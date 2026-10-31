# Silicon Copilot HITL bridge

Registers the `/dvapprove` Telegram command using Hermes's calling-session context.
It accepts acknowledgements only from configured human user IDs and the configured
Telegram chat. Request ID/nonce and current plan/interface snapshot must match.

Install the directory as `~/.hermes/plugins/silicon-copilot-hitl/`, enable it and restart
the gateway. The gateway Python must have `dv_agent` and its dependencies installed.
See [setup and workflow](../../docs/HUMAN_REVIEW.md). No credentials are stored here.

Human replies are natural language: `/dvapprove rst is active low`, followed by
`/dvapprove yes, approve` after reviewing the interpreted binding. No JSON or nonce
is needed. Multiple current requests require an explicit request ID; ambiguous
replies never select a run automatically. The configured model may translate broader
phrasing but cannot approve; confirmation must come from the authorized human.
