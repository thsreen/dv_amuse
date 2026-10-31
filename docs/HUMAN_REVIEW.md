# Human-in-the-loop infrastructure clarification

Basic infrastructure ambiguities have an explicit HITL/HIIT path. They do not become
assumptions, synthetic approvals or ordinary generation failures.

1. A scoped infrastructure step identifies a typed ambiguity: port binding, reset
   polarity, interface roles or idle value. Irrelevant requests for a clock scoreboard
   still receive normal prompt repair rather than being escalated as design questions.
2. Save a request under `<run>/human_review/<id>/request.json`, tied to the exact plan,
   interface snapshot, unit and question. Mark generation `WAITING_HUMAN`. Completed
   units remain checkpointed and no subsequent model step runs while waiting.
3. Ask a focused question in ordinary language, with consistently separated **Decision
   needed**, **Why this came up**, **Architecture and impact**, **Quick references** and
   **Your decision** sections. Show the affected ports relative to the DUT and up to two
   exact source excerpts with source IDs/locations. Distinguish implementation understanding
   that needs review from source facts. Save the structured brief in `request.json` and a
   formatted `review.md`; the full retrieved evidence remains in the request.

   At the terminal, answer naturally, for example:

   ```text
   rst is active low. This was confirmed with the RTL designer.
   ```

   The agent restates the interpretation as readable bullet points. Reply `yes, approve`
   to confirm, or explain a correction. An initial `yes` without a preceding interpretation
   cannot approve anything. No JSON, nonce or field names are required. Simple settings are
   interpreted locally; broader phrasing and role mappings use the configured model only
   as a translator, followed by value/scope validation and a separate human confirmation.
   The model cannot approve or fill missing settings from RTL or naming conventions.

   Wait up to `DV_HITL_USER_TIMEOUT_SECONDS` (default 120, shared across the conversation).
   Silence, rejection, uncertainty or timeout never grants approval. A noninteractive
   session escalates immediately. Raw clarification, interpreted settings, final natural
   confirmation and human identity are retained with the approval for audit.
4. On timeout, run one bounded Hermes advisory turn with toolsets disabled, then send
   a Telegram request using `hermes send`. Agent advice is labeled advisory and never
   accepted as human approval. Successful delivery is recorded to avoid duplicate messages.
5. The authorized human replies through the Hermes Telegram bot:

   ```text
   /dvapprove rst is active low. Confirmed with the RTL designer.
   /dvapprove yes, approve
   ```

   Send the second message only after reading the interpreted settings. The command
   wrapper routes the reply to this workflow; its contents are ordinary language.
   With multiple pending decisions, the bot asks which request is meant; prefix the
   response with that request ID. Nonces remain internal. Sender/chat allowlists and
   current plan/interface snapshot checks remain mandatory. Interpretations are scoped
   to the request, human and channel: another user's interpretation cannot be confirmed.
   The public terminal and Telegram workflows require conversational confirmation; JSON approval commands are no longer accepted.
6. A dedicated plan-revision workflow appends a **Human-approved infrastructure
   clarifications** section. JSON saves the binding, actor, timestamp, channel, reason,
   approval reference and comments. Both Markdown and HTML show `Approved by user …`.
   Original specification statements remain intact; this is an explicitly approved,
   infrastructure-only addendum, not wholesale approval of RTL-derived expectations.
7. The revision is staged/versioned under `dv/human_revisions/<id>/` with before/after
   hashes and the original JSON. Rendering happens before publishing; a revision lock
   prevents simultaneous terminal/Telegram revisions. Reapplying the same approval is
   idempotent; changed plans and conflicting responses are refused.
8. Generation reloads the revised plan and resumes with exact scoped human evidence.
   Generated bindings must honor the approved values and preserve approval fact lineage.
   No Xezim run is triggered. If generation has returned to the prompt, `/code` resumes it.

`DV_HITL_TELEGRAM_WAIT_SECONDS` controls how long the caller polls for an acknowledgement
after escalation (default 0: leave a durable waiting state and return to the prompt).
The Telegram plugin updates the plan immediately on approval even when generation is
not running. `plan-code` and `build-code` also report `WAITING_HUMAN`; their exit code 0
means the request was accepted/queued, not that code generation completed. Automation
must inspect the JSON status. A waiting latest build prevents execution of older code.

## Quick-testing auto approver (explicit opt-in)

**QUICK TESTING ONLY. This mode is not human approval, RTL-engineer validation or
verification sign-off. It is disabled by default.** Start the interactive orchestrator:

```bash
cd /proj/work/silicon_copilot/dv_agent
.venv/bin/python -m orchestrator_agent --quick-testing-auto-approve-inferences
```

Then enter `/code`. It selects the latest successful saved plan normally, makes an
isolated sibling run named `*-quick-testing-*`, and switches this session to that
copy. The original plan and its approvals remain unchanged. Normal saved-plan
selection excludes these copies. Start again without the flag to restore the usual
natural-language human review workflow; the flag does not persist in `.env`.

For each infrastructure HITL request (clock/reset bindings, roles or idle values),
the configured LLM evaluates the source excerpts, architecture context and allowed
ports/settings. It returns scoped bindings, reasoning and explicit assumptions.
Valid decisions are automatically accepted for this test run, without waiting for
terminal/Telegram acknowledgement. All existing port, width, timing, scope and
snapshot checks still apply. Invalid/model-failed evaluations remain pending; this
option does not force malformed or impossible bindings, bypass failed plan
foundations, or promote an entire RTL-derived specification. Existing generation
and retry budgets still apply.

Audit artifacts retain `TEST_AUTO_APPROVED`, `test_only: true`, model, reasoning and
assumptions in `auto_evaluation.json` and a separate `quick_test_approvals` collection.
Plan entries remain **INFERRED** with an explicit quick-testing warning in JSON,
Markdown and HTML. Generated SystemVerilog carries a test-only header; manifests
carry `test_only` and the warning. These records never claim an actual person
approved the decision. Normal code generation rejects a test-only plan, and the
inferred entries are eligible as infrastructure evidence only while opted in.

## Hermes/Telegram setup

The bridge plugin is shipped at `integrations/hermes_dv_hitl/`. Install that directory
as the user plugin `~/.hermes/plugins/silicon-copilot-hitl/`, in a Hermes gateway Python
installation that can import this repository's `dv_agent` package and its dependencies.
Enable/restart it using the normal Hermes plugin/gateway workflow. The repository copy
is reviewable; it does not automatically modify the global Hermes installation.

Configure the orchestrator environment and Hermes gateway environment consistently:

```sh
export DV_HITL_HERMES_TARGET='telegram:<chat-id>'
export DV_HITL_TELEGRAM_USER_IDS='<authorized-human-user-id>'  # comma-separated if needed
export DV_HITL_RUNS_ROOT='/proj/work/silicon_copilot/dv_agent/runs'
export DV_HITL_USER_TIMEOUT_SECONDS=120
export DV_HITL_TELEGRAM_WAIT_SECONDS=0
```

`DV_HITL_HERMES_BIN` and `DV_HITL_HERMES_AGENT_BIN` can override the executable paths.
Telegram credentials stay in Hermes configuration; no bot token is copied into the
run artifacts or passed to the LLM. Bot chat/user IDs must be explicitly configured;
the implementation does not guess a recipient from unrelated sessions.

Missing configuration or delivery failures leave the request pending, with diagnostics
in `escalation.json`. They never grant approval or discard the question. Review the
Hermes CLI/gateway installation on the actual host if delivery is unavailable. During
implementation here, `hermes --help` could not write its installation lock under the
read-only `/root/.hermes` directory; real Telegram delivery/plugin deployment was not
performed from this restricted workspace.

## Limits

This is targeted clarification of basic infrastructure, not a new approval gate for
every testplan or feature. General functional uncertainty remains subject to the
existing source/verification rules. Approval is bound to the request snapshot and
requires a reason. Shared host filesystem access is trusted; this is not a defence
against a malicious local process that can rewrite both code and approval artifacts.

## Startup messaging check

`/plan`, `/code`, advanced orchestrator runs and `dv-agent pipeline` attempt a startup
notification before generation. This sends only the operation, run folder name and UTC
start time through `hermes send`; it does not ask for approval. The first dashboard
checkpoint and `notification_<operation>.json` record delivery as SENT, UNCONFIGURED,
CONFIG_ERROR or DELIVERY_FAILED. A notification problem is nonfatal and verification
work continues. Dry runs do not send. Set `DV_AGENT_START_NOTIFICATION=0` to disable.

The target must be `telegram:<numeric chat ID>`. A bot token belongs in Hermes's
`TELEGRAM_BOT_TOKEN`, never in `DV_HITL_HERMES_TARGET`. Notification logs omit credentials
and raw provider output. Tests explicitly disable live startup messages by default.

## Notification recovery without a writable Hermes launcher

The default `DV_AGENT_NOTIFICATION_TRANSPORT=auto` tries Hermes first. If Hermes
fails before sending because its installation lock is read-only, or the executable
is missing, the sender uses Telegram's HTTPS API with the token already configured
in Hermes. It does not modify the Hermes installation or copy the token into logs.
`telegram` forces direct API delivery; `hermes` disables fallback.
`DV_HITL_HERMES_ENV_FILE` can select a named-profile `.env`; otherwise the sender
uses `HERMES_HOME/.env` or `~/.hermes/.env`.

A startup notification that fails before connecting (such as DNS failure) is saved
as QUEUED with a token-free request under `<run>/notification_outbox/`. Fresh runs
preserve the outbox. From the normal network-enabled host, retry pending messages:

```sh
cd /proj/work/silicon_copilot/dv_agent
.venv/bin/python -m dv_agent.core.notifications --flush runs
```

The worker loads the project's configuration, requires the queued recipient to match
the current destination, locks each item, and records confirmed message IDs. It
skips sent items. Timeouts/unknown delivery outcomes are not automatically resent,
and a worker crash leaves IN_FLIGHT for operator inspection rather than duplicate
delivery. Check the bot chat before manually requeuing an uncertain item.

This recovery fixes the application's dependence on a writable Hermes launcher.
It cannot grant a sandbox network access or repair host DNS. SENT is reported only
after the transport confirms it; a queued notification is not a delivered message.

## Delivery verification

A successful Hermes process exit is not delivery proof: Hermes also exits zero when
it skips a message. The sender now requests `hermes send --json` and requires an
explicit successful result plus a Telegram message ID. Skipped sends report
`DELIVERY_SKIPPED`; missing or mismatched receipts report `DELIVERY_UNCERTAIN`.
Uncertain sends are not automatically repeated. Old escalation receipts marked
SENT without a message ID become uncertain when reviewed again.

Run one direct check on the orchestrator host (loads the project configuration and
existing Hermes bot token; prints no credentials):

```bash
cd /proj/work/silicon_copilot/dv_agent
DV_AGENT_NOTIFICATION_TRANSPORT=telegram .venv/bin/python -m dv_agent.core.notifications --test
```

Only `SENT` with `message_id` confirms Telegram acceptance; it does not prove the
human read the message. A DNS error means the request did not reach Telegram.
The test sends one diagnostic message and does not approve or resume generation.

## Receiving the generated testplan on Telegram

When a testplan finishes generating (`/plan`, `dv-agent testplan`, or `dv-agent pipeline --testplan`, with a PASS
result), `testplan_doc.html` is uploaded as a document to the chat in `DV_HITL_HERMES_TARGET`. The caption names the run
and states that the plan is generated, not signed off.

- **Opt-out:** `DV_AGENT_SEND_TESTPLAN=0`. Nothing is sent without a configured target.
- **Confidentiality:** the plan can contain specification excerpts. It goes only to the configured chat; check that chat
  before enabling it for a confidential design.
- **Transport:** the Telegram Bot API with the token Hermes already holds (`auto` or `telegram`). The Hermes CLI has no
  verified file option, so transport `hermes` refuses to send documents rather than guess.
- **No duplicates:** the delivery is recorded in `dv/notification_testplan.json` with the file's SHA-256. The same content
  is not sent twice; a revised plan is sent again. An unconfirmed result (`DELIVERY_UNCERTAIN`, for example a timeout) is
  never retried automatically, because the file may already have arrived. A failure that provably did not reach Telegram
  is retried the next time the plan is generated.
- **Failure never affects the run.** The status is only recorded.
- **Resend on request:** `python -m dv_agent.core.notifications --send-testplan runs/<run>/dv` (exit code 1 unless `SENT`).
- Only `SENT` with a message ID confirms Telegram accepted the file; it does not prove anyone read it. Files up to 50 MB
  (Telegram's bot limit) are supported. Delivery has not been exercised against the real Telegram API from this
  environment; the tests use a mocked transport.
