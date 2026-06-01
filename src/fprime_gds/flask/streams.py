"""Streaming endpoints for the F Prime Flask GDS.

The default REST API exposes channel and event histories that the front-end
polls on a timer. For high-rate deployments (many channels at high cadence)
polling is a poor fit: every poll re-serializes the full per-client history
and the browser parses a multi-megabyte response while still-arriving
samples accumulate behind the request. This module supplements the REST
API with a WebSocket push channel.

A single :class:`StreamHub` registers itself with the F Prime pipeline as a
channel, event, and command consumer. As data arrives the hub enqueues a
JSON envelope into the per-client outbox of each subscriber whose
subscription matches. A WebSocket route, registered on the Flask app
through :func:`register_stream_routes`, runs the per-client I/O loop and
drains the outbox to the wire.

The hub is designed to **never block** the F Prime decoder threads.
Per-client outboxes are bounded; channel samples are coalesced per id
(the front-end ``MappedHistory`` already retains only the latest sample
per channel id, so coalescing on the way *in* preserves identical display
semantics while bounding the channel state by the number of *unique* ids
instead of the incoming sample *rate*). Events and commands are unique
and ride a bounded FIFO; on overflow the oldest item is dropped and a
counter is incremented so that overruns surface as telemetry rather than
as a stalled pipeline.

The WebSocket support is conditional on the optional ``flask-sock``
dependency. If unavailable, :func:`register_stream_routes` is a no-op and
the rest of the GDS continues to operate via REST polling.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.data_types.cmd_data import CmdData
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.handlers import DataHandler
from fprime_gds.flask import json as flask_json

try:  # pragma: no cover - optional dependency
    from flask_sock import Sock
    HAVE_FLASK_SOCK = True
except Exception:  # pragma: no cover - import-time fallback
    Sock = None  # type: ignore[assignment]
    HAVE_FLASK_SOCK = False


logger = logging.getLogger("fprime_gds.flask.streams")


# ---------------------------------------------------------------------------
# Envelope kinds. The names are part of the wire protocol; the values are
# also used as the discriminator in :func:`StreamHub._to_envelope` and on
# the client side in ``stream.js`` (see ``ENVELOPE_TYPE_*``).
#
# Two flavours:
#
# * High-rate kinds (``channel``/``event``/``command``) come from the
#   F Prime pipeline as individual decoded objects. They are coalesced
#   per ``_BATCHABLE_KINDS`` into one ``ws.send`` per drain window.
# * Snapshot kinds (``logdata``/``upfiles``/``downfiles``/``stats``)
#   come from REST resource getters that the GDS already exposes; the
#   :class:`PeriodicBroadcaster` polls them on a server-side timer and
#   pushes the full payload over the WS. The wire shape mirrors the
#   REST response exactly so the front-end's existing processor
#   pipeline runs unchanged regardless of transport.
# ---------------------------------------------------------------------------
KIND_CHANNEL = "channel"
KIND_EVENT = "event"
KIND_COMMAND = "command"
KIND_HELLO = "hello"
KIND_ERROR = "error"
KIND_LOGDATA = "logdata"
KIND_UPFILES = "upfiles"
KIND_DOWNFILES = "downfiles"
KIND_STATS = "stats"

#: Kinds that are coalesced into a per-kind batched ``ws.send`` payload by
#: the sender thread. Other kinds are passed through individually so future
#: envelope types don't silently merge into something they shouldn't.
_BATCHABLE_KINDS = (KIND_CHANNEL, KIND_EVENT, KIND_COMMAND)

#: Kinds that are sent to **every** subscriber regardless of subscription
#: filter. These are low-rate full snapshots replacing the legacy REST
#: polls (logdata, file lists, stats) so that with the WebSocket open
#: the front-end has no reason to keep any data-bearing poll alive.
_BROADCAST_KINDS = (KIND_LOGDATA, KIND_UPFILES, KIND_DOWNFILES, KIND_STATS)


DEFAULT_QUEUE_DEPTH = 1024
"""Default per-client outbox depth (in messages)."""

DEFAULT_DRAIN_TIMEOUT_S = 0.05
"""Wait timeout for the sender thread between drains."""

DEFAULT_BATCH_WINDOW_S = 0.028
"""After the first envelope wakes the sender, wait this long for more to
accumulate before draining. Coalesces same-kind samples into a single
``ws.send`` so the browser does one ``JSON.parse`` / handler dispatch per
kind per window instead of one per sample.

Default is sized to one F Prime frame at 35 Hz (1/35 s = 28.6 ms).
For live-rendering consumers like the DOOM display addon, this lets
the browser observe each emitted frame instead of a coalesced ~7-frame
window; for table-style consumers (the channels tab, etc.) it is
harmless because the front-end ``MappedHistory`` still retains only
the latest sample per channel id.

For deployments that do not need that update rate, set
``STREAM_BATCH_WINDOW_S`` in the Flask config (or the
``FP_STREAM_BATCH_WINDOW_S`` env var) to a larger value -- e.g.
``0.2`` to match the legacy ``/channels`` REST poll cadence and cut
the browser-side dispatch rate roughly 7x.
"""

DEFAULT_RECEIVE_TIMEOUT_S = 1.0
"""Wait timeout for the receive loop between subscription updates."""


# ---------------------------------------------------------------------------
# Per-client subscriber state
# ---------------------------------------------------------------------------

class _Subscriber:
    """Per-WebSocket subscriber state held by :class:`StreamHub`.

    Holds:

    * the subscription filter (which channels / events / commands this
      client wants),
    * a bounded outbox for events and commands (FIFO, drop-oldest on
      overflow),
    * a per-id coalescing dict for channel samples (the front-end
      ``MappedHistory`` only keeps the latest per id, so we coalesce on
      the way in rather than letting bursts overflow the outbox).
    """

    __slots__ = (
        "id",
        "channels",
        "subscribe_all_channels",
        "events",
        "commands",
        "_outbox",
        "_latest_channels",
        "_outbox_cv",
        "_max_depth",
        "dropped",
        "active",
    )

    def __init__(self, sub_id: str, max_depth: int):
        self.id = sub_id
        # The hub fans out *everything* by default. Clients may narrow
        # later by sending a ``{"op": "replace", ...}`` or
        # ``{"op": "unsub", ...}`` payload over the WebSocket. This
        # avoids race conditions where a slow first subscription request
        # would otherwise drop frames that arrive between the WS
        # handshake and the first ``replace`` payload.
        self.channels: Set[int] = set()
        self.subscribe_all_channels = True
        self.events = True
        self.commands = True
        # See the per-id coalescing rationale on the class docstring.
        self._outbox: deque = deque()
        self._latest_channels: Dict[int, Dict[str, Any]] = {}
        self._outbox_cv = threading.Condition()
        self._max_depth = max_depth
        self.dropped = 0
        self.active = True

    # ------------------------------------------------------------------
    # Subscription filter
    # ------------------------------------------------------------------
    def matches(self, kind: str, target_id: Optional[int]) -> bool:
        """Return whether an envelope of ``kind`` should fan out to us."""
        if kind == KIND_CHANNEL:
            if self.subscribe_all_channels:
                return True
            return target_id is not None and target_id in self.channels
        if kind == KIND_EVENT:
            return self.events
        if kind == KIND_COMMAND:
            return self.commands
        if kind in _BROADCAST_KINDS:
            # Snapshot kinds are always fanned out so that an open WS
            # client never falls behind the REST polls it replaces.
            return True
        return False

    def apply_subscription(self, message: Dict[str, Any]) -> None:
        """Apply a single subscription operation from the client.

        Supports three operations:

        * ``"subscribe"`` / ``"sub"`` — add to the current subscription
          (a channel list extends the set; ``"all"``/``True`` broadens
          to all channels; ``events``/``commands`` toggle on).
        * ``"unsubscribe"`` / ``"unsub"`` — remove from the current
          subscription (a channel list shrinks the set; ``"all"`` clears
          the channels; ``events``/``commands`` toggle off if falsy).
        * ``"replace"`` — replace the subscription wholesale.

        Unknown ops are ignored silently, leaving the door open for
        protocol extensions.
        """
        op = (message.get("op") or "").lower()
        channels = message.get("channels")
        events = message.get("events")
        commands = message.get("commands")
        if op in ("subscribe", "sub"):
            if channels == "all" or channels is True:
                self.subscribe_all_channels = True
            elif isinstance(channels, list):
                self.channels.update(int(c) for c in channels)
            if events is not None:
                self.events = bool(events)
            if commands is not None:
                self.commands = bool(commands)
        elif op in ("unsubscribe", "unsub"):
            if channels == "all" or channels is True:
                self.subscribe_all_channels = False
                self.channels.clear()
            elif isinstance(channels, list):
                self.channels.difference_update(int(c) for c in channels)
            if events is not None and not events:
                self.events = False
            if commands is not None and not commands:
                self.commands = False
        elif op == "replace":
            self.subscribe_all_channels = channels == "all" or channels is True
            self.channels = set()
            if isinstance(channels, list):
                self.channels = set(int(c) for c in channels)
            self.events = bool(events) if events is not None else False
            self.commands = bool(commands) if commands is not None else False

    # ------------------------------------------------------------------
    # Outbox
    # ------------------------------------------------------------------
    def enqueue(self, envelope: Dict[str, Any]) -> None:
        """Enqueue an envelope into this subscriber's outbox.

        For channel envelopes with a known id, coalesces with any prior
        sample for the same id (latest wins). All other envelopes ride a
        FIFO deque bounded to ``max_depth``; overflow drops the oldest
        entry and bumps the ``dropped`` counter.
        """
        with self._outbox_cv:
            if not self.active:
                return
            kind = envelope.get("type") if isinstance(envelope, dict) else None
            if kind == KIND_CHANNEL:
                cid = envelope.get("id")
                if cid is not None:
                    self._latest_channels[cid] = envelope
                else:
                    self._push_bounded(envelope)
            else:
                self._push_bounded(envelope)
            self._outbox_cv.notify()

    def _push_bounded(self, envelope: Dict[str, Any]) -> None:
        """Append to the FIFO outbox, drop-oldest on overflow.

        Caller must hold ``self._outbox_cv``.
        """
        if len(self._outbox) >= self._max_depth:
            try:
                self._outbox.popleft()
            except IndexError:
                pass
            self.dropped += 1
        self._outbox.append(envelope)

    def drain(self, timeout_s: float, batch_window_s: float = 0.0) -> List[Dict[str, Any]]:
        """Drain queued envelopes, blocking up to ``timeout_s`` for the first.

        Once at least one envelope has arrived, the call sleeps for
        ``batch_window_s`` outside the condition lock so producers can
        add more envelopes to the batch before the drain runs. The
        whole outbox is then snapshotted in one shot. Returns an empty
        list when the subscriber has been closed or nothing arrived
        within ``timeout_s``.
        """
        with self._outbox_cv:
            if self._empty_locked():
                self._outbox_cv.wait(timeout=timeout_s)
            if not self.active or self._empty_locked():
                return []
        if batch_window_s > 0:
            # Sleep outside the cv lock so the decoder thread can keep
            # enqueueing. The added latency is the window in which we
            # coalesce same-kind samples into one batched ws.send.
            time.sleep(batch_window_s)
        with self._outbox_cv:
            if not self.active:
                return []
            drained = list(self._outbox)
            self._outbox.clear()
            drained.extend(self._latest_channels.values())
            self._latest_channels.clear()
            return drained

    def _empty_locked(self) -> bool:
        """Whether both the outbox and the per-id channel slot are empty.

        Caller must hold ``self._outbox_cv``.
        """
        return not self._outbox and not self._latest_channels

    def close(self) -> None:
        """Mark the subscriber inactive and wake any blocked drain."""
        with self._outbox_cv:
            self.active = False
            self._outbox.clear()
            self._latest_channels.clear()
            self._outbox_cv.notify_all()


# ---------------------------------------------------------------------------
# Backward-compatible module-level alias. Tests and older callers may still
# call ``_apply_subscription(sub, message)``; new code should use
# ``sub.apply_subscription(message)`` directly.
# ---------------------------------------------------------------------------

def _apply_subscription(sub: _Subscriber, message: Dict[str, Any]) -> None:
    sub.apply_subscription(message)


# ---------------------------------------------------------------------------
# StreamHub: pipeline integration + fan-out
# ---------------------------------------------------------------------------

class StreamHub(DataHandler):
    """Fan-out of F Prime decoded data to WebSocket subscribers."""

    def __init__(self, max_depth: int = DEFAULT_QUEUE_DEPTH):
        self._max_depth = max_depth
        self._subscribers: Dict[str, _Subscriber] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Pipeline registration
    # ------------------------------------------------------------------
    def attach_to_pipeline(self, pipeline) -> None:
        """Register this hub with the standard pipeline's decoders.

        ``register_channel_consumer`` already registers the consumer with
        the packet decoder when one is configured, so we do not call
        ``register_packet_consumer`` explicitly here -- doing so would
        cause every packetized channel to be delivered twice.
        """
        coders = pipeline.coders
        coders.register_channel_consumer(self)
        coders.register_event_consumer(self)
        coders.register_command_consumer(self)

    # ------------------------------------------------------------------
    # Subscriber lifecycle
    # ------------------------------------------------------------------
    def register(self, max_depth: Optional[int] = None) -> _Subscriber:
        sub = _Subscriber(str(uuid.uuid4()), max_depth or self._max_depth)
        with self._lock:
            self._subscribers[sub.id] = sub
        return sub

    def unregister(self, sub: _Subscriber) -> None:
        with self._lock:
            self._subscribers.pop(sub.id, None)
        sub.close()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "clients": len(self._subscribers),
                "dropped": sum(s.dropped for s in self._subscribers.values()),
            }

    # ------------------------------------------------------------------
    # Snapshot fan-out
    # ------------------------------------------------------------------
    def broadcast(self, envelope: Dict[str, Any]) -> None:
        """Fan a single pre-built envelope to all current subscribers.

        Used by :class:`PeriodicBroadcaster` for the snapshot kinds
        (logdata, file lists, stats) where a server-side timer pushes
        full payloads instead of having the F Prime pipeline drive
        delivery. The envelope ``type`` is matched per subscriber, so
        the existing kind-filtering applies; for the snapshot kinds
        :meth:`_Subscriber.matches` always returns ``True`` today.
        """
        if not isinstance(envelope, dict) or "type" not in envelope:
            return
        with self._lock:
            subscribers = list(self._subscribers.values())
        if not subscribers:
            return
        kind = envelope["type"]
        target_id = envelope.get("id")
        for sub in subscribers:
            if sub.matches(kind, target_id):
                sub.enqueue(envelope)

    # ------------------------------------------------------------------
    # DataHandler API
    # ------------------------------------------------------------------
    def data_callback(self, data, sender=None) -> None:
        try:
            envelope = self._to_envelope(data)
        except Exception:  # pragma: no cover - defensive
            logger.exception("StreamHub: failed to serialize datum")
            return
        if envelope is None:
            return
        with self._lock:
            subscribers = list(self._subscribers.values())
        if not subscribers:
            return
        target_id = envelope.get("id")
        kind = envelope["type"]
        for sub in subscribers:
            if sub.matches(kind, target_id):
                sub.enqueue(envelope)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_envelope(data) -> Optional[Dict[str, Any]]:
        if isinstance(data, ChData):
            return {
                "type": KIND_CHANNEL,
                "id": data.id,
                "data": flask_json.minimal_channel(data),
            }
        if isinstance(data, EventData):
            return {
                "type": KIND_EVENT,
                "id": data.id,
                "data": flask_json.minimal_event(data),
            }
        if isinstance(data, CmdData):
            return {
                "type": KIND_COMMAND,
                "id": data.id,
                "data": flask_json.minimal_command(data),
            }
        # Packetized telemetry is delivered to channel consumers as
        # individual :class:`ChData` objects by the packet decoder, so
        # there is no separate ``PktData`` envelope on the wire.
        return None


# ---------------------------------------------------------------------------
# Periodic broadcaster: replaces the front-end REST polls for snapshot data
# ---------------------------------------------------------------------------

#: Default cadence at which :class:`PeriodicBroadcaster` polls its sources.
#: 1 Hz matches (and in practice slightly under-runs) the legacy REST poll
#: cadence for ``/logdata``, ``/upload/files``, ``/download/files``, and
#: ``/stats`` -- those endpoints serve small payloads whose freshness is
#: not bound to the F Prime pipeline cadence, so 1 s is a fine default.
DEFAULT_BROADCAST_INTERVAL_S = 1.0


class PeriodicBroadcaster:
    """Server-side timer that pushes snapshot envelopes over the hub.

    The single WebSocket is now the canonical data path for the
    front-end. The high-rate kinds (channel/event/command) are driven
    by the F Prime pipeline through :meth:`StreamHub.data_callback`;
    the low-rate snapshot kinds (``logdata``, ``upfiles``, ``downfiles``,
    ``stats``) are driven by this class so that an open WS subscriber
    sees up-to-date snapshots without the front-end having to keep any
    parallel REST poll alive.

    Sources are ``{kind: callable}`` where each callable returns the
    same shape the corresponding REST resource returns from
    ``Resource.get()``. A failed source logs an exception and is
    skipped for that tick; the broadcaster keeps running so a single
    misbehaving source can't take the rest down.
    """

    def __init__(
        self,
        hub: StreamHub,
        sources: Optional[Dict[str, Callable[[], Any]]] = None,
        interval_s: float = DEFAULT_BROADCAST_INTERVAL_S,
    ) -> None:
        self._hub = hub
        self._sources: Dict[str, Callable[[], Any]] = dict(sources or {})
        self._interval = float(interval_s)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def kinds(self) -> List[str]:
        """Snapshot kinds currently being broadcast (test/diagnostic hook)."""
        return list(self._sources.keys())

    def register_source(self, kind: str, getter: Callable[[], Any]) -> None:
        """Register or replace a snapshot source."""
        self._sources[kind] = getter

    def start(self) -> None:
        """Start the background thread. Idempotent."""
        if self._thread is not None:
            return
        if not self._sources:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="fprime-gds-stream-broadcaster",
            daemon=True,
        )
        self._thread.start()

    def stop(self, join_timeout_s: float = 1.0) -> None:
        """Stop the background thread. Safe to call multiple times."""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=join_timeout_s)

    def tick(self) -> None:
        """Run one broadcast cycle synchronously.

        Exposed for unit tests (so we don't have to wait for the timer)
        and as a small hook future code can use to force a snapshot
        push outside the timer cadence.
        """
        for kind, get_data in list(self._sources.items()):
            try:
                data = get_data()
            except Exception:
                logger.exception(
                    "PeriodicBroadcaster: source %r raised; skipping tick", kind
                )
                continue
            self._hub.broadcast({"type": kind, "data": data})

    def _loop(self) -> None:
        # Use ``Event.wait`` rather than ``time.sleep`` so ``stop()`` can
        # wake the loop up promptly during shutdown.
        while not self._stop.wait(self._interval):
            self.tick()


# ---------------------------------------------------------------------------
# Wire encoding helpers (shared by sender thread + tests)
# ---------------------------------------------------------------------------

def _encode(payload: Any) -> str:
    """JSON-encode an envelope (or batched envelope) for the wire.

    Centralized so the encoder options stay consistent across the
    grouped and pass-through paths.
    """
    return json.dumps(payload, default=flask_json.default, allow_nan=True)


def _group_batch(envelopes: Iterable[Dict[str, Any]]):
    """Split a drained batch into per-kind grouped lists + a passthrough.

    Returns ``(grouped, passthrough)`` where:

    * ``grouped`` is ``{kind: [data, ...]}`` containing the inner
      ``data`` payload of each envelope, suitable for sending as one
      batched ``{"type": kind, "data": [...]}`` envelope.
    * ``passthrough`` is a list of envelopes whose kind is not in
      :data:`_BATCHABLE_KINDS` (future envelope types); these are
      forwarded individually so unknown kinds don't get silently
      merged.

    Order is preserved within each kind.
    """
    grouped: Dict[str, list] = {}
    passthrough: List[Dict[str, Any]] = []
    for envelope in envelopes:
        kind = envelope.get("type") if isinstance(envelope, dict) else None
        if kind in _BATCHABLE_KINDS:
            grouped.setdefault(kind, []).append(envelope.get("data"))
        else:
            passthrough.append(envelope)
    return grouped, passthrough


# ---------------------------------------------------------------------------
# Per-connection session (sender + receiver threads)
# ---------------------------------------------------------------------------

class _StreamSession:
    """Run the sender + receiver loops for one WebSocket connection.

    Lifecycle:

    1. ``__init__`` registers a subscriber on the hub and creates the
       lock used to serialize ``ws.send`` calls across the two threads.
    2. ``run`` greets the client, spawns the sender thread, and blocks
       in the receive loop processing subscription updates from the
       client until the connection closes or an error trips
       ``stop_event``.
    3. On exit the subscriber is unregistered and the sender thread
       joined.

    Pulled into a class so the long-running loops are testable in
    isolation rather than living as nested closures inside
    :func:`register_stream_routes`.
    """

    def __init__(
        self,
        ws,
        hub: StreamHub,
        max_depth: int,
        drain_timeout: float,
        batch_window: float,
        receive_timeout: float,
    ) -> None:
        self._ws = ws
        self._hub = hub
        self._drain_timeout = drain_timeout
        self._batch_window = batch_window
        self._receive_timeout = receive_timeout
        self._sub = hub.register(max_depth=max_depth)
        self._ws_lock = threading.Lock()
        self._stop = threading.Event()

    def run(self) -> None:
        thread = threading.Thread(
            target=self._sender_loop,
            name=f"fprime-gds-stream-sender-{self._sub.id[:8]}",
            daemon=True,
        )
        try:
            self._send({"type": KIND_HELLO, "subscriber_id": self._sub.id})
            thread.start()
            self._receiver_loop()
        finally:
            self._stop.set()
            self._hub.unregister(self._sub)
            thread.join(timeout=1.0)

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------
    def _sender_loop(self) -> None:
        try:
            while not self._stop.is_set() and self._sub.active:
                batch = self._sub.drain(self._drain_timeout, self._batch_window)
                if not batch:
                    continue
                grouped, passthrough = _group_batch(batch)
                for kind, items in grouped.items():
                    if self._stop.is_set():
                        return
                    self._send_raw(_encode({"type": kind, "data": items}))
                for envelope in passthrough:
                    if self._stop.is_set():
                        return
                    self._send_raw(_encode(envelope))
        except Exception:
            logger.exception("StreamHub sender thread crashed")
            self._stop.set()

    def _receiver_loop(self) -> None:
        while not self._stop.is_set() and self._sub.active:
            try:
                message = self._ws.receive(timeout=self._receive_timeout)
            except Exception:
                break
            if message is None:
                continue
            try:
                parsed = json.loads(message)
            except Exception:
                self._send({"type": KIND_ERROR, "message": "invalid JSON"})
                continue
            if isinstance(parsed, dict):
                self._sub.apply_subscription(parsed)

    # ------------------------------------------------------------------
    # Wire I/O
    # ------------------------------------------------------------------
    def _send(self, payload: Dict[str, Any]) -> None:
        """Encode + send a single envelope. Mirrors the sender path so
        the hello / error frames go out under the same lock."""
        self._send_raw(_encode(payload))

    def _send_raw(self, payload: str) -> None:
        with self._ws_lock:
            self._ws.send(payload)


# ---------------------------------------------------------------------------
# Flask route registration
# ---------------------------------------------------------------------------

def register_stream_routes(app, hub: StreamHub) -> bool:
    """Register the WebSocket route on the Flask app.

    Returns ``True`` if the route was registered, ``False`` if WebSocket
    support is unavailable or disabled via app configuration. When this
    returns ``False`` the ``/api/stream`` URL is **not** added to the
    app, so a client that probes ``/api/stream/status`` will see
    ``active: False`` and the front-end will stay on REST polling.
    """
    if not HAVE_FLASK_SOCK:
        logger.info("flask-sock not installed; WebSocket stream disabled")
        return False
    if not app.config.get("STREAM_ENABLED", True):
        logger.info("STREAM_ENABLED is False; WebSocket stream disabled")
        return False

    sock = Sock(app)
    drain_timeout = float(app.config.get("STREAM_DRAIN_TIMEOUT_S", DEFAULT_DRAIN_TIMEOUT_S))
    batch_window = float(app.config.get("STREAM_BATCH_WINDOW_S", DEFAULT_BATCH_WINDOW_S))
    max_depth = int(app.config.get("STREAM_QUEUE_DEPTH", DEFAULT_QUEUE_DEPTH))
    receive_timeout = float(app.config.get("STREAM_RECEIVE_TIMEOUT_S", DEFAULT_RECEIVE_TIMEOUT_S))

    @sock.route("/api/stream")
    def _stream(ws):  # pragma: no cover - exercised via integration tests
        session = _StreamSession(
            ws=ws,
            hub=hub,
            max_depth=max_depth,
            drain_timeout=drain_timeout,
            batch_window=batch_window,
            receive_timeout=receive_timeout,
        )
        session.run()

    return True
