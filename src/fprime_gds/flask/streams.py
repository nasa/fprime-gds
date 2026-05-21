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
        self._outbox: deque = deque()
        self._outbox_lock = threading.Lock()
        self._outbox_cv = threading.Condition(self._outbox_lock)
        self._max_depth = max_depth
        self.dropped = 0
        self.active = True

    def enqueue(self, message: str) -> None:
        with self._outbox_cv:
            if not self.active:
                return
            if len(self._outbox) >= self._max_depth:
                # Drop oldest to keep latency bounded under sustained overrun.
                try:
                    self._outbox.popleft()
                except IndexError:
                    pass
                self.dropped += 1
            self._outbox.append(message)
            self._outbox_cv.notify()

    def drain(self, timeout_s: float):
        """Yield queued messages, blocking up to ``timeout_s`` for the first.

        Subsequent messages are yielded as long as they are immediately
        available so a burst is delivered in a single batch. Returns an
        empty iterable when the subscriber has been closed.
        """
        with self._outbox_cv:
            if not self._outbox:
                self._outbox_cv.wait(timeout=timeout_s)
            if not self.active:
                return []
            drained = list(self._outbox)
            self._outbox.clear()
            return drained

    def close(self) -> None:
        with self._outbox_cv:
            self.active = False
            self._outbox.clear()
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
        payload = json.dumps(envelope, default=flask_json.default, allow_nan=True)
        target_id = envelope.get("id")
        kind = envelope["type"]
        for sub in subscribers:
            if not self._matches(sub, kind, target_id):
                continue
            sub.enqueue(payload)

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
                    batch = sub.drain(drain_timeout)
                    if not batch:
                        continue
                    for payload in batch:
                        if stop_event.is_set():
                            return
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
