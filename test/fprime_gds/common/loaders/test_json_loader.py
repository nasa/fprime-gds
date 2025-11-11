from fprime_gds.common.loaders.json_loader import JsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.event_json_loader import EventJsonLoader
from fprime_gds.common.loaders.pkt_json_loader import PktJsonLoader
from fprime_gds.common.loaders.type_json_loader import TypeJsonLoader
from fprime_gds.common.models.serialize.array_type import ArrayType
from fprime_gds.common.models.serialize.enum_type import EnumType
import fprime_gds.common.models.serialize.numerical_types as numerical_types
from fprime_gds.common.models.serialize.serializable_type import SerializableType
from fprime_gds.common.models.serialize.string_type import StringType

from pathlib import Path
import pytest
import json
from typing import List
from fprime_gds.common.templates.cmd_template import CmdTemplate
from fprime_gds.common.templates.ch_template import ChTemplate
from fprime_gds.common.templates.event_template import EventTemplate
from fprime_gds.common.templates.pkt_template import PktTemplate


REF_JSON_DICTIONARY = str(
    Path(__file__).resolve().parent / "resources" / "RefTopologyDictionary.json"
)


@pytest.fixture
def loader():
    return JsonLoader(REF_JSON_DICTIONARY)


@pytest.fixture
def cmd_loader():
    return CmdJsonLoader(REF_JSON_DICTIONARY)


@pytest.fixture
def event_loader():
    return EventJsonLoader(REF_JSON_DICTIONARY)


@pytest.fixture
def ch_loader():
    return ChJsonLoader(REF_JSON_DICTIONARY)


@pytest.fixture
def pkt_loader():
    return PktJsonLoader(REF_JSON_DICTIONARY)


@pytest.fixture
def fw_type_loader():
    return TypeJsonLoader(REF_JSON_DICTIONARY)


@pytest.fixture
def json_dict_obj():
    with open(REF_JSON_DICTIONARY, "r") as f:
        return json.load(f)


def test_construct_enum_type(loader):
    ref_signal_type = loader.parse_type(
        {"name": "Ref.SignalType", "kind": "qualifiedIdentifier"}
    )
    assert issubclass(ref_signal_type, EnumType)
    assert ref_signal_type.__name__ == "Ref.SignalType"
    assert ref_signal_type.ENUM_DICT == {
        "TRIANGLE": 0,
        "SQUARE": 1,
        "SINE": 2,
        "NOISE": 3,
    }
    assert ref_signal_type.REP_TYPE == "I32"


def test_construct_alias_type(loader):
    ref_alias_frequency_type = loader.parse_type(
        {"name": "Ref.SignalGen.FrequencyType", "kind": "qualifiedIdentifier"}
    )
    assert ref_alias_frequency_type == numerical_types.U32Type
    ref_alias_phase_type = loader.parse_type(
        {"name": "Ref.SignalGen.PhaseType", "kind": "qualifiedIdentifier"}
    )
    assert ref_alias_phase_type == numerical_types.F32Type
    ref_alias_buff_recv_type = loader.parse_type(
        {"name": "Ref.BuffRecvType", "kind": "qualifiedIdentifier"}
    )
    assert ref_alias_buff_recv_type == numerical_types.U32Type
    ref_alias_u32_type = loader.parse_type(
        {"name": "Ref.AliasU32", "kind": "qualifiedIdentifier"}
    )
    assert ref_alias_u32_type == numerical_types.U32Type


def test_construct_array_type(loader):
    ref_many_choices = loader.parse_type(
        {"name": "Ref.ManyChoices", "kind": "qualifiedIdentifier"}
    )
    assert issubclass(ref_many_choices, ArrayType)
    assert ref_many_choices.__name__ == "Ref.ManyChoices"
    assert ref_many_choices.FORMAT == "{}"
    assert ref_many_choices.LENGTH == 2
    assert ref_many_choices.MEMBER_TYPE.ENUM_DICT == {
        "ONE": 0,
        "TWO": 1,
        "RED": 2,
        "BLUE": 3,
    }
    assert ref_many_choices.MEMBER_TYPE.REP_TYPE == "I32"


def test_construct_serializable_type(loader):
    ref_choice_pair = loader.parse_type(
        {"name": "Ref.ChoicePair", "kind": "qualifiedIdentifier"}
    )
    assert issubclass(ref_choice_pair, SerializableType)
    assert ref_choice_pair.__name__ == "Ref.ChoicePair"
    assert ref_choice_pair.MEMBER_LIST[0][0] == "firstChoice"
    assert ref_choice_pair.MEMBER_LIST[0][1].ENUM_DICT == {
        "ONE": 0,
        "TWO": 1,
        "RED": 2,
        "BLUE": 3,
    }
    assert ref_choice_pair.MEMBER_LIST[0][1].REP_TYPE == "I32"
    assert ref_choice_pair.MEMBER_LIST[0][2] == "{}"
    assert ref_choice_pair.MEMBER_LIST[1][0] == "secondChoice"
    assert ref_choice_pair.MEMBER_LIST[1][1].ENUM_DICT == {
        "ONE": 0,
        "TWO": 1,
        "RED": 2,
        "BLUE": 3,
    }
    assert ref_choice_pair.MEMBER_LIST[1][1].REP_TYPE == "I32"
    assert ref_choice_pair.MEMBER_LIST[1][2] == "{}"


def test_struct_with_unordered_members(loader):
    misordered_member = loader.parse_type(
        {"name": "Ref.TestMisorderedStructIndexes", "kind": "qualifiedIdentifier"}
    )
    assert issubclass(misordered_member, SerializableType)
    assert misordered_member.MEMBER_LIST[0][0] == "ThisIsZero"
    assert misordered_member.MEMBER_LIST[1][0] == "ThisIsOne"
    assert misordered_member.MEMBER_LIST[2][0] == "ThisIsTwo"


def test_construct_primitive_types(loader):
    i32_type = loader.parse_type(
        {"name": "I32", "kind": "integer", "size": 32, "signed": True}
    )
    assert i32_type == numerical_types.I32Type
    f64_type = loader.parse_type(
        {
            "name": "F64",
            "kind": "float",
            "size": 64,
        }
    )
    assert f64_type == numerical_types.F64Type


def test_construct_cmd_dict(cmd_loader, json_dict_obj):
    id_dict, name_dict, versions = cmd_loader.construct_dicts(None)
    assert len(id_dict) == len(name_dict) == len(json_dict_obj["commands"])
    assert versions == ("TestVersion", "TestVersion")

    cmd_no_op_string: CmdTemplate = name_dict["Ref.cmdDisp.CMD_NO_OP_STRING"]
    assert cmd_no_op_string.get_op_code() == 1281
    assert cmd_no_op_string.get_description() == "No-op string command"
    assert issubclass(cmd_no_op_string.get_args()[0][2], StringType)


def test_construct_event_dict(event_loader, json_dict_obj):
    id_dict, name_dict, versions = event_loader.construct_dicts(None)
    assert len(id_dict) == len(name_dict) == len(json_dict_obj["events"])
    assert versions == ("TestVersion", "TestVersion")

    event_choice: EventTemplate = name_dict["Ref.typeDemo.ChoiceEv"]
    assert event_choice.get_id() == 4352
    assert event_choice.get_description() == "Single choice event"
    assert event_choice.get_args()[0][0] == "choice"
    assert issubclass(event_choice.get_args()[0][2], EnumType)
    assert event_choice.get_format_str() == "Choice: {}"


def test_construct_ch_dict(ch_loader, json_dict_obj):
    id_dict, name_dict, versions = ch_loader.construct_dicts(None)
    assert len(id_dict) == len(name_dict) == len(json_dict_obj["telemetryChannels"])
    assert versions == ("TestVersion", "TestVersion")

    ch_choice: ChTemplate = name_dict["Ref.typeDemo.ChoicesCh"]
    assert ch_choice.get_id() == 4353
    assert ch_choice.get_ch_desc() == "Multiple choice channel via Array"
    assert ch_choice.ch_type_obj.__name__ == "Ref.ManyChoices"
    assert ch_choice.ch_type_obj.LENGTH == 2


def test_construct_pkt_dict(ch_loader, pkt_loader):
    _, ch_name_dict, _ = ch_loader.construct_dicts(None)
    _, pkt_name_dict, _ = pkt_loader.construct_dicts("PacketSet1", ch_name_dict)
    sig_gen_pkt: PktTemplate = pkt_name_dict["SigGen1"]
    sig_gen_pkt_ch_list: List[ChTemplate] = sig_gen_pkt.get_ch_list()

    assert sig_gen_pkt.get_id() == 15
    assert len(sig_gen_pkt_ch_list) == 5
    assert sig_gen_pkt_ch_list[0].get_full_name() == "Ref.SG1.PairOutput"
    assert sig_gen_pkt_ch_list[1].get_full_name() == "Ref.SG1.History"
    assert sig_gen_pkt_ch_list[2].get_full_name() == "Ref.SG1.PairHistory"
    assert sig_gen_pkt_ch_list[3].get_full_name() == "Ref.SG1.DpBytes"
    assert sig_gen_pkt_ch_list[4].get_full_name() == "Ref.SG1.DpRecords"

    _, pkt_name_dict, _ = pkt_loader.construct_dicts("PacketSet2", ch_name_dict)
    type_demo_pkt: PktTemplate = pkt_name_dict["TypeDemo"]
    type_demo_pkt_ch_list: List[ChTemplate] = type_demo_pkt.get_ch_list()

    assert type_demo_pkt.get_id() == 21
    assert len(type_demo_pkt_ch_list) == 20
    assert type_demo_pkt_ch_list[0].get_full_name() == "Ref.typeDemo.ChoiceCh"
    assert type_demo_pkt_ch_list[1].get_full_name() == "Ref.typeDemo.ChoicesCh"
    assert type_demo_pkt_ch_list[-1].get_full_name() == "Ref.typeDemo.ScalarF64Ch"


def test_construct_fw_types(fw_type_loader):
    _, name_dict, _ = fw_type_loader.construct_dicts(None)
    # Test values as per specified in ./resources/RefTopologyDictionary.json (non-default values)
    assert name_dict["FwPacketDescriptorType"] == numerical_types.U8Type
    assert name_dict["FwChanIdType"] == numerical_types.U32Type
    assert name_dict["FwEventIdType"] == numerical_types.U32Type
    assert name_dict["FwOpcodeType"] == numerical_types.U32Type
    assert name_dict["FwTlmPacketizeIdType"] == numerical_types.U16Type
