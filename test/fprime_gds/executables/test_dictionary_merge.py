""" Tests for fprime_gds.executables.dictionary_merge

All inputs are built in-code from spec-complete entries. `deployment()` gives a hub-reference-shaped dictionary: a
shared subtopology (CdhCore, identical in every deployment) plus a deployment-local component that reuses the same
local ids. A and B at the same base id reproduce the hub reference as shipped; B2 is B with shifted ids, the case the
per-deployment namespacing is for.
"""

import contextlib
import copy
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fprime_gds.common.loaders.ch_json_loader import ChJsonLoader
from fprime_gds.common.loaders.cmd_json_loader import CmdJsonLoader
from fprime_gds.common.loaders.event_json_loader import EventJsonLoader
from fprime_gds.common.loaders.pkt_json_loader import PktJsonLoader
from fprime_gds.common.utils.cleanup import globals_cleanup
from fprime_gds.executables import dictionary_merge
from fprime_gds.executables.dictionary_merge import (
    ARRAY_SECTIONS,
    SECTION_ORDER,
    LoadedInput,
    MergeOptions,
    merge_dictionaries,
    merge_two,
)

# Message fingerprints
E_NAME_CLASH = "with different opcodes; use --prefer-primary", "with different ids; use --prefer-primary"
E_BODY = "has different definitions in"
E_ID_CLASH = "is used by"
E_TYPE = "has inconsistent definitions in"
E_META = "Inconsistent metadata values"
E_UNKNOWN_CHANNEL = "references unknown channel"
E_MALFORMED = "Malformed dictionary"
E_RENAME_TARGET = "cannot rename"
E_PREFIX = "cannot derive a namespace prefix"
E_SAME_PREFIX = "both have the namespace prefix"
W_DROPPED = "dropped in favour of"
W_RENAMED = "; renamed to '"
W_KEPT_BODY = "kept definition '"
W_KEPT_TYPE = "kept definition from"
W_LIBS = "libraryVersions differ"
W_PACKET_REMOVED = "removed because it references dropped channel"
W_PACKET_SETS = "needs --packet-set-name"


def u(name="U32", size=32):
    return {"name": name, "kind": "integer", "size": size, "signed": False}


def command(name, opcode, **extra):
    return {"name": name, "commandKind": "async", "opcode": opcode, "formalParams": [], "queueFullBehavior": "assert",
            "annotation": "", **extra}


def event(name, id, **extra):
    return {"name": name, "severity": "ACTIVITY_LO", "formalParams": [], "id": id, "format": "x", "annotation": "",
            **extra}


def channel(name, id, **extra):
    return {"name": name, "type": u(), "id": id, "telemetryUpdate": "always", "annotation": "", **extra}


def typed(name, id):
    """ A parameter or record: a named, typed, id-bearing entry """
    return {"name": name, "type": u(), "id": id, "annotation": ""}


def enum_type(name, *enumerators):
    return {"kind": "enum", "qualifiedName": name, "representationType": u("U16", 16),
            "enumeratedConstants": [{"name": n, "value": v, "annotation": ""} for v, n in enumerate(enumerators)]}


def constant(name, value):
    return {"kind": "constant", "qualifiedName": name, "type": u(), "value": value, "annotation": ""}


def packet_set(name, *packets, omitted=()):
    return {"name": name, "omitted": list(omitted),
            "members": [{"name": p, "id": i, "group": 1, "members": list(m)} for i, (p, m) in enumerate(packets, 1)]}


def make_dictionary(name="Ref.Ref", *, types=(), constants=(), commands=(), parameters=(), events=(), channels=(),
                    records=(), containers=(), packet_sets=(), **metadata):
    meta = {"deploymentName": name, "projectVersion": "p1", "frameworkVersion": "f1", "libraryVersions": [],
            "dictionarySpecVersion": "1.0.0", **metadata}
    return {"metadata": {k: v for k, v in meta.items() if v is not None}, "typeDefinitions": list(types),
            "constants": list(constants), "commands": list(commands), "parameters": list(parameters),
            "events": list(events), "telemetryChannels": list(channels), "records": list(records),
            "containers": list(containers), "telemetryPacketSets": list(packet_sets)}


NO_OP = "CdhCore.cmdDisp.CMD_NO_OP"
DISPATCHED = "CdhCore.cmdDisp.CommandsDispatched"


def deployment(letter, base=0):
    """ 'Ref.Deployment<letter>': shared CdhCore entries at base + 0x5xx, a local component at base + 0x1xxx """
    local = f"Ref.Deployment{letter}.{letter.lower()}_comp"
    return make_dictionary(f"Ref.Deployment{letter}",
                           types=[enum_type("TimeBase", "TB_NONE", "TB_PROC_TIME")], constants=[constant("Ref.K", 1)],
                           commands=[command(NO_OP, base + 0x500), command(f"{local}.GO", base + 0x1000)],
                           parameters=[typed(f"{local}.PRM", base + 0x1003)],
                           events=[event("CdhCore.events.CMD_OK", base + 0x501), event(f"{local}.WENT", base + 0x1001)],
                           channels=[channel(DISPATCHED, base + 0x502), channel(f"{local}.Count", base + 0x1002)],
                           records=[typed(f"{local}.Rec", base + 0x1004)],
                           containers=[{"name": f"{local}.Con", "id": base + 0x1005, "defaultPriority": 1}])


A = deployment("A")
B = deployment("B")
B2 = deployment("B", 0x20000000)


def names(merged, section="commands"):
    return [e["name"] for e in merged[section]]


def count(lines, *fingerprints):
    return sum(1 for line in lines if any(f in line for f in fingerprints))


def merge(*dictionaries, prefixes=None, **options):
    """ In-memory merge; returns (merged or None, report) """
    prefixes = prefixes or [None] * len(dictionaries)
    inputs = [LoadedInput(f"d{i}", copy.deepcopy(d), prefix=p)
              for i, (d, p) in enumerate(zip(dictionaries, prefixes), start=1)]
    return merge_two(*inputs, MergeOptions(**options))


def merge_ok(*dictionaries, **options):
    merged, report = merge(*dictionaries, **options)
    assert merged is not None, "\n".join(report.errors)
    return merged, report


def merge_fails(*dictionaries, **options):
    merged, report = merge(*dictionaries, **options)
    assert merged is None, "expected the merge to fail"
    return report.errors


class TestCollisionRules(unittest.TestCase):
    """ One test per rule of Merger.merge_entries """

    def test_identical_entries_merge_into_one(self):
        # A + B as shipped: the shared subtopology is identical (also types/constants), the local components clash by id
        errors = merge_fails(A, B)
        self.assertEqual((len(errors), count(errors, E_ID_CLASH)), (6, 6))
        merged, report = merge_ok(A, B, prefer_primary=True)
        self.assertEqual(count(report.warnings, W_DROPPED), 6)
        for section in ARRAY_SECTIONS:
            self.assertEqual(merged[section], A[section], section)

    def test_same_name_different_id_renames_both(self):
        merged, report = merge_ok(A, B2)
        self.assertEqual(count(report.warnings, W_RENAMED), 3)
        self.assertEqual(names(merged), [f"DeploymentA.{NO_OP}", "Ref.DeploymentA.a_comp.GO", f"DeploymentB.{NO_OP}",
                                         "Ref.DeploymentB.b_comp.GO"])
        self.assertEqual([c["opcode"] for c in merged["commands"]], [0x500, 0x1000, 0x20000500, 0x20001000])
        self.assertEqual(merged["typeDefinitions"], A["typeDefinitions"])
        for section in ("parameters", "records", "containers"):
            self.assertEqual(merged[section], A[section] + B2[section], section)
        # the body does not matter (ids are authoritative), nor does --prefer-primary
        other = make_dictionary("Ref.Two", channels=[channel("Sub.X", 2, format="{} ms")])
        merged, _ = merge_ok(make_dictionary("Ref.One", channels=[channel("Sub.X", 1)]), other, prefer_primary=True)
        self.assertEqual(names(merged, "telemetryChannels"), ["One.Sub.X", "Two.Sub.X"])

    def test_no_namespace(self):
        errors = merge_fails(A, B2, no_namespace=True)
        self.assertEqual((len(errors), count(errors, *E_NAME_CLASH)), (3, 3))
        merged, report = merge_ok(A, B2, no_namespace=True, prefer_primary=True)
        self.assertEqual(count(report.warnings, W_DROPPED), 3)
        self.assertEqual(names(merged), [NO_OP, "Ref.DeploymentA.a_comp.GO", "Ref.DeploymentB.b_comp.GO"])

    def test_same_id_different_name(self):
        d1 = make_dictionary("Ref.One", channels=[channel("Ref.a.X", 0)])
        d2 = make_dictionary("Ref.Two", channels=[channel("Ref.b.Y", 0), channel("Ref.b.Z", 1)],
                             packet_sets=[packet_set("Pkts", ("P", ["Ref.b.Y", "Ref.b.Z"]), ("Q", ["Ref.b.Z"]),
                                                     omitted=["Ref.b.Y", "Ref.b.Z"])])
        self.assertEqual(count(merge_fails(d1, d2), E_ID_CLASH), 1)
        merged, report = merge_ok(d1, d2, prefer_primary=True)
        self.assertEqual(names(merged, "telemetryChannels"), ["Ref.a.X", "Ref.b.Z"])
        # a packet that referenced the dropped channel goes with it; an omitted reference is just filtered
        pkts = merged["telemetryPacketSets"][0]
        self.assertEqual(([p["name"] for p in pkts["members"]], pkts["omitted"]), (["Q"], ["Ref.b.Z"]))
        self.assertEqual((count(report.warnings, W_DROPPED), count(report.warnings, W_PACKET_REMOVED)), (1, 1))

    def test_same_name_same_id_different_body(self):
        d1 = make_dictionary("Ref.One", events=[event("Sub.E", 1)], channels=[channel("Sub.X", 1)])
        d2 = make_dictionary("Ref.Two", events=[event("Sub.E", 1, format="other")],
                             channels=[channel("Sub.X", 1, format="{} ms")],
                             packet_sets=[packet_set("Pkts", ("P", ["Sub.X"]), omitted=["Sub.X"])])
        self.assertEqual(count(merge_fails(d1, d2), E_BODY), 2)
        merged, report = merge_ok(d1, d2, prefer_primary=True)
        self.assertEqual((merged["events"], merged["telemetryChannels"]), (d1["events"], d1["telemetryChannels"]))
        self.assertEqual((count(report.warnings, W_KEPT_BODY), count(report.warnings, W_PACKET_REMOVED)), (2, 0))
        # the item is still there under its name, so the packet referencing it stays (and follows the primary's prefix)
        merged, _ = merge_ok(d1, d2, prefer_primary=True, namespace_all=True)
        pkts = merged["telemetryPacketSets"][0]
        self.assertEqual((pkts["members"][0]["members"], pkts["omitted"]), (["One.Sub.X"], ["One.Sub.X"]))

    def test_type_and_constant_conflicts(self):
        d1 = make_dictionary("Ref.One", types=[enum_type("TimeBase", "TB_NONE")], constants=[constant("Ref.K", 1)])
        d2 = make_dictionary("Ref.Two", types=[enum_type("TimeBase", "TB_NONE", "TB_X")],
                             constants=[constant("Ref.K", 2)])
        self.assertEqual(count(merge_fails(d1, d2), E_TYPE), 2)
        merged, report = merge_ok(d1, d2, prefer_primary=True)
        self.assertEqual((merged["typeDefinitions"], merged["constants"]), (d1["typeDefinitions"], d1["constants"]))
        self.assertEqual(count(report.warnings, W_KEPT_TYPE), 2)

    def test_prefix_is_last_segment_and_must_differ(self):
        d1 = make_dictionary("X.Same", commands=[command("Sub.X", 1)])
        d2 = make_dictionary("Y.Same", commands=[command("Sub.X", 2)])
        self.assertEqual(count(merge_fails(d1, d2), E_SAME_PREFIX), 1)
        merged, _ = merge_ok(d1, d2, prefixes=["Alpha", "Site.Beta"])
        self.assertEqual(names(merged), ["Alpha.Sub.X", "Site.Beta.Sub.X"])
        # an unusable deploymentName is only an error once a prefix is needed; --prefix rescues it
        d2["metadata"]["deploymentName"] = "not an identifier"
        errors = merge_fails(d1, d2)
        self.assertEqual((len(errors), count(errors, E_PREFIX)), (1, 1), errors)
        del d2["metadata"]["deploymentName"]
        self.assertEqual(count(merge_fails(d1, d2), E_PREFIX), 1)
        merge_ok(d1, d2, prefixes=["Alpha", "Beta"])
        d2["commands"] = [command("Sub.Y", 2)]
        merge_ok(d1, d2)

    def test_rename_target_already_taken(self):
        d1 = make_dictionary("Ref.P", commands=[command("Sub.X", 1), command("Q.Sub.X", 3)])
        d2 = make_dictionary("Ref.Q", commands=[command("Sub.X", 2)])
        self.assertEqual(count(merge_fails(d1, d2), E_RENAME_TARGET), 1)

    def test_literal_prefixed_name_is_a_distinct_item(self):
        # d1's 'X' is held as 'Alpha.X'; d2's literal 'Alpha.X' at the same opcode is an id clash, not the same entry
        d1 = make_dictionary("Ref.Alpha", commands=[command("X", 1)])
        d2 = make_dictionary("Ref.Beta", commands=[command("X", 2), command("Alpha.X", 1)])
        self.assertEqual(count(merge_fails(d1, d2), E_ID_CLASH), 1)
        # and a held literal 'Beta.X' is not the same-name definition of d2's 'X' either: dropped, packet removed
        d1 = make_dictionary("Ref.Alpha", channels=[channel("Beta.X", 1)])
        d2 = make_dictionary("Ref.Beta", channels=[channel("X", 1, type=u("U16", 16))],
                             packet_sets=[packet_set("Pkts", ("P", ["X"]))])
        self.assertEqual(count(merge_fails(d1, d2), E_ID_CLASH), 1)
        merged, report = merge_ok(d1, d2, prefer_primary=True)
        self.assertEqual((merged["telemetryChannels"], merged["telemetryPacketSets"][0]["members"]),
                         (d1["telemetryChannels"], []))
        self.assertEqual(count(report.warnings, W_KEPT_BODY), 0)

    def test_chained_merge_is_not_supported(self):
        merged, _ = merge_ok(A, B2)
        # the held literal 'DeploymentB.X' and B2's 'X' share an id: a clash, even though it is the same item
        self.assertEqual(count(merge_fails(merged, B2), E_ID_CLASH), 3)
        again, report = merge_ok(merged, B2, prefer_primary=True)
        self.assertEqual((again["commands"], count(report.warnings, W_DROPPED)), (merged["commands"], 3))

    def test_all_errors_are_collected(self):
        d1 = make_dictionary("Ref.One", commands=[command("Sub.X", 1), command("Ref.a.Y", 2)],
                             types=[enum_type("Ref.T", "A")], projectVersion="p1")
        d2 = make_dictionary("Ref.Two", commands=[command("Sub.X", 3), command("Ref.b.Y", 2)],
                             types=[enum_type("Ref.T", "B")], projectVersion="p2")
        errors = merge_fails(d1, d2, no_namespace=True)
        self.assertEqual([count(errors, *f) for f in (E_NAME_CLASH, (E_ID_CLASH,), (E_TYPE,), (E_META,))], [1] * 4)


class TestPacketsAndNamespaceAll(unittest.TestCase):

    def test_packet_references_follow_renames(self):
        d1 = make_dictionary("Ref.DeploymentA", channels=[channel("Sub.X", 1), channel("Sub.Y", 2)],
                             packet_sets=[packet_set("Pkts", ("P", ["Sub.X", "Sub.Y"]), omitted=["Sub.X"])])
        d2 = make_dictionary("Ref.DeploymentB", channels=[channel("Sub.X", 3)],
                             packet_sets=[packet_set("Pkts", ("Q", ["Sub.X"]))])
        merged, report = merge_ok(d1, d2)
        sets = {s["name"]: s for s in merged["telemetryPacketSets"]}
        self.assertEqual(sets["DeploymentA.Pkts"]["members"][0]["members"], ["DeploymentA.Sub.X", "Sub.Y"])
        self.assertEqual(sets["DeploymentA.Pkts"]["omitted"], ["DeploymentA.Sub.X"])
        self.assertEqual(sets["DeploymentB.Pkts"]["members"][0]["members"], ["DeploymentB.Sub.X"])
        self.assertEqual(count(report.warnings, W_PACKET_SETS), 1)
        d2["telemetryPacketSets"][0]["members"][0]["members"] = ["Sub.Nope"]  # unknown, in a packet
        d1["telemetryPacketSets"][0]["omitted"] = ["Sub.Nope"]  # unknown, in omitted
        self.assertEqual(count(merge_fails(d1, d2), E_UNKNOWN_CHANNEL), 2)
        # packet sets have no id: identical sets merge, same-named different sets are renamed (or an error)
        d1 = make_dictionary("Ref.One", channels=[channel("Sub.X", 1)], packet_sets=[packet_set("Pkts", ("P", []))])
        d2 = {**d1, "metadata": {**d1["metadata"], "deploymentName": "Ref.Two"}}
        self.assertEqual(names(merge_ok(d1, d2)[0], "telemetryPacketSets"), ["Pkts"])
        d2 = make_dictionary("Ref.Two", channels=[channel("Sub.X", 1)], packet_sets=[packet_set("Pkts", ("Q", []))])
        self.assertEqual(names(merge_ok(d1, d2)[0], "telemetryPacketSets"), ["One.Pkts", "Two.Pkts"])
        self.assertEqual(count(merge_fails(d1, d2, no_namespace=True), "different definitions"), 1)

    def test_namespace_all(self):
        d1 = make_dictionary("Ref.DeploymentA", channels=[channel("Sub.X", 1), channel("Ref.a.Y", 2)],
                             commands=[command("Ref.a.CMD", 1)], types=[enum_type("Ref.E", "A")],
                             constants=[constant("Ref.K", 1)],
                             packet_sets=[packet_set("Pkts", ("P", ["Sub.X", "Ref.a.Y"]), omitted=["Ref.a.Y"])])
        d2 = make_dictionary("Ref.DeploymentB", channels=[channel("Sub.X", 1), channel("Ref.b.Z", 4)])
        merged, report = merge_ok(d1, d2, namespace_all=True)
        self.assertEqual(report.warnings, [])
        # every id-bearing entry is prefixed; identical entries merge under the primary's prefix; types, constants
        # and packet-set names are untouched
        self.assertEqual(names(merged, "telemetryChannels"), ["DeploymentA.Sub.X", "DeploymentA.Ref.a.Y",
                                                              "DeploymentB.Ref.b.Z"])
        self.assertEqual(names(merged), ["DeploymentA.Ref.a.CMD"])
        self.assertEqual((merged["typeDefinitions"], merged["constants"]), (d1["typeDefinitions"], d1["constants"]))
        pkts = merged["telemetryPacketSets"][0]
        self.assertEqual((pkts["name"], pkts["members"][0]["members"], pkts["omitted"]),
                         ("Pkts", ["DeploymentA.Sub.X", "DeploymentA.Ref.a.Y"], ["DeploymentA.Ref.a.Y"]))
        merged, _ = merge_ok(d1, d2, namespace_all=True, prefixes=["Alpha", "Beta"])
        self.assertEqual(names(merged, "telemetryChannels"), ["Alpha.Sub.X", "Alpha.Ref.a.Y", "Beta.Ref.b.Z"])
        # a packet set named in both inputs still follows the collision rule: both copies renamed
        d2["telemetryPacketSets"] = [packet_set("Pkts", ("Q", ["Ref.b.Z"]))]
        merged, report = merge_ok(d1, d2, namespace_all=True)
        self.assertEqual(names(merged, "telemetryPacketSets"), ["DeploymentA.Pkts", "DeploymentB.Pkts"])
        self.assertEqual(merged["telemetryPacketSets"][1]["members"][0]["members"], ["DeploymentB.Ref.b.Z"])
        self.assertEqual((count(report.warnings, W_RENAMED), count(report.warnings, W_PACKET_SETS)), (1, 1))
        # prefixes must be distinct even without a collision
        d2["metadata"]["deploymentName"] = "Other.DeploymentA"
        self.assertEqual(count(merge_fails(d1, d2, namespace_all=True), E_SAME_PREFIX), 1)


class TestMetadataAndStructure(unittest.TestCase):

    def test_metadata(self):
        d1 = make_dictionary("Ref.One", libraryVersions=["lib@1"])
        d2 = make_dictionary("Ref.Two", projectVersion="p2", libraryVersions=["lib@2"])
        self.assertEqual(count(merge_fails(d1, d2), E_META), 1)
        merged, report = merge_ok(d1, d2, permissive=True)
        self.assertEqual(report.warnings, [])
        self.assertEqual(merged["metadata"], {**d1["metadata"], "deploymentName": "Ref.One_Ref.Two_merged"})
        d2["metadata"]["projectVersion"] = "p1"
        merged, report = merge_ok(d1, d2, name="Hub.Ground")
        self.assertEqual((count(report.warnings, W_LIBS), merged["metadata"]["deploymentName"]), (1, "Hub.Ground"))
        # unknown top-level keys are preserved, the primary's winning
        merged, _ = merge_ok({**d1, "extra": 1, "one": True}, {**d2, "extra": 2, "two": True})
        self.assertEqual({k: merged[k] for k in ("extra", "one", "two")}, {"extra": 1, "one": True, "two": True})

    def test_malformed_inputs(self):
        good = make_dictionary("Ref.One")
        broken = [({"metadata": "meta"}, "'metadata' must be an object"),
                  ({"commands": {}}, "'commands' must be an array"),
                  ({"commands": [{"name": "X"}]}, "integer 'opcode'"),
                  ({"commands": [command("X", "1")]}, "integer 'opcode'"),
                  ({"typeDefinitions": [{"kind": "enum"}]}, "string 'qualifiedName'")]
        for override, message in broken:
            errors = merge_fails(good, {**make_dictionary("Ref.Two"), **override})
            self.assertEqual(len(errors), 1, errors)
            self.assertIn(message, errors[0])
        for section in SECTION_ORDER:
            d2 = make_dictionary("Ref.Two")
            del d2[section]
            self.assertEqual(count(merge_fails(good, d2), E_MALFORMED), 1, section)
        null_members = {**make_dictionary("Ref.Two"),
                        "telemetryPacketSets": [{"name": "Pkts", "members": None, "omitted": None}]}
        merged, _ = merge_ok(good, null_members)
        self.assertEqual(merged["telemetryPacketSets"], [{"name": "Pkts", "members": [], "omitted": []}])

    def test_malformed_packet_sets_and_root(self):
        good = make_dictionary("Ref.One")
        for override in [{"members": "P"}, {"members": [{"name": "P", "members": [1]}]}, {"omitted": [None]},
                         {"members": 0}, {"omitted": ""}, {"members": [{"name": "P", "members": {}}]}]:
            bad = {**make_dictionary("Ref.Two"), "telemetryPacketSets": [{"name": "Pkts", **override}]}
            errors = merge_fails(good, bad)
            self.assertEqual((len(errors), count(errors, "arrays of channel names")), (1, 1), errors)
        self.assertEqual(count(merge_fails(good, []), E_MALFORMED), 1)

    def test_namespace_all_shared_channel_references_and_name_collisions(self):
        # a packet set of the secondary referencing a channel shared with the primary follows the primary's prefix
        d1 = make_dictionary("Ref.Alpha", channels=[channel("Sub.X", 1)])
        d2 = make_dictionary("Ref.Beta", channels=[channel("Sub.X", 1), channel("Sub.Y", 2)],
                             packet_sets=[packet_set("Pkts", ("P", ["Sub.X", "Sub.Y"]), omitted=["Sub.X"])])
        merged, _ = merge_ok(d1, d2, namespace_all=True)
        pkts = merged["telemetryPacketSets"][0]
        self.assertEqual((pkts["members"][0]["members"], pkts["omitted"]),
                         (["Alpha.Sub.X", "Beta.Sub.Y"], ["Alpha.Sub.X"]))
        # prefixes that make two distinct entries collide on their output name are rejected
        d1 = make_dictionary("Ref.A", commands=[command("B.X", 1)])
        d2 = make_dictionary("Ref.B", commands=[command("X", 2)])
        errors = merge_fails(d1, d2, namespace_all=True, prefixes=["A", "A.B"])
        self.assertEqual((len(errors), count(errors, E_RENAME_TARGET), count(errors, "'A.B.X'")), (1, 1, 1), errors)


class TestCli(unittest.TestCase):

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.a, self.b2 = self.write("A.json", A), self.write("B2.json", B2)

    def write(self, name, dictionary):
        path = self.tmp / name
        path.write_text(json.dumps(dictionary, indent=2))
        return path

    def run_cli(self, *args, output=None):
        """ Run main(); returns (exit code, stderr lines, output path) """
        output = output or self.tmp / "out.json"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as context:
            dictionary_merge.main([str(arg) for arg in args] + ["--output", str(output)])
        return context.exception.code, stderr.getvalue().splitlines(), output

    def test_two_disjoint_inputs_unchanged_from_before(self):
        # what the two-input tool produced before this rewrite: d1's keys over d2's, sections concatenated
        ground = make_dictionary("Ground", channels=[channel("Ground.Derived", 0x9000)], projectVersion="g",
                                 frameworkVersion="g", libraryVersions=None)
        expected = {**ground, **A, "metadata": {**A["metadata"], "deploymentName": "Ref.DeploymentA_Ground_merged"}}
        for section in ARRAY_SECTIONS:
            expected[section] = A[section] + ground[section]
        code, lines, output = self.run_cli("--permissive", self.a, self.write("G.json", ground))
        self.assertEqual((code, lines), (0, []))
        self.assertEqual(output.read_bytes(), json.dumps(expected, indent=2).encode())
        self.assertEqual(merge_dictionaries(A, ground, permissive=True), expected)
        with self.assertRaisesRegex(ValueError, E_ID_CLASH):
            merge_dictionaries(A, B)
        with self.assertRaisesRegex(ValueError, "not a valid dotted identifier"):
            merge_dictionaries(A, ground, name="bad name", permissive=True)

    def test_output_loads_in_gds(self):
        b2 = {**B2, "telemetryPacketSets": [packet_set("Pkts", ("P", [DISPATCHED]))]}
        code, lines, output = self.run_cli(self.a, self.write("B2p.json", b2), "--prefix", "Alpha", "--prefix", "Beta")
        self.assertEqual((code, count(lines, W_RENAMED)), (0, 3))
        globals_cleanup()
        self.addCleanup(globals_cleanup)
        _, cmd_names, _ = CmdJsonLoader(str(output)).construct_dicts(str(output))
        evr_ids, _, _ = EventJsonLoader(str(output)).construct_dicts(str(output))
        _, ch_names, _ = ChJsonLoader(str(output)).construct_dicts(str(output))
        _, pkt_names, _ = PktJsonLoader(str(output)).construct_dicts("Pkts", ch_names)
        self.assertEqual({n: c.get_op_code() for n, c in cmd_names.items() if n.endswith(NO_OP)},
                         {f"Alpha.{NO_OP}": 0x500, f"Beta.{NO_OP}": 0x20000500})
        self.assertEqual(cmd_names[f"Beta.{NO_OP}"].get_comp_name(), "Beta.CdhCore.cmdDisp")
        self.assertEqual({evr_ids[i].get_full_name() for i in (0x501, 0x20000501)},
                         {"Alpha.CdhCore.events.CMD_OK", "Beta.CdhCore.events.CMD_OK"})
        self.assertEqual([ch.get_full_name() for ch in pkt_names["P"].get_ch_list()], [f"Beta.{DISPATCHED}"])

    def test_exit_codes(self):
        code, lines, output = self.run_cli(self.a, self.write("B.json", B))
        self.assertEqual((code, count(lines, E_ID_CLASH), output.exists()), (1, 6, False))
        self.assertIn("Merge failed with 6 error(s); no output written", lines[-1])
        (self.tmp / "bad.json").write_text("{not json")
        (self.tmp / "deep.json").write_text("[" * 100000 + "]" * 100000)
        for argv, message in [([self.a, self.tmp / "bad.json"], "Expecting property name"),
                              ([self.a, self.tmp / "missing.json"], "No such file"),
                              ([self.a, self.tmp / "deep.json"], "recursion"),
                              ([self.a, self.b2, "--namespace-all"], "No such file")]:
            code, lines, _ = self.run_cli(*argv, output=self.tmp / "nope" / "out.json")
            self.assertEqual((code, len(lines), count(lines, "[ERROR] "), count(lines, message)), (1, 1, 1, 1), lines)
        code, lines, _ = self.run_cli("--name", "1bad", self.a, self.b2)
        self.assertEqual((code, count(lines, "not a valid dotted identifier")), (1, 1), lines)
        usage = [[self.a], ["--prefix", "Alpha", self.a, self.b2], ["--prefix", "A", "--prefix", "A", self.a, self.b2],
                 ["--no-namespace", "--prefix", "A", "--prefix", "B", self.a, self.b2],
                 ["--no-namespace", "--namespace-all", self.a, self.b2]]
        for argv in usage:
            self.assertEqual(self.run_cli(*argv)[0], 2, argv)
        # options may appear between positionals
        self.assertEqual(self.run_cli(self.a, "--prefix", "Alpha", self.b2, "--prefix", "Beta")[0], 0)
