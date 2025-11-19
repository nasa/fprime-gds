"""
Tests the event encoder

Created on Jul 10, 2020
@author: Joseph Paetz, hpaulson
"""

from fprime_gds.common.models.serialize.numerical_types import U8Type, U16Type, U32Type
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.data_types.event_data import EventData
from fprime_gds.common.encoders.event_encoder import EventEncoder
from fprime_gds.common.templates.event_template import EventTemplate
from fprime_gds.common.utils.config_manager import ConfigManager
from fprime_gds.common.utils.event_severity import EventSeverity


def test_event_encoder_1():
    """
    Tests the encoding of the event encoder
    """
    temp = EventTemplate(
        101,
        "test_ch",
        "test_comp",
        [("a1", "a1", U32Type), ("a2", "a2", U32Type)],
        EventSeverity["DIAGNOSTIC"],
        "%d %d",
    )

    time_obj = TimeType(TimeType.TimeBase("TB_WORKSTATION_TIME"), 0, 1533758629, 123456)
    event_obj = EventData((U32Type(42), U32Type(10)), time_obj, temp)

    desc_bin = b"\x00\x02"  # U16 ComCfg.Apid for FW_PACKET_LOG
    id_bin = b"\x00\x00\x00\x65"
    time_bin = b"\x00\x02\x00\x5b\x6b\x4c\xa5\x00\x01\xe2\x40"
    arg_bin = b"\x00\x00\x00\x2a\x00\x00\x00\x0a"
    u32_len_bin = b"\x00\x00\x00\x19"  # 25 bytes (2+4+11+8)
    u16_len_bin = b"\x00\x19"  # 25 bytes

    u32_expected = u32_len_bin + desc_bin + id_bin + time_bin + arg_bin
    u16_expected = u16_len_bin + desc_bin + id_bin + time_bin + arg_bin

    #### Use msg_len U32Type ####
    ConfigManager().set_config("msg_len", U32Type)
    enc = EventEncoder()
    u32_output = enc.encode_api(event_obj)
    assert (
        u32_output == u32_expected
    ), f"FAIL: expected regular output to be {list(u32_expected)}, but found {list(u32_output)}"

    #### Use msg_len U16Type ####
    ConfigManager().set_config("msg_len", U16Type)
    enc_u16 = EventEncoder()
    u16_output = enc_u16.encode_api(event_obj)
    assert (
        u16_output == u16_expected
    ), f"FAIL: expected configured output to be {list(u16_expected)}, but found {list(u16_output)}"

    ConfigManager()._set_defaults()  # reset defaults not to interfere with other tests


def test_event_encoder_2():
    temp = EventTemplate(
        102,
        "test_ch2",
        "test_comp2",
        [("a1", "a1", U8Type), ("a2", "a2", U16Type)],
        EventSeverity["DIAGNOSTIC"],
        "%d %d",
    )

    time_obj = TimeType(TimeType.TimeBase("TB_WORKSTATION_TIME"), 0, 1533758628, 123457)
    event_obj = EventData((U8Type(128), U16Type(40)), time_obj, temp)

    desc_bin = b"\x00\x02"  # U16 ComCfg.Apid for FW_PACKET_LOG
    id_bin = b"\x00\x00\x00\x66"
    time_bin = b"\x00\x02\x00\x5b\x6b\x4c\xa4\x00\x01\xe2\x41"
    arg_bin = b"\x80\x00\x28"
    u32_len_bin = b"\x00\x00\x00\x14"  # 20 bytes (2+4+11+3)
    u16_len_bin = b"\x00\x14"  # 20 bytes

    u32_expected = u32_len_bin + desc_bin + id_bin + time_bin + arg_bin
    u16_expected = u16_len_bin + desc_bin + id_bin + time_bin + arg_bin

    #### Use msg_len U32Type ####
    ConfigManager().set_config("msg_len", U32Type)
    enc = EventEncoder()
    u32_output = enc.encode_api(event_obj)
    assert (
        u32_output == u32_expected
    ), f"FAIL: expected regular output to be {list(u32_expected)}, but found {list(u32_output)}"

    #### Use msg_len U16Type ####
    ConfigManager().set_config("msg_len", U16Type)
    enc_u16 = EventEncoder()
    u16_output = enc_u16.encode_api(event_obj)
    assert (
        u16_output == u16_expected
    ), f"FAIL: expected configured output to be {list(u16_expected)}, but found {list(u16_output)}"

    ConfigManager()._set_defaults()  # reset defaults not to interfere with other tests
