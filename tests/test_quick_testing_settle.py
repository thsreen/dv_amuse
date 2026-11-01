"""Quick testing stops re-asking a collateral question that its allowed fields cannot change."""
import json

from dv_agent.codegen.units import InfrastructureAmbiguity as Ambiguity
from dv_agent.quality.quick_testing import ENV, settle_ambiguities

UNIT = 'collateral_bus'


def run_dir(tmp_path, answered=None, quick=True):
    if quick: (tmp_path / 'quick_testing.json').write_text('{}')
    if answered is not None:
        folder = tmp_path / 'human_review' / 'r1'
        folder.mkdir(parents=True)
        (folder / 'request.json').write_text(json.dumps(dict(unit=UNIT)))
        (folder / 'approval.json').write_text(json.dumps(dict(bindings=answered)))
    return tmp_path


ROLES, PORT = Ambiguity(kind='interface_roles', question='which role?'), Ambiguity(kind='port_binding', question='which port?')


def test_unanswered_questions_still_block_the_first_time(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, '1')
    assert settle_ambiguities(run_dir(tmp_path), UNIT, [ROLES, PORT]) == ([ROLES, PORT], [])


def test_after_an_approved_answer_the_same_questions_become_assumptions(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, '1')
    blocking, assumed = settle_ambiguities(run_dir(tmp_path, {'roles': {}}), UNIT, [ROLES, PORT])
    assert blocking == [] and assumed == [ROLES, PORT]


def test_an_answer_to_another_field_does_not_settle_a_role_question(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, '1')
    assert settle_ambiguities(run_dir(tmp_path, {'idle_values': {}}), UNIT, [ROLES]) == ([ROLES], [])


def test_outside_quick_testing_nothing_changes(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    answered = run_dir(tmp_path, {'roles': {}})
    assert settle_ambiguities(answered, UNIT, [ROLES]) == ([ROLES], [])


def test_a_run_that_is_not_an_isolated_quick_test_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV, '1')
    assert settle_ambiguities(run_dir(tmp_path, {'roles': {}}, quick=False), UNIT, [ROLES]) == ([ROLES], [])


def test_idle_values_are_not_a_question_kind_because_driver_templates_own_the_defaults():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Ambiguity(kind='idle_value', question='idle level?')
