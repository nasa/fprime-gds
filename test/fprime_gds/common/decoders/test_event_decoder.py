"""
Tests the event decoder
"""

from fprime_gds.common.decoders.event_decoder import EventDecoder
from fprime_gds.common.models.serialize.bool_type import BoolType
from fprime_gds.common.models.serialize.numerical_types import U32Type
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.templates.event_template import EventTemplate
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.utils.event_severity import EventSeverity


def serialize_event(event_id, args):
    """Serialize an event as id + time + args, the layout EventDecoder expects"""
    id_obj = ConfigManager().get_type("FwEventIdType")()
    id_obj.val = event_id
    time_obj = TimeType(TimeType.TimeBase("TB_WORKSTATION_TIME"), 0, 1533758629, 123456)
    return id_obj.serialize() + time_obj.serialize() + b"".join(arg.serialize() for arg in args)


def test_event_decoder_multiple_events():
    """
    Tests that two events serialized back to back in one buffer both decode
    """
    count_temp = EventTemplate(
        1,
        "CountEvent",
        "test_comp",
        [("count", None, U32Type)],
        EventSeverity.ACTIVITY_HI,
        "count={}",
    )
    flag_temp = EventTemplate(
        2,
        "FlagEvent",
        "test_comp",
        [("flag", None, BoolType)],
        EventSeverity.ACTIVITY_HI,
        "abc {} 123",
    )
    decoder = EventDecoder({1: count_temp, 2: flag_temp})

    data = serialize_event(1, [U32Type(42)]) + serialize_event(2, [BoolType(True)])
    events = decoder.decode_api(data)

    assert len(events) == 2
    assert events[0].get_id() == 1
    assert events[0].get_display_text() == "count=42"
    assert events[1].get_id() == 2
    assert events[1].get_display_text() == "abc True 123"


def test_event_decoder_bool_not_truncated():
    """Regression test for nasa/fprime#4860.

    A bool argument must not truncate the event's format string: the literal
    text that follows the bool in "abc {} 123" must be preserved.
    """
    flag_temp = EventTemplate(
        1,
        "BoolEvent",
        "test_comp",
        [("flag", None, BoolType)],
        EventSeverity.ACTIVITY_HI,
        "abc {} 123",
    )
    decoder = EventDecoder({1: flag_temp})

    (true_event,) = decoder.decode_api(serialize_event(1, [BoolType(True)]))
    assert true_event.get_display_text() == "abc True 123"

    (false_event,) = decoder.decode_api(serialize_event(1, [BoolType(False)]))
    assert false_event.get_display_text() == "abc False 123"


def test_event_decoder_bool_followed_by_arg_not_truncated():
    """nasa/fprime#4860: a value after the bool must survive too."""
    temp = EventTemplate(
        2,
        "BoolThenNum",
        "test_comp",
        [("flag", None, BoolType), ("n", None, U32Type)],
        EventSeverity.ACTIVITY_HI,
        "flag={} n={}",
    )
    decoder = EventDecoder({2: temp})

    (event,) = decoder.decode_api(serialize_event(2, [BoolType(True), U32Type(42)]))
    assert event.get_display_text() == "flag=True n=42"


def test_event_decoder_single_event_preserved():
    """Preservation test for the decode_api pointer change.

    A buffer holding exactly one event must decode to exactly one EventData
    with the correct id, time and argument. This must hold both before and
    after switching decode_api to advance by the returned offset, proving the
    normal one-event-per-buffer path is unaffected by the fix.
    """
    temp = EventTemplate(
        3,
        "CountEvent",
        "test_comp",
        [("count", None, U32Type)],
        EventSeverity.ACTIVITY_HI,
        "count={}",
    )
    decoder = EventDecoder({3: temp})

    events = decoder.decode_api(serialize_event(3, [U32Type(7)]))

    # Exactly one event back: the pointer consumed the whole buffer and the
    # loop did not re-enter on leftover bytes (under-advance) or warn about
    # missing data (over-advance).
    assert len(events) == 1
    assert events[0].get_id() == 3
    assert events[0].time.seconds == 1533758629
    assert events[0].time.useconds == 123456
    assert events[0].get_display_text() == "count=7"

    # Same guarantee when the single argument is a bool: the offset returned by
    # decode_args must land exactly past the 1-byte bool, which is the spot the
    # decode_api pointer change touches.
    bool_temp = EventTemplate(
        4,
        "FlagEvent",
        "test_comp",
        [("flag", None, BoolType)],
        EventSeverity.ACTIVITY_HI,
        "abc {} 123",
    )
    bool_decoder = EventDecoder({4: bool_temp})
    bool_events = bool_decoder.decode_api(serialize_event(4, [BoolType(True)]))

    assert len(bool_events) == 1
    assert bool_events[0].get_id() == 4
    assert bool_events[0].get_display_text() == "abc True 123"
