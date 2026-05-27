"""Unit tests for :mod:`fprime_gds.flask.streams`.

Focus is on the parts that have actually bitten us in browser testing:
the per-channel coalescing inside ``_Subscriber`` (so a dense channel
burst can no longer fill the bounded outbox and cause drops), the
event/command path that must *not* coalesce, and the close handshake.
"""

from __future__ import annotations

import threading
import time

import pytest

from fprime_gds.flask import streams


def _channel(cid: int, val: object = 0, ert: float = 0.0):
    return {"type": "channel", "id": cid, "data": {"id": cid, "val": val, "ert": ert}}


def _event(eid: int, val: object = 0):
    return {"type": "event", "id": eid, "data": {"id": eid, "val": val}}


def _command(cid: int, val: object = 0):
    return {"type": "command", "id": cid, "data": {"id": cid, "val": val}}


def test_channel_enqueue_coalesces_by_id():
    sub = streams._Subscriber("s", max_depth=4)
    # 1000 samples, only 3 unique ids -> outbox stays small, no drops
    for i in range(1000):
        sub.enqueue(_channel(i % 3, val=i))
    drained = sub.drain(timeout_s=0)
    by_id = {env["id"]: env for env in drained}
    assert set(by_id.keys()) == {0, 1, 2}
    # Each id keeps the LATEST sample (highest ``val``) we enqueued.
    assert by_id[0]["data"]["val"] == 999
    assert by_id[1]["data"]["val"] == 997
    assert by_id[2]["data"]["val"] == 998
    assert sub.dropped == 0


def test_event_path_does_not_coalesce_and_drops_on_overflow():
    sub = streams._Subscriber("s", max_depth=4)
    # 10 unique events; the deque is bounded to 4.
    for i in range(10):
        sub.enqueue(_event(i))
    drained = sub.drain(timeout_s=0)
    # Oldest is dropped to keep latency bounded under sustained overrun.
    assert [env["id"] for env in drained] == [6, 7, 8, 9]
    assert sub.dropped == 6


def test_command_path_does_not_coalesce():
    sub = streams._Subscriber("s", max_depth=8)
    for i in range(3):
        sub.enqueue(_command(42, val=i))
    drained = sub.drain(timeout_s=0)
    # Commands carry per-issue side effects; we must not lose any of
    # them just because two were issued back-to-back.
    assert [env["data"]["val"] for env in drained] == [0, 1, 2]


def test_drain_mixed_kinds_preserves_outbox_then_channels():
    sub = streams._Subscriber("s", max_depth=8)
    sub.enqueue(_event(1))
    sub.enqueue(_channel(100, val="a"))
    sub.enqueue(_event(2))
    sub.enqueue(_channel(100, val="b"))
    sub.enqueue(_command(7))
    drained = sub.drain(timeout_s=0)
    types_in_order = [env["type"] for env in drained]
    # Events/commands ride the FIFO outbox; channels are appended after,
    # coalesced to the latest value per id.
    assert types_in_order == ["event", "event", "command", "channel"]
    chan_envs = [env for env in drained if env["type"] == "channel"]
    assert chan_envs[0]["data"]["val"] == "b"


def test_drain_returns_empty_after_close():
    sub = streams._Subscriber("s", max_depth=4)
    sub.enqueue(_channel(1))
    sub.enqueue(_event(2))
    sub.close()
    assert sub.drain(timeout_s=0) == []
    # Subsequent enqueues on a closed subscriber are no-ops.
    sub.enqueue(_channel(3))
    sub.enqueue(_event(4))
    assert sub.drain(timeout_s=0) == []


def test_drain_blocks_until_first_envelope_then_batches():
    sub = streams._Subscriber("s", max_depth=16)

    def producer():
        time.sleep(0.02)
        for cid in (1, 2, 3):
            sub.enqueue(_channel(cid, val=cid))
        # Give the batch window a chance to absorb a follow-up update
        # for an existing channel id.
        time.sleep(0.005)
        sub.enqueue(_channel(2, val="latest"))

    t = threading.Thread(target=producer, daemon=True)
    t.start()
    drained = sub.drain(timeout_s=1.0, batch_window_s=0.05)
    t.join(timeout=1.0)
    by_id = {env["id"]: env["data"]["val"] for env in drained}
    assert by_id == {1: 1, 2: "latest", 3: 3}


def test_apply_subscription_replace_narrows_default_all():
    sub = streams._Subscriber("s", max_depth=4)
    # Defaults: subscribed to everything (channels=all, events, commands).
    assert sub.subscribe_all_channels is True
    assert sub.events is True
    assert sub.commands is True

    streams._apply_subscription(
        sub, {"op": "replace", "channels": [10, 20], "events": True, "commands": False}
    )
    assert sub.subscribe_all_channels is False
    assert sub.channels == {10, 20}
    assert sub.events is True
    assert sub.commands is False

    # ``channels: "all"`` re-broadens.
    streams._apply_subscription(
        sub, {"op": "replace", "channels": "all", "events": False, "commands": True}
    )
    assert sub.subscribe_all_channels is True
    assert sub.channels == set()
    assert sub.events is False
    assert sub.commands is True


def test_apply_subscription_unsub_clears_all_channels():
    sub = streams._Subscriber("s", max_depth=4)
    sub.subscribe_all_channels = False
    sub.channels = {1, 2, 3}
    streams._apply_subscription(sub, {"op": "unsub", "channels": [2]})
    assert sub.channels == {1, 3}
    streams._apply_subscription(sub, {"op": "unsub", "channels": "all"})
    assert sub.subscribe_all_channels is False
    assert sub.channels == set()


def test_hub_fanout_skips_unsubscribed_kinds():
    hub = streams.StreamHub(max_depth=4)
    sub = hub.register()
    sub.events = False
    sub.commands = False
    hub.data_callback(_FakeChan(id=1, val=1))
    hub.data_callback(_FakeEvent(id=2, val=2))
    hub.data_callback(_FakeCmd(id=3, val=3))
    drained = sub.drain(timeout_s=0)
    # Only the channel envelope makes it through.
    assert len(drained) == 1
    assert drained[0]["type"] == "channel"


def test_hub_stats_aggregates_drops():
    hub = streams.StreamHub(max_depth=2)
    sub_a = hub.register()
    sub_b = hub.register()
    # Force drops on the event path of both subscribers.
    for i in range(5):
        sub_a.enqueue(_event(i))
        sub_b.enqueue(_event(i))
    stats = hub.stats()
    assert stats["clients"] == 2
    assert stats["dropped"] >= 1


# ---------------------------------------------------------------------------
# Light-weight test doubles so we can exercise StreamHub without dragging in
# the full F Prime decoder/dictionary machinery.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_minimal(monkeypatch):
    """Replace the JSON minimisers with identity functions so the tests
    can pass plain values through without building real ChData/EventData/
    CmdData objects (those require dictionaries to construct)."""
    from fprime_gds.flask import json as flask_json

    monkeypatch.setattr(flask_json, "minimal_channel", lambda d: {"id": d.id, "val": d.val})
    monkeypatch.setattr(flask_json, "minimal_event", lambda d: {"id": d.id, "val": d.val})
    monkeypatch.setattr(flask_json, "minimal_command", lambda d: {"id": d.id, "val": d.val})


class _FakeChan:
    """Stand-in that passes ``isinstance(data, ChData)`` checks.

    We rebind ``ChData`` in the streams module to this class for the
    duration of the test so ``StreamHub._to_envelope`` routes to the
    channel branch without us needing to construct a real ``ChData``.
    """

    def __init__(self, id: int, val: object):
        self.id = id
        self.val = val


class _FakeEvent:
    def __init__(self, id: int, val: object):
        self.id = id
        self.val = val


class _FakeCmd:
    def __init__(self, id: int, val: object):
        self.id = id
        self.val = val


@pytest.fixture(autouse=True)
def _rebind_fprime_types(monkeypatch):
    monkeypatch.setattr(streams, "ChData", _FakeChan)
    monkeypatch.setattr(streams, "EventData", _FakeEvent)
    monkeypatch.setattr(streams, "CmdData", _FakeCmd)
