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
    kind: Literal["read", "write", "send", "idle", "random_write", "random_send", "poll", "custom"]
    address: int = Field(default=0, ge=0)
    data: int = Field(default=0, ge=0)
    mask: int = Field(default=255, ge=0)
    cycles: int = Field(default=0, ge=0, le=1000000)
    count: int = Field(default=1, ge=1, le=1024)


class Sequence(Model):
    id: str
    agent: str
    purpose: str
    operations: list[Operation] = Field(min_length=1, max_length=256)
    fact_ids: list[str] = Field(min_length=1)


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


class Test(Model):
    id: str
    stages: list[list[str]] = Field(min_length=1, max_length=128)
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


class CodePlan(Model):
    contract: Literal["verification_codegen_v1"] = "verification_codegen_v1"
    top: str
    clock: str
    reset: str
    reset_active: Literal["high", "low"]
    clock_period_ns: int = Field(default=10, ge=2, le=1000000)
    reset_cycles: int = Field(default=8, ge=2, le=10000)
    defines: list[str] = Field(default_factory=list, max_length=32)
    request_timeout_cycles: int = Field(default=10000, ge=1, le=10000000)
    facts: list[Fact] = Field(min_length=1, max_length=256)
    agents: list[Agent] = Field(min_length=1, max_length=16)
    tie_offs: list[TieOff] = Field(default_factory=list, max_length=128)
    registers: list[Register] = Field(default_factory=list, max_length=128)
    sequences: list[Sequence] = Field(default_factory=list, max_length=128)
    routes: list[Route] = Field(default_factory=list, max_length=64)
    checks: list[Check] = Field(default_factory=list, max_length=64)
    tests: list[Test] = Field(default_factory=list, max_length=64)
    hooks: list[Hook] = Field(default_factory=list, max_length=32)
    coverage: list[CoverageGoal] = Field(default_factory=list,max_length=64)
    questions: list[str] = Field(default_factory=list)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def identifier(value):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", value) or value in RESERVED:
        raise ValueError(f"Invalid generated identifier: {value!r}")
    return value


def pointer(value, path):
    if not path.startswith("/"):
        raise ValueError("plan_pointer must be a JSON pointer")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value
