# Static review of spec_graph — 2026-10-30

Subsequent implementation: see [automatic recovery](GRAPH_RECOVERY.md). Both modes now extract in spec_graph with durable batch checkpoints; the graph tool no longer uses its former whole-stage background timeout. Findings below describe the earlier code.

No pipeline, model calls or tests were executed for this review, as requested.

- Fixed: repository discovery stripped leading dots from `../...`, breaking parent-relative paths. It now preserves them and accepts quoted paths containing spaces. The terminal accepts a bare existing absolute directory as a repository prompt. An unresolved new prompt clears the previous repository selection.
- Fixed: orchestrator wrappers did not pass `DV_AGENT_MODE` to graph building or planning. They now forward flow `mode` (when supplied), then the environment setting, then `full`. Set `DV_AGENT_MODE=fast` before starting the orchestrator to select the new path consistently.
- High timeout risk remains in full mode: the flow allows 600 seconds per tool, while full graph construction performs one call per chunk plus dependency-group calls. At the 90-second request timeout and three attempts, even one failed call can consume roughly 276 seconds including backoff. More workers reduce elapsed time only when the service responds; they do not reduce request count or guarantee the 600-second limit.
- The orchestrator timeout stops waiting for the worker; it does not terminate the underlying model calls. A timed-out worker can continue writing artifacts. Do not treat TIMEOUT as cancellation or immediately run another writer in the same output directory.
- Fast mode skips eager requirement/dependency model extraction in spec_graph and builds a deterministic index. This should remove the earlier extraction bottleneck by inspection. An enabled embedder still builds a dense index, so graph construction is not necessarily API-free. Later testplan sections still make model, repair and on-demand dependency calls and can time out independently.
- Parallel extraction fetches responses before applying them in stable order, preserving graph mutation ordering. Its executor waits for all submitted futures; an auth failure is only raised after this collection phase. It therefore is not fail-fast.
- Fast-mode dependency caching only recognizes pairs with an edge. A previous no-edge answer is queried again; repeated sections may make redundant calls. Fast-mode coverage uses lazily discovered requirements, so its ratio alone cannot establish recall against the full 163-requirement baseline.

Assessment: fast spec_graph is a plausible structural remedy for the earlier extraction timeout, after mode forwarding. Full mode is still exposed to the same deadline mismatch. End-to-end speed and requirement recall are unverified; the documented UART comparison gate remains necessary.
