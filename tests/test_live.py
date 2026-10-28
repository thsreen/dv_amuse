"""Opt-in live checks: `pytest -m live` with MODEL_API_KEY (and optionally Langfuse keys) set."""
import os

import pytest

from dv_agent.extract import EXTRACT_INSTRUCTIONS, EXTRACT_SCHEMA, locate_quote
from dv_agent.llm import MetaClient
from dv_agent.trace import Tracer, langfuse_configured, read_trace

pytestmark = pytest.mark.live

TEXT = "Reset Value: 00h\nWhen bit 0 is '1' the counter decrements on every clock cycle."


@pytest.fixture(autouse=True)
def no_langfuse():
    """Overrides the offline conftest fixture so live keys stay visible."""


def test_meta_structured_extraction_contract(tmp_path):
    if not os.getenv("MODEL_API_KEY", "").strip():
        pytest.skip("MODEL_API_KEY not set")
    with Tracer(tmp_path / "t.jsonl", "live_meta") as tracer:
        result = MetaClient(cache_dir=None).structured(
            name="spec_requirements", instructions=EXTRACT_INSTRUCTIONS, schema=EXTRACT_SCHEMA,
            payload={"document": "live", "section": "1 Test", "pages": "1-1", "chunk_id": "CH-live",
                     "text": TEXT}, tracer=tracer)
    assert set(result.data) == {"summary", "entities", "requirements"}
    assert any(locate_quote(TEXT, r["quote"]) for r in result.data["requirements"])
    assert any(r["type"] == "generation" for r in read_trace(tmp_path / "t.jsonl"))


def test_langfuse_auth(tmp_path):
    if not langfuse_configured():
        pytest.skip("Langfuse keys not set")
    from langfuse import Langfuse
    assert Langfuse().auth_check()
