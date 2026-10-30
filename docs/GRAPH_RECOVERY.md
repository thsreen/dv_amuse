# Automatic graph extraction and API recovery

`spec_graph` now extracts requirements and dependencies before testplan generation in both full and fast modes. Fast retains lexical retrieval; it no longer skips upfront extraction. A completed graph supplies existing requirements/dependencies to planning without on-demand dependency model calls. This supersedes the graph-free behaviour described in D-052.

Successful batch responses are saved atomically under the run's `llm_cache` (including responses containing no requirements or edges). A normal rerun or `/plan` in the same interactive session reconstructs the graph from completed responses and requests only missing batches. Model, instructions, schema and source payload form the cache key, so changed input is re-extracted. `--force` rebuilds graph artifacts while retaining response checkpoints; `--fresh` deliberately deletes them.

The graph is also saved after sequential batch application. Parallel extraction keeps only the configured number of requests in flight and stops scheduling when a request exhausts transient-error recovery. In-flight calls finish before returning; no graph writer is abandoned in a background thread. The graph tool waits for bounded API calls rather than applying the former 600-second whole-stage timeout. Other flow deadlines still apply.

Generation requests make at most five attempts. The initial output allowance scales with the serialized UTF-8 input payload: baseline allowance times input bytes divided by 2,000, rounded up. With the default baseline of 8192, the minimum is 8192 and the ceiling is 32768. This is a size heuristic, not an exact input-token count; larger chunks and multi-chunk batches receive more room. Explicit constructor output budgets remain fixed starting-budget overrides. CLI and orchestrator clients use automatic sizing.

Test-plan generation waits synchronously for bounded API calls instead of abandoning a worker after 600 seconds. Successful raw responses for register batches, sections and repairs are atomically saved under `llm_cache/testplan` (or an explicitly configured client cache). Same-directory reruns replay matching responses and reapply validation; failed API calls are retried. Changed dependent context can require a new request. Global flow limits are checked between tools, not during a running model stage. `--fresh` clears checkpoints. Existing runs made before this change have no automatic raw-response checkpoint unless their client already used a cache.

Every completed testplan section now also saves its graph lineage and partial JSON,
Markdown and HTML views. Pending sections are explicitly `NOT_RUN`. The document's
`generation_status` is `IN_PROGRESS`, `INTERRUPTED`, `ERROR`, `PARTIAL` or `COMPLETE`;
`COMPLETE` requires all required sections to pass. Partial views are for inspection;
recovery reconstructs and validates content from exact-match response checkpoints,
rather than trusting an incomplete document as a completed plan. Interruptions save
the latest partial report and record the exception type. The flow records an
interrupted step and final review/result instead of silently losing its ending.

Model requests default to **150 seconds per attempt**, including basic mode. Set
`META_REQUEST_TIMEOUT_SECONDS` to override it; explicit constructor timeouts take
precedence. Basic mode retains two attempts, full/fast five. Longer request timeouts
improve tolerance for slow responses but cannot guarantee the 10–15 minute demo target.

For diagnosis, each traced stage writes `llm_requests.jsonl` beside `trace.jsonl`.
It appends request/attempt starts **before sending**, outcomes after completion,
retry schedules and cache hits. Records include UTC timestamps, correlation/trace/span
IDs, model/API style, section/chunk IDs, input/instruction/schema byte counts,
timeout, output allowance, temperature, duration, response IDs, usage, HTTP status
and sanitized exception/cause class names. API keys, headers, endpoint URLs and
provider exception bodies are not included in this metadata log. Completed spans
retain their audit payloads in `trace.jsonl`; exception stack frames omit source
lines and exception messages. There is no periodic timer output. A start with no
outcome indicates an outstanding request or abrupt termination; it does not prove
which one. Orchestrator progress is persisted even without the live dashboard.

Transient network, timeout, rate-limit and server errors use exponential backoff. Every retry increases the preceding output budget by 25% (rounded up to an integer, bounded by the configured ceiling); malformed JSON is retried too. For a starting allowance of 8192, attempts allow 8192, 10240, 12800, 16000 and 20000. The first attempt uses the provider default temperature; retries use 0.1, 0.3, 0.0 and 0.2. If the provider rejects temperature, subsequent attempts omit it. Attempt five adds compact wording/atomic-statement constraints while preserving schema, source coverage and provenance requirements. Attempt settings and usage are recorded. Authentication and non-recoverable request errors fail immediately.

Embedding batches also retry transient failures up to five times with backoff. Embeddings have no temperature setting. Application retries own the budget; SDK automatic retries are disabled.

Five failed attempts stop that request. The graph build preserves completed work and reports BLOCKED; it does not loop indefinitely. Restart the same run after connectivity recovers to resume automatically. This prevents loss of successful extraction but does not guarantee lower first-run latency or a successful response from an unavailable service.
