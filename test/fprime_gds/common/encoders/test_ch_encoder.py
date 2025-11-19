"""
Tests the channel encoder

Created on Jul 10, 2020
@author: Joseph Paetz, hpaulson
"""

from fprime_gds.common.models.serialize.numerical_types import U16Type, U32Type
from fprime_gds.common.models.serialize.time_type import TimeType
from fprime_gds.common.data_types.ch_data import ChData
from fprime_gds.common.encoders.ch_encoder import ChEncoder
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.utils.config_manager import ConfigManager


def test_ch_encoder_1():
    """
    Tests the encoding of the channel encoder
    """

    temp = ChTemplate(101, "test_ch", "test_comp", U32Type)
    time_obj = TimeType(TimeType.TimeBase("TB_WORKSTATION_TIME"), 0, 1533758629, 123456)
    ch_obj = ChData(U32Type(42), time_obj, temp)

    desc_bin = b"\x00\x01"  # U16 ComCfg.Apid for FW_PACKET_TELEM
    id_bin = b"\x00\x00\x00\x65"
    time_bin = b"\x00\x02\x00\x5b\x6b\x4c\xa5\x00\x01\xe2\x40"
    val_bin = b"\x00\x00\x00\x2a"
    u32_len_bin = b"\x00\x00\x00\x15"  # 21 bytes (2+4+11+4)
    u16_len_bin = b"\x00\x15"  # 21 bytes

    u32_expected = u32_len_bin + desc_bin + id_bin + time_bin + val_bin
    u16_expected = u16_len_bin + desc_bin + id_bin + time_bin + val_bin

    #### Use msg_len U32Type ####
    ConfigManager().set_config("msg_len", U32Type)
    enc = ChEncoder()
    u32_output = enc.encode_api(ch_obj)
    assert (
        u32_output == u32_expected
    ), f"FAIL: expected regular output to be {list(u32_expected)}, but found {list(u32_output)}"

    #### Use msg_len U16Type ####
    ConfigManager().set_config("msg_len", U16Type)
    enc_u16 = ChEncoder()
    u16_output = enc_u16.encode_api(ch_obj)
    assert (
        u16_output == u16_expected
    ), f"FAIL: expected configured output to be {list(u16_expected)}, but found {list(u16_output)}"

    ConfigManager()._set_defaults()  # reset defaults not to interfere with other tests


def test_ch_encoder_2():
    temp = ChTemplate(102, "test_ch2", "test_comp2", U16Type)
    time_obj = TimeType(TimeType.TimeBase("TB_WORKSTATION_TIME"), 0, 1533758628, 123457)
    ch_obj = ChData(U16Type(40), time_obj, temp)

    desc_bin = b"\x00\x01"  # U16 ComCfg.Apid for FW_PACKET_TELEM
    id_bin = b"\x00\x00\x00\x66"
    time_bin = b"\x00\x02\x00\x5b\x6b\x4c\xa4\x00\x01\xe2\x41"
    val_bin = b"\x00\x28"
    u32_len_bin = b"\x00\x00\x00\x13"  # 19 bytes (2+4+11+2)
    u16_len_bin = b"\x00\x13"  # 19 bytes

    u32_expected = u32_len_bin + desc_bin + id_bin + time_bin + val_bin
    u16_expected = u16_len_bin + desc_bin + id_bin + time_bin + val_bin

    #### Use msg_len U32Type ####
    ConfigManager().set_config("msg_len", U32Type)
    enc = ChEncoder()
    u32_output = enc.encode_api(ch_obj)
    assert (
        u32_output == u32_expected
    ), f"FAIL: expected regular output to be {list(u32_expected)}, but found {list(u32_output)}"

    #### Use msg_len U16Type ####
    ConfigManager().set_config("msg_len", U16Type)
    enc_u16 = ChEncoder()
    u16_output = enc_u16.encode_api(ch_obj)
    assert (
        u16_output == u16_expected
    ), f"FAIL: expected configured output to be {list(u16_expected)}, but found {list(u16_output)}"

    ConfigManager()._set_defaults()  # reset defaults not to interfere with other tests
