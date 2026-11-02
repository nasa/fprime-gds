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
