"""Streaming endpoints for the F Prime Flask GDS.

The default REST API exposes channel and event histories that the front-end
polls on a timer. For high-rate deployments (many channels at high cadence)
polling is a poor fit: every poll re-serializes the full per-client history
and the browser parses a multi-megabyte response while still arriving
samples accumulate behind the request. This module supplements the REST
API with a WebSocket push channel.

A single :class:`StreamHub` registers itself with the F Prime pipeline as a
channel, event, command, and packet consumer. As data arrives the hub
enqueues a JSON envelope into the per-client outbox of each subscriber
whose subscription matches. A WebSocket route, registered on the Flask app
through :func:`register_stream_routes`, runs the per-client I/O loop and
drains the outbox to the wire.

The hub is designed to *never block* the F Prime decoder threads. Per-client
outboxes are bounded; on overflow the oldest item is dropped and a counter
is incremented so that overruns surface as telemetry rather than as a
stalled pipeline.

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
from typing import Any, Dict, Optional, Set

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


DEFAULT_QUEUE_DEPTH = 1024
"""Default per-client outbox depth (in messages)."""

DEFAULT_DRAIN_TIMEOUT_S = 0.05
"""Wait timeout for the sender thread between drains."""

DEFAULT_BATCH_WINDOW_S = 0.2
"""After the first envelope wakes the sender, wait this long for more to
accumulate before draining. Coalesces same-kind samples into a single
ws.send so the browser does one JSON.parse / handler dispatch per kind
per window instead of one per sample.

The window is intentionally close to the legacy ``/channels`` REST
poll cadence (500 ms by default) -- the front-end ``MappedHistory``
display only retains the latest sample per channel id, so anything
finer than a poll-interval is wasted work in the browser. Combined
with the per-id coalescing in ``_Subscriber``, this collapses
2800 channel samples/sec from the F Prime stress reference (80
``FrameOutNN`` channels at 35 Hz plus the rest of the deployment)
down to ~5 ws messages/sec carrying ~100 unique-id samples each.
Interactive command response still lands inside one window, so a
``Send Command`` click round-trips visibly in under half a second.
"""

DEFAULT_RECEIVE_TIMEOUT_S = 1.0
"""Wait timeout for the receive loop between subscription updates."""


class _Subscriber:
    """Per-WebSocket subscriber state held by :class:`StreamHub`."""

    __slots__ = (
        "id",
        "channels",
        "subscribe_all_channels",
        "events",
        "commands",
        "_outbox",
        "_latest_channels",
        "_outbox_lock",
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
        # Events and commands are unique and must be delivered in order,
        # so they ride a bounded deque. Channel samples, by contrast,
        # are dense and lossy by nature: the front-end ``MappedHistory``
        # only keeps the latest sample per channel id anyway, so we
        # coalesce on the way in and store ``{id: latest_envelope}``.
        # That bounds the channel state by the number of *unique* ids
        # (a few hundred in a typical deployment) instead of by the
        # incoming sample *rate*, which is what was producing tens of
        # thousands of "dropped" entries on the outbox at high cadence.
        self._outbox: deque = deque()
        self._latest_channels: Dict[int, Dict[str, Any]] = {}
        self._outbox_lock = threading.Lock()
        self._outbox_cv = threading.Condition(self._outbox_lock)
        self._max_depth = max_depth
        self.dropped = 0
        self.active = True

    def enqueue(self, envelope: Dict[str, Any]) -> None:
        with self._outbox_cv:
            if not self.active:
                return
            kind = envelope.get("type") if isinstance(envelope, dict) else None
            if kind == "channel":
                cid = envelope.get("id")
                if cid is not None:
                    # Replace any earlier sample for this channel.
                    # MappedHistory.send already discards everything but
                    # the latest per id; we just do it earlier so the
                    # wire and the drain stay small.
                    self._latest_channels[cid] = envelope
                else:
                    # Fallback path: channel without an id; treat as
                    # ordinary unique sample.
                    if len(self._outbox) >= self._max_depth:
                        try:
                            self._outbox.popleft()
                        except IndexError:
                            pass
                        self.dropped += 1
                    self._outbox.append(envelope)
            else:
                if len(self._outbox) >= self._max_depth:
                    # Drop oldest to keep latency bounded under sustained overrun.
                    try:
                        self._outbox.popleft()
                    except IndexError:
                        pass
                    self.dropped += 1
                self._outbox.append(envelope)
            self._outbox_cv.notify()

    def drain(self, timeout_s: float, batch_window_s: float = 0.0):
        """Drain queued envelopes, blocking up to ``timeout_s`` for the first.

        Once at least one envelope has arrived, the call sleeps for
        ``batch_window_s`` outside the condition lock so producers can
        add more envelopes to the batch before the drain runs. The
        whole outbox is then snapshotted in one shot. Returns an empty
        list when the subscriber has been closed or nothing arrived
        within ``timeout_s``.
        """
        with self._outbox_cv:
            if not self._outbox and not self._latest_channels:
                self._outbox_cv.wait(timeout=timeout_s)
            if not self.active:
                return []
            if not self._outbox and not self._latest_channels:
                return []
        if batch_window_s > 0:
            # Sleep outside the cv lock so the decoder thread can keep
            # enqueueing. The added latency (default ~50 ms) is the
            # window in which we coalesce same-kind samples into one
            # batched ws.send.
            time.sleep(batch_window_s)
        with self._outbox_cv:
            if not self.active:
                return []
            drained = list(self._outbox)
            self._outbox.clear()
            drained.extend(self._latest_channels.values())
            self._latest_channels.clear()
            return drained

    def close(self) -> None:
        with self._outbox_cv:
            self.active = False
            self._outbox.clear()
            self._latest_channels.clear()
            self._outbox_cv.notify_all()


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
            if not self._matches(sub, kind, target_id):
                continue
            # Enqueue the raw envelope; the sender thread coalesces
            # multiple same-kind envelopes drained together into a
            # single batched ws.send() payload.
            sub.enqueue(envelope)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _matches(sub: _Subscriber, kind: str, target_id: Optional[int]) -> bool:
        if kind == "channel":
            if sub.subscribe_all_channels:
                return True
            return target_id is not None and target_id in sub.channels
        if kind == "event":
            return sub.events
        if kind == "command":
            return sub.commands
        return False

    @staticmethod
    def _to_envelope(data) -> Optional[Dict[str, Any]]:
        if isinstance(data, ChData):
            return {
                "type": "channel",
                "id": data.id,
                "data": flask_json.minimal_channel(data),
            }
        if isinstance(data, EventData):
            return {
                "type": "event",
                "id": data.id,
                "data": flask_json.minimal_event(data),
            }
        if isinstance(data, CmdData):
            return {
                "type": "command",
                "id": data.id,
                "data": flask_json.minimal_command(data),
            }
        # Packetized telemetry is delivered to channel consumers as
        # individual :class:`ChData` objects by the packet decoder, so
        # there is no separate ``PktData`` envelope on the wire.
        return None


def _apply_subscription(sub: _Subscriber, message: Dict[str, Any]) -> None:
    """Apply a single subscription operation from the client."""
    op = (message.get("op") or "").lower()
    channels = message.get("channels")
    events = message.get("events")
    commands = message.get("commands")
    if op in ("subscribe", "sub"):
        if channels == "all" or channels is True:
            sub.subscribe_all_channels = True
        elif isinstance(channels, list):
            sub.channels.update(int(c) for c in channels)
        if events is not None:
            sub.events = bool(events)
        if commands is not None:
            sub.commands = bool(commands)
    elif op in ("unsubscribe", "unsub"):
        if channels == "all" or channels is True:
            sub.subscribe_all_channels = False
            sub.channels.clear()
        elif isinstance(channels, list):
            sub.channels.difference_update(int(c) for c in channels)
        if events is not None and not events:
            sub.events = False
        if commands is not None and not commands:
            sub.commands = False
    elif op == "replace":
        sub.subscribe_all_channels = channels == "all" or channels is True
        sub.channels = set()
        if isinstance(channels, list):
            sub.channels = set(int(c) for c in channels)
        sub.events = bool(events) if events is not None else False
        sub.commands = bool(commands) if commands is not None else False
    # Unknown ops are ignored silently; future-proofing.


def register_stream_routes(app, hub: StreamHub) -> bool:
    """Register the WebSocket route on the Flask app.

    Returns ``True`` if the route was registered, ``False`` if WebSocket
    support is unavailable or disabled via app configuration.
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
        sub = hub.register(max_depth=max_depth)
        ws_lock = threading.Lock()
        stop_event = threading.Event()

        def sender():
            try:
                while not stop_event.is_set() and sub.active:
                    batch = sub.drain(drain_timeout, batch_window)
                    if not batch:
                        continue
                    # Coalesce same-kind envelopes into a single batched
                    # payload so the browser does one JSON.parse + one
                    # handler dispatch per kind per drain, instead of
                    # one per sample. Order is preserved within each
                    # kind. Unknown-kind envelopes are passed through
                    # individually so we don't silently drop future
                    # envelope types.
                    grouped: Dict[str, list] = {}
                    passthrough = []
                    for envelope in batch:
                        kind = envelope.get("type") if isinstance(envelope, dict) else None
                        if kind in ("channel", "event", "command"):
                            grouped.setdefault(kind, []).append(envelope.get("data"))
                        else:
                            passthrough.append(envelope)
                    for kind, items in grouped.items():
                        if stop_event.is_set():
                            return
                        payload = json.dumps(
                            {"type": kind, "data": items},
                            default=flask_json.default,
                            allow_nan=True,
                        )
                        with ws_lock:
                            ws.send(payload)
                    for envelope in passthrough:
                        if stop_event.is_set():
                            return
                        payload = json.dumps(
                            envelope, default=flask_json.default, allow_nan=True
                        )
                        with ws_lock:
                            ws.send(payload)
            except Exception:
                logger.exception("StreamHub sender thread crashed")
                stop_event.set()

        sender_thread = threading.Thread(
            target=sender, name=f"fprime-gds-stream-sender-{sub.id[:8]}", daemon=True
        )

        try:
            with ws_lock:
                ws.send(json.dumps({"type": "hello", "subscriber_id": sub.id}))
            sender_thread.start()
            while not stop_event.is_set() and sub.active:
                try:
                    message = ws.receive(timeout=receive_timeout)
                except Exception:
                    break
                if message is None:
                    continue
                try:
                    parsed = json.loads(message)
                except Exception:
                    with ws_lock:
                        ws.send(json.dumps({"type": "error", "message": "invalid JSON"}))
                    continue
                if isinstance(parsed, dict):
                    _apply_subscription(sub, parsed)
        finally:
            stop_event.set()
            hub.unregister(sub)
            sender_thread.join(timeout=1.0)

    return True
