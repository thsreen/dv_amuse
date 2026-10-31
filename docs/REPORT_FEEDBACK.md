# Human feedback on the Markdown report

Generated testplan Markdown ends with **Human feedback and completion review**.
For each section, edit `Requested` to `DONE` or leave `OPEN`, write ordinary-language
feedback, and add evidence: comma-separated source IDs from the report or file paths
relative to its `dv/` directory. Keep the section IDs and hidden snapshot markers.
The Assessment column is calculated; editing it cannot force completion.

Apply your edited report (replace the example run directory and reviewer):

```bash
.venv/bin/python -m dv_agent.cli review-feedback \
  --out runs/<run>/dv \
  --file runs/<run>/dv/testplan_doc.md \
  --reviewer "Your name"
```

The tool analyzes every row. DONE requires explicit feedback, a resolving reference,
and a PASS section. Otherwise it records OPEN/NEEDS_WORK with reasons. A stale report
is rejected. JSON stores the reviewer, timestamp, feedback and analysis; Markdown and
HTML show the same review result. A revision directory retains the previous JSON,
submitted Markdown and analysis. Other edits in the full Markdown report are retained.

This completes **human review of report content only**. It does not clear generation
blockers, change inference authority, accept an HITL binding, set simulation PASS or
claim DUT sign-off. Use the existing natural-language HITL workflow for binding
changes; use `/run` and `/regress` for execution evidence. Apply feedback when code
is not running; the workflow refuses a concurrent code-generation lock.
