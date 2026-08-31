"""
Tests the event decoder, in particular decoding several events packed into a
single buffer (as delivered when the flight software emits events in quick
succession).

Regression test for nasa/fprime#4620: the decoder advanced its read pointer by
the absolute end offset returned from ``decode_args`` instead of using it as the
new position, so every event after the first in a multi-event buffer was parsed
from the wrong offset and came back corrupted.
"""

from fprime_gds.common.decoders.event_decoder import EventDecoder
from fprime_gds.common.models.serialize.numerical_types import U32Type
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.templates.event_template import EventTemplate
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.utils.event_severity import EventSeverity


def _make_template():
    return EventTemplate(
        101,
        "test_evr",
        "test_comp",
        [("value", "the value", U32Type)],
        EventSeverity["ACTIVITY_LO"],
        "value {}",
    )


def _serialize_event(event_id, useconds, value):
    """Build the raw bytes the decoder consumes: id + time + args."""
    id_obj = ConfigManager().get_type("FwEventIdType")()
    id_obj.val = event_id
    time_obj = TimeType(
        TimeType.TimeBase("TB_WORKSTATION_TIME"), 0, 1533758629, useconds
    )
    return id_obj.serialize() + time_obj.serialize() + U32Type(value).serialize()


def test_event_decoder_single_event():
    decoder = EventDecoder({101: _make_template()})

    events = decoder.decode_api(_serialize_event(101, 100, 42))

    assert len(events) == 1
    assert events[0].time.useconds == 100
    assert events[0].args[0].val == 42


def test_event_decoder_multiple_events_in_one_buffer():
    decoder = EventDecoder({101: _make_template()})

    buffer = (
        _serialize_event(101, 111, 23351024)
        + _serialize_event(101, 222, 23351023)
        + _serialize_event(101, 333, 23351022)
    )
    events = decoder.decode_api(buffer)

    assert len(events) == 3
    decoded = [(event.time.useconds, event.args[0].val) for event in events]
    assert decoded == [(111, 23351024), (222, 23351023), (333, 23351022)]
