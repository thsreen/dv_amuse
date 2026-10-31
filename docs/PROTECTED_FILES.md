# Protected files

Some files decide what the plan calls "Recommended by DV agent" or whether an agent may proceed. A coding
agent (Claude Code, Codex or any other) must not change them. Only the owner does.

| File | Why it is protected |
|---|---|
| `src/dv_agent/templates/methodology_rules_v0.json` | The DV agent's recommendation source. Its rules become plan entries tagged DOCUMENTED / "Recommended by DV agent" and are force-injected into the plan. |
| `src/dv_agent/templates/methodology_rules_v0.json.sha256` | The owner's pinned digest of the file above. |
| `.claude/settings.json`, `.github/CODEOWNERS` | They hold the protection itself. |

## How it is enforced (layers, strongest first)

1. **Runtime pin (`plan/methodology.py`, `shipped_rules_bytes`).** Loading the rules checks the file against the pinned
   SHA-256 and raises `ProtectedFileChanged` on any difference. The plan stage cannot run on altered rules, and
   `tests/test_protected_files.py` fails.
2. **Agent permissions (`.claude/settings.json`, and the workspace `.claude/settings.json` one level up).** Claude Code
   denies Edit/Write on every protected path and denies any shell command that names the rules file. Reading stays allowed.
3. **Review (`.github/CODEOWNERS`).** Changes need the owner's review once branch protection requires Code Owners.
4. **Agent instructions (`AGENTS.md`).** Every agent is told not to modify these files and to ask instead.
5. **File mode.** The two rules files are read-only locally (`chmod 444`). Git does not carry this, so it is a speed bump.

Limits, stated plainly: an agent with unrestricted shell access and no permission rules can still write a file, and
Codex has no ignore file for write protection. Layers 1 and 3 do not depend on the agent's cooperation: a changed file
fails at run time and in review. Nothing here stops the owner.

## Changing a protected file (owner only)

1. Edit the file yourself.
2. Review the diff.
3. Re-pin: `cd src/dv_agent/templates && sha256sum methodology_rules_v0.json > methodology_rules_v0.json.sha256`.
4. Run `pytest -q`, then commit both files together.
