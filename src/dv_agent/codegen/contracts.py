"""Typed implementation IR. DUT-specific information belongs here, never in templates."""
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from rtl_agent.source import RESERVED


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(Model):
    id: str
    statement: str
    source_id: str
    quote: str = Field(min_length=8)
    plan_pointer: str


class Agent(Model):
    id: str
    protocol: Literal["wishbone", "serial", "custom"]
    bindings: dict[str, str]
    fact_ids: list[str] = Field(min_length=1)
    bit_cycles: int = Field(default=16, ge=2, le=1000000)
    data_bits: int = Field(default=8, ge=5, le=8)
    parity: Literal["none", "even", "odd"] = "none"
    stop_bits: int = Field(default=1, ge=1, le=2)
    active: bool = True
    coverage_enabled: bool = True
    idle_values: dict[str,int] = Field(default_factory=dict)


class Register(Model):
    id: str
    agent: str
    address: int = Field(ge=0)
    width: int = Field(ge=1, le=64)
    access: Literal["RW", "RO", "WO"]
    reset: int | None = None
    mask: int = Field(ge=0)
    fact_ids: list[str] = Field(min_length=1)


class TieOff(Model):
    id: str
    signal: str
    value: int = Field(ge=0)
    fact_ids: list[str] = Field(min_length=1)


class Operation(Model):
    kind: Literal["read", "write", "send", "idle", "random_write", "random_send", "poll", "custom", "register_write"]
    register_id: str | None = None  # register_write: the declared register id; its address and agent come from the register
    address: int = Field(default=0, ge=0)
    data: int = Field(default=0, ge=0)
    mask: int = Field(default=255, ge=0)
    cycles: int = Field(default=0, ge=0, le=1000000)
    count: int = Field(default=1, ge=1, le=1024)


class SequenceBinding(Model):
    operation: int = Field(ge=0)
    field: Literal['data','address','count','cycles']
    variable: str


class SequencerVariable(Model):
    id: str
    agent: str
    width: int = Field(ge=1,le=64)
    default: int = Field(ge=0)
    fact_ids: list[str] = Field(min_length=1)


class Sequence(Model):
    id: str
    agent: str
    purpose: str
    operations: list[Operation] = Field(min_length=1, max_length=256)
    fact_ids: list[str] = Field(min_length=1)
    extends: str | None = None
    controls: list[SequenceBinding] = Field(default_factory=list,max_length=16)


class Condition(Model):
    agent: str
    address: int = Field(ge=0)
    mask: int = Field(ge=0)
    value: int = Field(ge=0)
    initial_value: int | None = Field(default=None, ge=0)


class Route(Model):
    id: str
    expected_agent: str
    expected_event: Literal["write", "read", "rx", "tx", "transaction"]
    actual_agent: str
    actual_event: Literal["write", "read", "rx", "tx", "transaction"]
    expected_address: int | None = None
    actual_address: int | None = None
    when: list[Condition] = Field(default_factory=list, max_length=8)
    mask: int = Field(default=255, ge=0)
    fact_ids: list[str] = Field(min_length=1)


class Check(Model):
    id: str
    agent: str
    kind: Literal["stable_until_ack", "known_controls"]
    fact_ids: list[str] = Field(min_length=1)


class SequencerSetting(Model):
    variable: str
    value: int = Field(ge=0)


class Test(Model):
    id: str
    stages: list[list[str]] = Field(min_length=1, max_length=128)
    sequencer_settings: list[SequencerSetting] = Field(default_factory=list,max_length=32)
    seed: int = Field(default=1, ge=1, le=2147483647)
    drain_cycles: int = Field(default=1024, ge=1, le=10000000)
    minimum_comparisons: int = Field(default=1, ge=1)
    fact_ids: list[str] = Field(min_length=1)


class Hook(Model):
    id: str
    target: str
    slot: Literal["driver.body", "monitor.body", "scoreboard.compare", "coverage.sample"]
    purpose: str
    fact_ids: list[str] = Field(min_length=1)


class CoverageBin(Model):
    name: str
    values: list[int] = Field(min_length=1,max_length=64)


class CoveragePoint(Model):
    name: str
    field: Literal['data','address','kind','error','data_bits','parity_mode','stop_bits']
    mask: int = Field(default=18446744073709551615,ge=0,le=18446744073709551615)
    shift: int = Field(default=0,ge=0,le=63)
    bins: list[CoverageBin] = Field(min_length=1,max_length=32)


class CoverageCross(Model):
    name: str
    points: list[str] = Field(min_length=2,max_length=4)


class CoverageGoal(Model):
    id: str
    agent: str
    points: list[CoveragePoint] = Field(min_length=1,max_length=8)
    crosses: list[CoverageCross] = Field(default_factory=list,max_length=8)
    sample_kinds: list[int] = Field(default_factory=list,max_length=5)
    sample_address: int | None = Field(default=None,ge=0)
    fact_ids: list[str] = Field(min_length=1)


class ClockPeriodRange(Model):
    name: str
    min_ps: int = Field(ge=2, le=1000000000)
    max_ps: int = Field(ge=2, le=1000000000)
    nominal_ps: int | None = Field(default=None, ge=2, le=1000000000)
    cited_chunk_ids: list[str] = Field(min_length=1, max_length=16)
    provenance: Literal['DOCUMENTED','INFERRED','ASSUMED'] = 'DOCUMENTED'
    inference_reason: str = ''


class CodePlan(Model):
    contract: Literal["verification_codegen_v1"] = "verification_codegen_v1"
    top: str
    clock: str
    reset: str
    reset_active: Literal["high", "low"]
    clock_period_ns: float = Field(default=10, ge=0.002, le=1000000)
    clock_period_ranges: list[ClockPeriodRange] = Field(default_factory=list, max_length=16)
    reset_cycles: int = Field(default=8, ge=2, le=10000)
    defines: list[str] = Field(default_factory=list, max_length=32)
    request_timeout_cycles: int = Field(default=10000, ge=1, le=10000000)
    facts: list[Fact] = Field(min_length=1, max_length=256)
    agents: list[Agent] = Field(min_length=1, max_length=16)
    tie_offs: list[TieOff] = Field(default_factory=list, max_length=128)
    registers: list[Register] = Field(default_factory=list, max_length=128)
    sequences: list[Sequence] = Field(default_factory=list, max_length=128)
    sequencer_variables: list[SequencerVariable] = Field(default_factory=list,max_length=64)
    routes: list[Route] = Field(default_factory=list, max_length=64)
    checks: list[Check] = Field(default_factory=list, max_length=64)
    tests: list[Test] = Field(default_factory=list, max_length=64)
    hooks: list[Hook] = Field(default_factory=list, max_length=32)
    coverage: list[CoverageGoal] = Field(default_factory=list,max_length=64)
    questions: list[str] = Field(default_factory=list)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


IDENTIFIER_RULE = ("identifiers start with a letter and contain only letters, digits and underscores "
                   "(no hyphens, dots or spaces) and are not reserved words")


def is_identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value)) and value not in RESERVED


def identifier(value):
    if not is_identifier(value):
        raise ValueError(f"Invalid generated identifier: {value!r}: {IDENTIFIER_RULE}")
    return value


def safe_identifier(value):
    """The closest valid identifier: runs of other characters become one underscore."""
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value)).strip("_") or "id"
    if not text[0].isalpha():
        text = "f_" + text
    return text + "_id" if text in RESERVED else text


def normalize_fact_ids(data):
    """Rename invalid fact ids in a model answer, and every `fact_ids` reference to them, in place.

    Fact ids are internal labels. Rejecting `F-RST-01` cost two model calls and stopped a run, so any answer
    anywhere in the code stage is repaired deterministically instead. Returns {old: new} for what changed.
    """
    facts = []

    def collect(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "facts" and isinstance(child, list):
                    facts.extend(f for f in child if isinstance(f, dict) and isinstance(f.get("id"), str))
                collect(child)
        elif isinstance(node, list):
            for child in node:
                collect(child)

    collect(data)
    taken = {f["id"] for f in facts if is_identifier(f["id"])}
    renamed = {}
    for fact in facts:
        if is_identifier(fact["id"]):
            continue
        new = base = safe_identifier(fact["id"])
        number = 2
        while new in taken:
            new, number = f"{base}_{number}", number + 1
        taken.add(new)
        renamed[fact["id"]] = new
        fact["id"] = new
    if renamed:
        def relink(node):
            if isinstance(node, dict):
                for key, child in node.items():
                    if key == "fact_ids" and isinstance(child, list):
                        node[key] = [renamed.get(x, x) if isinstance(x, str) else x for x in child]
                    else:
                        relink(child)
            elif isinstance(node, list):
                for child in node:
                    relink(child)
        relink(data)
    return renamed


def pointer(value, path):
    if not path.startswith("/"):
        raise ValueError("plan_pointer must be a JSON pointer")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value
