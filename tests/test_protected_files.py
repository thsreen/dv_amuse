import hashlib
import json
from pathlib import Path

import pytest

from dv_agent.plan import methodology

ROOT = Path(__file__).resolve().parents[1]
RULES = "src/dv_agent/templates/methodology_rules_v0.json"
PROTECTED = [RULES, RULES + ".sha256", ".claude/settings.json", ".github/CODEOWNERS"]


def test_shipped_rules_match_the_owner_pin_and_load():
    pin = (ROOT / (RULES + ".sha256")).read_text().split()[0]
    assert hashlib.sha256((ROOT / RULES).read_bytes()).hexdigest() == pin
    assert [r["id"] for r in methodology.load_methodology_rules()][0] == "METH-XPROP-1"


def test_altered_or_unpinned_rules_are_refused(tmp_path, monkeypatch):
    rules = tmp_path / methodology.TEMPLATE_FILENAME
    rules.write_bytes((ROOT / RULES).read_bytes())
    (tmp_path / methodology.PIN_FILENAME).write_text((ROOT / (RULES + ".sha256")).read_text())
    monkeypatch.setattr(methodology, "default_rules_path", lambda: rules)
    assert methodology.load_methodology_rules()
    rules.write_text(rules.read_text().replace("immediately", "eventually"))  # an agent "improving" a rule
    with pytest.raises(methodology.ProtectedFileChanged, match="owner-pinned"):
        methodology.load_methodology_rules()
    (tmp_path / methodology.PIN_FILENAME).unlink()
    with pytest.raises(methodology.ProtectedFileChanged, match="pin file"):
        methodology.load_methodology_rules()


def test_user_rules_cannot_bypass_the_shipped_pin(tmp_path, monkeypatch):
    rules = tmp_path / methodology.TEMPLATE_FILENAME
    rules.write_text((ROOT / RULES).read_text() + " ")
    (tmp_path / methodology.PIN_FILENAME).write_text((ROOT / (RULES + ".sha256")).read_text())
    monkeypatch.setattr(methodology, "default_rules_path", lambda: rules)
    extra = tmp_path / "mine.json"
    extra.write_text(json.dumps({"rules": []}))
    with pytest.raises(methodology.ProtectedFileChanged):
        methodology.load_methodology_rules(extra)


def test_agent_permissions_deny_writes_and_shell_access_to_every_protected_file():
    deny = json.loads((ROOT / ".claude/settings.json").read_text())["permissions"]["deny"]
    for path in PROTECTED:
        assert f"Edit(/{path})" in deny and f"Write(/{path})" in deny, path
    assert any("methodology_rules_v0.json" in rule and rule.startswith("Bash(") for rule in deny)
    owners = (ROOT / ".github/CODEOWNERS").read_text()
    for path in PROTECTED:
        assert f"/{path}" in owners, path
    assert "docs/PROTECTED_FILES.md" in (ROOT / "AGENTS.md").read_text()
