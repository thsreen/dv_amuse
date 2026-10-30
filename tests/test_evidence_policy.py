from dv_agent.quality.evidence_policy import PROVENANCE_RULES, assessment
from dv_agent.plan.interfaces import _validate_groups


def test_direct_normalization_can_be_documented_but_missing_quote_cannot():
    text = "The WISHBONE slave accepts register reads and writes."
    support = dict(provenance="DOCUMENTED", quote=text, chunk_id="CH-1", inference_reason="")
    # Slave -> responder is an unambiguous terminology normalization.
    assert assessment(support, {"CH-1": text})["provenance"] == "DOCUMENTED"
    unsupported = assessment(support | {"quote": "All writes complete in one cycle."}, {"CH-1": text}, ["CH-1"])
    assert unsupported["provenance"] == "INFERRED" and unsupported["inference_reason"]
    assert assessment(support, {})["provenance"] == "ASSUMED"
    assert "Unvalidated RTL" in PROVENANCE_RULES


def test_group_properties_have_independent_statuses():
    text = "The WISHBONE slave accepts register reads and writes."
    direct = dict(provenance="DOCUMENTED", quote=text, chunk_id="CH-1", inference_reason="")
    proposal = dict(provenance="INFERRED", quote=text, chunk_id="CH-1",
                    inference_reason="The system interconnect peer is not identified by this source.")
    signal = dict(name="dat", chunk_id="CH-1", quote=text, direction="input")
    group = dict(name="WISHBONE", function="register access", category="bus", protocol="WISHBONE",
                 connected_to="", peer_type="interconnect", dut_role="responder", is_sideband=False,
                 signals=["dat"], rationale="", property_evidence={"name": direct, "dut_role": direct,
                                                                     "peer_type": proposal})
    groups, _ = _validate_groups([group], [signal], {"CH-1": text})
    assert groups[0]["provenance"] == "DOCUMENTED"
    assert groups[0]["property_evidence"]["dut_role"]["provenance"] == "DOCUMENTED"
    assert groups[0]["property_evidence"]["peer_type"]["provenance"] == "INFERRED"
