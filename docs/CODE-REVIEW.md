# ASTRO — Code Review

**Repo:** `secw01f/astro` @ `f3ba212` (PR #22 merge) · **Reviewed:** 2026-06-11

## Methodology & tooling

- **Initial evaluation — Claude Fable 5 (Ultracode mode):** multi-agent orchestration — subsystem maps → dimension finders (correctness, security, concurrency, error-handling, API-contract, quality) + an independent Codex pass → a completeness critic → adversarial verification of every finding.
- **Completion & verification — Claude Opus 4.8 (Ultracode mode) + OpenAI Codex CLI:** every finding re-verified against source, with a Codex CLI session as an independent rubber-duck reviewer.

Every finding was verified against source at the cited `file:line`; **none were refuted**. Severities reflect post-verification consensus.


## Summary

| Severity | Count |
|---|---|
| 🟠 HIGH | 4 |
| 🟡 MEDIUM | 16 |
| 🔵 LOW | 20 |
| **Total** | **40** |

**Scope:** correctness, robustness, API-contract, and maintainability. Dominant themes: **broken or unreachable endpoints**, **blocking calls on the asyncio event loop** (embeddings, DNS, file I/O) that stall the single-worker service under concurrency, **data-model / pagination correctness bugs**, and **dead code / dependency-pinning hygiene**. Each finding cites a verified `file:line` with a suggested fix.

## 🟠 HIGH

### 1. GET /agent/prompts is unreachable — shadowed by GET /agent/{id}
`api/src/router/agent.py:204`

`@agent_router.get("/{id}")` (line 49) is registered before `@agent_router.get("/prompts")` (line 204). Starlette matches routes in registration order, so a request to `GET /agent/prompts` matches `/{id}` with `id="prompts"`. FastAPI then validates the `id: int` parameter, which fails with 422 Unprocessable Entity. The prompts-listing handler `get_prebuilt_prompts` is never invoked, so clients can never list prebuilt prompts.

**Fix:** Declare the static `/prompts` route before the dynamic `/{id}` route, or constrain the dynamic route with a path converter (e.g. `/{id:int}`).

### 2. update_prebuilt_prompt is completely broken: compares against builtin id and ignores request body
`api/src/router/agent.py:213`

PATCH /agent/prompt/{id} omits the `id` path parameter from the function signature:
```python
@agent_router.patch("/prompt/{id}")
async def update_prebuilt_prompt(prompt: UpdatePrompt, session: session_dep) -> dict[str, Prompt]:
    stmt = select(Prompt).where(Prompt.id == id)
```
Because `id` is not a parameter, `Prompt.id == id` compares the column against Python's builtin `id` function, so the query never matches a real row (it will 404 every time, or error on bind). Worse, even if a prompt were found, the update is a no-op: `prompt.prompt = prompt.prompt` (line 218) re-assigns the row's existing value to itself and never applies the `UpdatePrompt.prompt` from the request body. The endpoint can never update a prompt.

**Fix:** Add `id: int` to the signature, query `Prompt.id == id`, and apply the body: `prompt.prompt = body.prompt` (rename the body param to avoid shadowing the loaded row).

### 3. fastembed embedding (CPU-bound + first-use model download) executes on the main FastAPI event loop
`api/src/tool/memory.py:57`

`_store_memory` builds `Memory(..., embedding=_embed(content), ...)` (line 57) and `_recall_memory` computes `Memory.embedding.cosine_distance(_embed(query))` (line 70) inside async functions. These coroutines are not run in the tool's worker thread: `MemoryToolset` tools call `run_sync(_store_memory(...), app_loop=app_loop)` (lines 141/156), and `run_sync` (api/lib/tool/__init__.py:21) submits the coroutine to the application event loop via `asyncio.run_coroutine_threadsafe(coro, app_loop)`. `_embed` is synchronous, CPU-bound ONNX inference, and on first call `_get_model()` (line 16-20) downloads and loads the BAAI/bge-small-en-v1.5 model — seconds to minutes of blocking work executed directly on the single uvicorn event loop (entrypoint runs one worker). Every memory_store/memory_recall tool call from any agent freezes the entire API (all users, all SSE streams, auth, everything) for the duration. MemoryToolset is attached to every supervisor and supporting agent in run_stack, so this is a normal-flow stall.

**Fix:** Compute the embedding off-loop: `embedding = await asyncio.to_thread(_embed, content)` (and the same for the query in _recall_memory), and pre-warm `_get_model()` at startup in a thread so the model download never happens on the loop.

**Verified / corrected:** Severity left at high. One nuance: the finding's "all users" framing is slightly overstated for what is effectively a single-operator deployment (default "stack" user, one Docker stack), so the real-world blast radius is "freezes all concurrent agent runs and SSE streams for the single operator" rather than a multi-tenant outage. This does not change the technical correctness or the severity — the first-call model download (seconds to minutes) executing on the sole event loop is a genuine availability stall on a normal-flow code path used by every agent.

### 4. Blocking dnspython calls inside async tool functions block the entire tools-service event loop and defeat the 20s wait_for cap
`tools/src/dns/tools.py:54`

All DNS tools are declared `async def` but perform fully synchronous dnspython network I/O on the event loop: `ans = resolver.resolve(qname, rdt)` (line 54, used by dns_lookup/dns_email_auth/dns_tls_policy/dns_dnssec_probe/dns_delegation with caller-controlled `lifetime` up to 60s and caller-controlled nameservers), and `xfr = dns.query.xfr(input.nameserver, origin, lifetime=input.lifetime)` plus `dns.zone.from_xfr(xfr, ...)` (lines 228-229) with `lifetime` up to 120s against a caller-supplied server. The dns router executes these with `await asyncio.wait_for(tool.func(...), timeout=20)` (tools/src/dns/__init__.py:31-34), but because the coroutine never reaches an await point, the timeout callback can never fire and cancellation is impossible — the whole tools-service event loop is blocked for up to the full dnspython lifetime (120s for AXFR). During that window every other tool request (web, reporting, asm, threatmodel) on the single-worker service stalls, and dns_delegation can chain many sequential blocking resolves (NS + A + AAAA per NS host) in one call.

**Fix:** Wrap the blocking dnspython work in `await asyncio.to_thread(...)` (e.g. run _safe_resolve and the xfr/from_xfr pair in a thread), which also makes the router's wait_for(20) actually enforceable; alternatively clamp `lifetime` to below the router timeout.

## 🟡 MEDIUM

### 5. Startup makes blocking outbound get_tools() calls with no error handling, so a tools-service outage prevents API boot
`api/api.py:118`

Startup seeds five default toolsets by awaiting `get_tools(web_toolset.url)` etc. (lines 118, 167, 216, 265, 314) with no try/except around them. `get_tools` performs outbound HTTP to the tools service (api/lib/tool/http.py:246, httpx.AsyncClient with only the implicit default timeout). Unlike init_db (which has a retry loop), these calls are unguarded: if the tools service is unreachable or slow at boot (a common compose start-order race), get_tools raises and `startup_event` propagates the exception, so the API fails to start at all rather than degrading. There is also no timeout/retry, so a hung tools service stalls startup.

**Fix:** Wrap each seeding block in try/except that logs and continues (toolsets can be synced later), and/or add a bounded retry with explicit timeout as done for init_db.

**Verified / corrected:** The claim "There is also no timeout/retry, so a hung tools service stalls startup" is inaccurate. httpx.AsyncClient() defaults to a 5-second timeout (not unbounded), so a hung/slow tools service raises httpx.TimeoutException after ~5s rather than stalling startup indefinitely. The corrected statement: there is no try/except and no retry, so any get_tools failure (connection refused at boot, non-2xx via raise_for_status, or a 5s timeout) propagates out of startup_event and prevents the API from booting — it fails fast rather than hanging. The proposed fix (wrap in try/except to log-and-continue, or add bounded retry like init_db) remains valid.

### 6. CLI user creation discards the generated password — created accounts are unusable
`api/cli/src/users.py:21`

`password = generate_password(12)` is passed to create_user (which stores only the hash) and then dropped; the success message `print(f"The user {newuser_username} has been created with role {role}")` never reveals it and no reset token is issued. An admin using this CLI creates an account nobody can ever log into.

**Fix:** Print the generated password (or create a password-reset token like POST /auth/user/create does) after creation.

### 7. SupportingAgent retry re-executes the entire agent run, repeating side-effectful tool calls
`api/lib/agent/__init__.py:245`

On a 'retryable' error the whole agent run is replayed:
```python
for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
    try:
        return super().run(*args, **kwargs)
    except Exception as e:
        if _is_retryable_error(e) and attempt < _RETRY_MAX_ATTEMPTS:
            ...
            time.sleep(_RETRY_SLEEP_SECONDS)
            continue
        raise
```
If an exception occurs after some tools already executed (e.g. an HTTP POST/PUT/DELETE via the web toolset, a spec write, or a report save), the retry restarts the agent from scratch and re-invokes those already-completed side-effectful tools — duplicate writes/requests. `_is_retryable_error` (lines 17-26) also matches substrings like `"timeout"` or `"429"` anywhere in the exception text, so unrelated errors trigger this replay. Compounding it, `time.sleep(60)` blocks the worker thread that runs `supervisor.run`.

**Fix:** Only retry idempotent operations, or scope retry to the failing LLM call rather than the whole agent run; tighten `_is_retryable_error` to inspect exception types/status codes instead of substring matches, and avoid a 60s blocking sleep in the run path.

### 8. redis.asyncio client cached across asyncio.run() event loops in limiter/cache singletons
`api/lib/llm/limiter.py:131`

RedisTokenBucketLimiter and RedisPromptCache (line 197) lazily create one `Redis.from_url(...)` client and cache it on the module-level singletons. RateLimitedChatGenerator.run() executes from worker threads (supervisor.run goes through asyncio.to_thread) and calls `asyncio.run(self._limiter.acquire(...))` per LLM call — each call creates and then closes a fresh event loop, but the cached redis client's pooled connections stay bound to the loop where they were created. The second and subsequent calls reuse connections attached to a closed loop ('Event loop is closed' / cross-loop Future errors), and concurrent runs in multiple threads share one client across simultaneously live loops. The in-code comment (lines 117-119) acknowledges the cross-thread use but the lock only guards creation, not loop affinity. Breaks every stack execution once LLM_LIMITER_ENABLED or LLM_PROMPT_CACHE_ENABLED is turned on.

**Fix:** Create the Redis client per event loop (e.g. keyed by id(asyncio.get_running_loop()) or stored in a contextvar), or run a single dedicated background loop/thread for limiter+cache I/O instead of asyncio.run per call.

### 9. Single cached redis.asyncio client reused across distinct asyncio.run() event loops
`api/lib/llm/limiter.py:277`

RateLimitedChatGenerator.run() (used in the stack worker-thread path, where no event loop is running) calls `asyncio.run(...)` per LLM call:
```python
asyncio.run(self._cached_get(payload))
...
asyncio.run(self._limiter.acquire(self._provider, self._model, payload))
```
Each `asyncio.run` creates and then closes a new event loop. `_get_redis` caches the client on `self._redis` (limiter.py:127-132 and 193-198) the first time, binding redis.asyncio's connection pool/locks to that first loop. On the second LLM call a fresh loop runs but reuses the cached client bound to the now-closed first loop, raising RuntimeError ('Event loop is closed' / future attached to a different loop). When `LLM_LIMITER_ENABLED` or `LLM_PROMPT_CACHE_ENABLED` is set, the second LLM call of every stack run fails. The threading.Lock noted at line 117 does not address loop binding.

**Fix:** Do not cache a redis.asyncio client across loops in the sync path: create (and close) the client inside each acquire/get/set call, or key the cached client by the running loop, or use a synchronous redis client for the asyncio.run path.

**Verified / corrected:** Minor precision: the claim "the second LLM call of every stack run fails" is approximately correct but the exact trigger is "the first reuse of the cached client under a loop different from the one whose `asyncio.run()` created the connection." The client is created lazily on first awaited command, so the first `asyncio.run` that actually issues a redis command succeeds, and the next `asyncio.run` reusing that cached client fails. Also the bug only manifests when the feature flags are explicitly enabled and REDIS_URL is set (both flags default False), which the finding does state as a precondition.

### 10. MCP toolset build failures are silently swallowed, dropping agent capabilities without signal
`api/lib/tool/resolver.py:125`

In build_agent_toolset_catalog, MCP handling wraps validation/build in `try: ... except Exception as e: logger.error("Error adding MCP toolset %s: %s", toolset.url, e)` (lines 111-127), and the `else` branch on an invalid server only logs (`logger.error("Invalid MCP server: %s", toolset.url)`, line 124). In both cases the tool is silently dropped and execution continues, whereas HTTP toolsets raise (lines 128-139). The user's agent then runs without a toolset it explicitly attached, with no error surfaced to the caller — failures (auth errors, unreachable MCP server, build errors) are indistinguishable from success, and `is_valid_server` itself already swallows all exceptions to return False (mcp.py:58-60), compounding the silent loss.

**Fix:** Make MCP failures behave consistently with HTTP (raise an HTTPException), or at minimum propagate a structured warning into the run stream so the caller knows a requested toolset was unavailable.

**Verified / corrected:** The finding's framing that "HTTP toolsets raise" on the same failure classes MCP swallows is partially wrong. http_toolset_factory does not perform connectivity validation at build time — it builds from stored DB specs and only raises on missing-token/config errors; an unreachable HTTP server fails lazily at tool-invocation time, not at build. The true asymmetry is that MCP eagerly probes the server (is_valid_server) and swallows connectivity/auth/non-2xx failures, dropping the toolset, whereas HTTP defers connectivity to runtime and only raises for config/token problems at build. The core defect (MCP build/validation failures silently dropping a requested toolset with no signal to the caller) is confirmed.

### 11. All API and tools dependencies are completely unpinned
`api/requirements.txt:1`

api/requirements.txt lists 16 packages (`fastapi`, `sqlmodel`, `haystack-ai`, `amazon-bedrock-haystack`, `anthropic-haystack`, `mcp-haystack`, `redis`, ...) with no version specifiers at all; tools/requirements.txt (lines 1-8) is the same. Every `docker compose up --build` (deploy.sh runs this unconditionally) installs whatever is latest, so builds are non-reproducible and behavior can change under you: the code already relies on deprecated/removed-in-newer-majors surfaces (`@api.on_event("startup")` in api/api.py:31 and tools/api.py:67, pydantic v2 internals, fast-moving haystack-ai/mcp-haystack APIs). A routine rebuild can break the service with no code change.

**Fix:** Pin versions (at minimum compatible ranges, ideally a lock file generated via pip-tools/uv) for both api/requirements.txt and tools/requirements.txt.

### 12. Login 'stack' inactive branch uses a malformed query and dereferences possibly-None user
`api/src/router/auth.py:40`

The first stack-user branch is broken:
```python
if default_stack_user_active != "1":
    statement = select(User).where(User.username == "stack", User)
    result = await session.exec(statement)
    user = result.first()
    user.enabled = False
    raise HTTPException(status_code=403, detail="User not valid.")
```
`select(User).where(User.username == "stack", User)` passes the mapped class `User` as a WHERE criterion, which SQLAlchemy rejects (ArgumentError) — so this raises a 500 instead of the intended clean 403. Even if the query ran, `user.enabled = False` would raise AttributeError when no stack user exists, and the assignment is never committed (and is immediately followed by an unconditional raise that rolls back the session), so it accomplishes nothing. Any attempt to log in as `stack` once the Redis activation flag is gone hits this buggy path.

**Fix:** Drop the dead query/assignment and just raise the 403 (the correct check already exists later at lines 57-64): `if default_stack_user_active != "1": raise HTTPException(status_code=403, detail="User not valid.")`.

### 13. delete_user performs a bare delete with no cascade, breaking deletion of any user that owns resources
`api/src/router/auth.py:201`

delete_user does `await session.delete(user)` directly. The User model owns agents, stacks, llms, credentials, and memories via plain foreign keys (api/src/db/models.py:37-42), and no relationship declares a delete cascade and no FK column declares ON DELETE CASCADE (grep for cascade/ondelete returns nothing). Other delete handlers in this codebase manually cascade — delete_stack deletes Message and AgentStackLink rows first (stack.py:518-528) and delete_llm nulls agent.llm_id first (llm.py:123-127) — which is direct evidence the authors know auto-cascade does not happen here. As written, deleting any user who has created an agent/stack/LLM raises a Postgres FK violation (or an async lazy-load error trying to NULL children), surfacing as an unhandled 500 and leaving the admin unable to delete real users. It can also orphan rows (Credentials holding encrypted secrets, Memories) if the constraint were ever relaxed.

**Fix:** Manually cascade dependent rows (agents, stacks, llms, credentials, memories and their link rows) before deleting the user, mirroring delete_stack, or declare ON DELETE CASCADE / SQLAlchemy cascade='all, delete-orphan' on the User relationships. Wrap the delete to convert IntegrityError into a clean 409/400.

### 14. Pagination 'more' flag treats SQL row offset as a page index
`api/src/router/message.py:48`

The query applies `offset` as a SQL row offset (`statement = statement.offset(body.offset)`, line 37), but the `more` computation treats it as a page index:
```python
more = total > limit * (offset + 1)
```
With e.g. limit=50, offset=50 (skip 50 rows), total=120, this yields `more = 120 > 50*51 = 2550` → False, even though 20 older messages remain unfetched. The flag is wrong for any non-zero offset. Additionally `total` (line 33) ignores the offset entirely, so the count and the page selection are computed on inconsistent bases.

**Fix:** Compute remaining rows from the actual offset: `more = (offset + len(messages)) < total` (using the offset/limit semantics actually applied to the query), rather than treating offset as a page number.

### 15. FileRunSession leaked in process-global registry on every error path before the runner task starts
`api/src/router/stack.py:302`

`FileRunRegistry.register(file_session)` runs at line 302, but the only cleanup, `FileRunRegistry.unregister(run_id)`, lives inside the detached runner task's finally block (line 432) which is created at line 439. Any failure between 302 and 439 leaves the session permanently registered. Several such failures are reachable per request: supporting-agent missing LLM (`raise HTTPException(... agent {agent.id} is missing an LLM)`, line 329), LLM/credential ownership 403/404 (lines 332-346), `build_agent_toolset_catalog` raising 403/400/500 (line 360), or `supervisor.warm_up()` raising (line 382). Because run_id is a fresh uuid4 each call, `FileRunRegistry._sessions` (a class-level dict in api/lib/file/request.py) accumulates orphaned entries holding queues, the event loop, and pending futures, growing unbounded over time.

**Fix:** Wrap the body after register() in try/except that calls FileRunRegistry.unregister(run_id) on any exception before re-raising, or register the session only immediately before asyncio.create_task(runner()) once all fallible setup has succeeded.

### 16. Assistant/tool message positions collide across runs because stack.last_position is never advanced for them
`api/src/router/stack.py:396`

run_stack obtains one position via `next_position` (which increments and persists `Stack.last_position` once) for the user message, then tracks assistant/tool positions in a separate in-memory counter:
```python
_position = await next_position(session, id, user_id)   # user msg, bumps last_position once
...
assistant_position_state = {"next": _position + 1}
```
storage_consumer (lib/message/__init__.py) increments `assistant_position_state` for each assistant/tool message but never updates `Stack.last_position`. So after run 1: user msg at position 0 (last_position=0), assistant msg at position 1, tool msgs at 2,3... On run 2, `next_position` returns last_position+1 = 1 for the new user message — colliding with run 1's assistant message at position 1. Every stack executed more than once produces duplicate `position` values, corrupting message ordering and the position-based pagination in message.py.

**Fix:** Advance `Stack.last_position` to the highest position actually consumed by the run (persist the final value of assistant_position_state back to the stack), or allocate all run positions through a single authoritative counter.

**Verified / corrected:** Minor path correction only: the helper functions are in api/lib/message/__init__.py (imported as `lib.message`), not api/src/lib/message/__init__.py as written in the finding. All cited code, line numbers, and the described collision behavior are accurate.

### 17. Fire-and-forget asyncio.create_task(runner()) with no saved reference
`api/src/router/stack.py:439`

`asyncio.create_task(runner())` (line 439) discards the returned Task. The event loop holds only weak references to tasks; per the asyncio documentation a task without a strong reference "may be garbage collected at any time, even before it's done." If the runner task is collected mid-run, the stack execution dies silently: FileRunRegistry.unregister never runs (leaking the run session and pending futures), `main_queue.put(None)` is never sent, so the fanout and storage tasks leak and the client's SSE stream (`event_stream(client_queue)`) hangs forever waiting for the terminator. The same pattern means any exception escaping runner's own except/finally would only surface at GC time.

**Fix:** Keep a strong reference for the task's lifetime, e.g. add it to a module-level `set` with `task.add_done_callback(tasks.discard)`, or track it on the FileRunSession/registry so it is also cancellable on shutdown.

### 18. Blocking file I/O for user uploads and agent file reads executes on the event loop
`api/src/router/stack.py:474`

`row = save_user_file(user_id, file.filename or "upload", content, ...)` (line 474) is called in the async submit_run_file handler; save_user_file does synchronous `mkdir`, `write_bytes(content)` and `write_text` (api/lib/file/storage.py:33,42-43) of the full upload on the event loop. Worse, the agent-side file tools route through `run_sync(..., app_loop=app_loop)` (api/src/tool/file.py:105,115), which executes `_read_file`/`_list_files` ON the application loop via run_coroutine_threadsafe (api/lib/tool/__init__.py:21-22), so `get_user_file`'s `data_path.read_bytes()` (api/lib/file/storage.py:71) and `list_user_files`'s glob + per-file `read_text` loop (lines 53-57) — over arbitrarily large user uploads — block the single-worker API loop on every file_read/file_list/file_request tool call.

**Fix:** Wrap the storage calls in `await asyncio.to_thread(...)` at the call sites (submit_run_file, _read_file, _list_files), or make lib/file/storage.py async using to_thread internally.

### 19. CLI `llms update` always sends provider, so server validator rejects every key-less update
`client/src/commands/llm.py:80`  _(finders said high; de-rated after verification)_

The update command forces `--provider` to be supplied: `@click.option("--provider", type=click.Choice([...]), required=True, ...)` and unconditionally adds it to the payload (`if provider: payload["provider"] = provider`). The server's `UpdateLLM.validate_keys` (api/lib/llm/models.py:43-57) short-circuits only when provider is absent: `if "provider" not in fields_set: return self`. Because the CLI always sends provider, the validator always runs and then demands the key: for anthropic/openai `if "key" not in fields_set: raise ValueError("An ... API Key is required")`, and for bedrock it additionally requires `key_id` and `region`. But the CLI only sends `key` when the user opts in, and never collects `key_id`/`region` for updates at all. Result: `astro llms update --provider anthropic 5` to rename or change the model returns HTTP 422 unless the user re-enters the key, and `astro llms update --provider bedrock 5` can NEVER succeed (key_id/region cannot be sent). The normal 'update an LLM without re-entering its secret' flow is broken.

**Fix:** Make `--provider` optional in the CLI update command (do not send it unless the user is actually changing it), or change `UpdateLLM.validate_keys` to only enforce key/key_id/region presence when the provider value is actually changing relative to the stored row (the router has the existing LLM available).

**Verified / corrected:** Severity reduced from high to medium: the issue is real and confirmed, but it is a functional/UX breakage (HTTP 422 on metadata-only updates; bedrock updates impossible via CLI), not a security vulnerability. Minor clarification: the proposed fix note "the router has the existing LLM available" is true of the handler but NOT of the validator — UpdateLLM.validate_keys runs at FastAPI body-parse time before the handler queries the DB, so fixing it server-side requires moving the provider-change check into the handler (which has existing_llm) rather than the model validator.

### 20. Blocking dnspython calls inside async tools make the 20s exec timeout ineffective and stall the event loop
`tools/src/dns/tools.py:228`

DNS tools run synchronous, blocking dnspython operations directly inside `async def` functions with no thread offload — e.g. dns_axfr_probe does `xfr = dns.query.xfr(input.nameserver, origin, lifetime=input.lifetime)` and `dns.zone.from_xfr(...)` (lines 228-229), and _safe_resolve calls `resolver.resolve(...)` (line 54). The exec router wraps these in `asyncio.wait_for(..., timeout=20)` (tools/src/dns/__init__.py:31-34), but wait_for cannot cancel a synchronous call that never yields to the loop, so the 20s timeout does not fire until the blocking call returns. dns_axfr_probe accepts `lifetime` up to 120.0 (le=120.0) and dns_lookup up to 60.0, so a caller can block the shared tools-service event loop for up to 120s, hanging all concurrent tool requests, while the advertised timeout provides no protection.

**Fix:** Run blocking dnspython calls via asyncio.to_thread (or a thread pool) so wait_for can actually cancel them, and bound the per-call lifetime to well under the router timeout.

## 🔵 LOW

### 21. router-scaffold CLI command crashes on every invocation (undefined Path, Path+str concat, bare except)
`api/cli/src/routers.py:11`

`template_dir = Path("../templates").resolve()` — only `pathlib` is imported, `Path` is undefined → NameError on first call. Even fixed, line 17 `output = str(router_dir + f"{name}.py")` adds a Path to a str (TypeError). The bare `except:` at line 25 would mask the write error with a generic message. The command is dead, misleading tooling.

**Fix:** Import `from pathlib import Path`, build the output path with `router_dir / f"{name}.py"`, and catch OSError specifically.

**Verified / corrected:** The headline implies the bare `except:` masks the crash; it does not. The NameError at line 11 occurs before the try/except (lines 19-26), so the command dies with an uncaught NameError traceback rather than the generic "failed to create" message. The bare-except is a separate, real code-quality defect that only masks errors inside the `with open(...)` write block. The TypeError at line 17 (Path + str) and undefined-Path NameError at lines 11-12 are both confirmed.

### 22. _is_retryable_error matches retry keywords anywhere in the exception string
`api/lib/agent/__init__.py:17`  _(finders said medium; de-rated after verification)_

`_is_retryable_error` (lines 17-26) does `message = str(exc).lower()` then returns True if substrings like `"429"`, `"timeout"`, `"timed out"`, or `"connection error"` appear anywhere in the text. Exception messages frequently embed echoed tool arguments/results, URLs, or model output; any non-retryable error whose text merely contains e.g. "timeout" (a tool parameter named timeout, a 429 appearing in returned content, a validation message) is misclassified as retryable, triggering the 60s sleep + full agent re-run (see related retry bug). This converts permanent failures into long hangs and duplicated side effects.

**Fix:** Classify retryability on exception type and structured status codes (e.g. provider rate-limit/timeout exception classes, HTTP status attributes) rather than substring matching on the stringified exception.

**Verified / corrected:** Two refinements: (1) The claim that tool results/arguments containing "timeout" or "429" trigger retries is largely incorrect for this codebase — tools catch their own errors and return result strings (e.g. _error_response in tools/src/web/tools.py), which are not raised exceptions and never reach _is_retryable_error. Only an actual raised Exception whose str() contains a keyword is misclassified. (2) The finding omits that _is_retryable_error also matches "rate_limit" and "rate limit". Net: a real latent fragility in retry classification, but the practical false-positive surface is narrower than described, and impact (wasted 60s sleeps + redundant agent re-runs in a single-operator deployment) is low rather than medium.

### 23. Dead 'else: agent' statement in register_supporting_agent
`api/lib/agent/__init__.py:200`

```
if not isinstance(agent, SupportingAgent):
    raise TypeError(...)
else:
    agent
```
The `else: agent` branch is a bare expression statement with no effect — dead code that suggests an unfinished assignment or registration step.

**Fix:** Remove the else branch.

### 24. UpdateAgent omits the type/role and supervisor-no-tools validation that CreateAgent enforces, allowing invalid agent states via PATCH
`api/lib/agent/models.py:62`

`CreateAgent.validate_type_and_role` (lines 48-60) enforces that supervisor/supporting types map to the correct role sets and that supervisors cannot carry `toolset_ids`/`tool_ids`. `UpdateAgent` (lines 62-70) has no validator, and `update_agent` (api/src/router/agent.py:91-115) applies `type`/`role`/`toolset_ids`/`tool_ids` independently without re-checking the invariant. A client can PATCH an agent to `type=supervisor` while assigning toolsets/tools, producing a data-model state that `create` forbids. At runtime supervisors ignore their toolsets, so the attached tooling is silently dead, and the stored agent violates the create-time contract.

**Fix:** Add the same `model_validator` logic to `UpdateAgent` (validating the effective type/role and rejecting toolsets/tools on supervisors), or re-validate the resulting agent state in the update route after merging changes.

### 25. Dead function password_reset_token_valid misleads about the reset flow
`api/lib/auth/auth.py:143`

`async def password_reset_token_valid(user_id, token)` is never called anywhere (the router resolves token→user_id directly via get_password_reset_token_user_id). A reader auditing the reset flow can be misled into thinking a user-id/token cross-check exists. Same file also has the no-op `token = token` at line 22.

**Fix:** Delete password_reset_token_valid (and the `token = token` line) or wire it into the reset endpoint.

### 26. FileRunRegistry is process-local class state — breaks under any multi-worker deployment
`api/lib/file/request.py:78`

`class FileRunRegistry: _sessions: dict[str, FileRunSession] = {}` (lines 77-78) stores live run sessions (with their asyncio.Queue, loop reference, and pending Futures) in a class-level dict. The upload endpoint /stack/{id}/run/{run_id}/file (api/src/router/stack.py:464) resolves runs via this in-process dict. The shipped entrypoint runs a single uvicorn worker so this currently works, but scaling to `uvicorn --workers N` (or multiple replicas) silently breaks the file_request flow: the upload request lands on a worker that has no entry for the run_id and returns 404 while the agent stays blocked until the 3600s timeout. There is no shared-store fallback or any guard documenting the single-process assumption.

**Fix:** Either enforce/document the single-worker assumption, or move run registration to Redis (run_id -> worker identity) with worker-affinity routing, and have the upload endpoint return a distinguishable error when the run exists but is owned by another process.

### 27. Supporting-agent streamed responses are accumulated but never persisted (no 'end' event ever emitted for them)
`api/lib/message/__init__.py:64`  _(finders said medium; de-rated after verification)_

storage_consumer accumulates streamed tokens per `(agent, run_id)` key and only writes the assistant Message when an `"end"` event for that key arrives. But the only `.end()` call in the codebase is `_callback.end()` for the supervisor (src/router/stack.py:433); supporting agents' StreamingCallback instances emit start/token/tool_result but never end. Their fully accumulated text in `messages[key]` is silently discarded when the loop breaks on the None sentinel, so the DB transcript only contains the supervisor message plus 2000-char tool_result previews. The per-agent accumulation machinery is half-dead code that misleads readers into thinking all agents' outputs are stored.

**Fix:** Either emit an end event per supporting agent (e.g. call each _support_stream.end() in runner's finally) or flush remaining non-empty `messages` entries to the DB before exiting storage_consumer; if only supervisor output should be stored, stop accumulating tokens for other agents.

### 28. No client-disconnect handling: client_queue grows unboundedly after the SSE consumer is cancelled
`api/lib/message/__init__.py:110`

`fanout` keeps doing `await client_queue.put(item)` (line 110) for the whole run. When the SSE client disconnects, Starlette cancels the `event_stream(client_queue)` generator (api/src/router/stack.py:441-449), but nothing signals fanout, so every token/start/file_request event for the remainder of the run accumulates in the unbounded asyncio.Queue with no consumer. Long verbose runs after a disconnect grow memory until the run ends; `file_request` events also go nowhere, leaving the run parked for the full 3600s file timeout with no user able to see the request (the registry endpoint still works, but the prompt was lost).

**Fix:** Detect consumer cancellation (e.g. event_stream sets a flag / closes the queue in a finally block) and have fanout stop writing to client_queue, or use a bounded queue with drop-oldest semantics for the client leg.

### 29. init_db retry loop never breaks on success, re-running schema creation 10 times every startup
`api/src/db/db.py:25`

The retry loop has no break/return after a successful attempt:
```python
for attempt in range(max_retries):
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(SQLModel.metadata.create_all)
    except Exception as e:
        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)
        else:
            raise e
```
On the first successful iteration nothing breaks the loop, so `CREATE EXTENSION` + `create_all` run on all 10 iterations every startup. The operations are idempotent so there is no data corruption, but it does 10x redundant DDL/round-trips on each boot — a logic error (missing `break`).

**Fix:** Add `break` (or `return`) at the end of the `try` block after a successful schema creation.

### 30. ToolSet.validate_auth_type validator is malformed and never enforces the invariant
`api/src/db/models.py:268`

The before-validator is written as an instance method referencing `self`:
```python
@model_validator(mode="before")
def validate_auth_type(self, data: Any) -> Any:
    if self.auth_required and self.auth_type is None:
        raise ValueError("An authentication type is required for an authenticated toolset")
    return data
```
A pydantic `mode="before"` model validator must be a classmethod receiving the raw input data; here the first positional arg `self` would actually receive the raw value (a dict), so `self.auth_required` would be a dict attribute access. Moreover SQLModel table models skip pydantic validation on construction, and `ToolSet` is never passed through `model_validate` (only `ToolSetPublic` is), so this validator never runs at all. The auth_required/auth_type invariant it claims to enforce is silently not enforced at the model layer (the only real enforcement is `validate_auth_fields` in the router/service path).

**Fix:** Rewrite as a proper classmethod before-validator operating on the data dict (e.g. `@classmethod def validate_auth_type(cls, data): ...`), or remove it and rely solely on validate_auth_fields so the dead/broken validator does not mislead.

### 31. new_llm uses two sequential commits, orphaning the credential row on partial failure
`api/src/router/llm.py:58`

new_llm commits the Credential first (lines 62-63), then separately adds the LLM, assigns credential_id, and commits again (lines 68-70). The two writes are not in a single transaction. If the second commit fails (e.g., the unique key_id constraint on LLM, or any DB error), the already-committed Credential row (holding an encrypted API key) is left orphaned with no LLM referencing it and no cleanup path, leaving inconsistent state in the credential table.

**Fix:** Add both objects and commit once so the credential and LLM are created atomically (or wrap in an explicit transaction and roll back on failure).

### 32. delete_llm orphans the Credential row holding the encrypted API key
`api/src/router/llm.py:129`

`await session.delete(llm)` removes the LLM but never deletes the Credential referenced by `llm.credential_id`, so the encrypted provider key persists in the credential table forever with no owner-facing way to remove it. This has drifted from the toolset deletion path, where delete_toolset_record → delete_toolset_user_credentials (lib/tool/service.py:131-155) carefully removes orphaned credentials.

**Fix:** Fetch and delete the linked Credential (after confirming no other LLM references it) inside delete_llm.

**Verified / corrected:** Comparison path is `api/lib/tool/service.py`, not `api/src/lib/tool/service.py` (line range 131-155 is correct). The behavioral claim — delete_llm orphans the Credential row, with no cascade/relationship/endpoint to remove it — holds as stated; only the cited path of the comparison file is wrong. Severity is appropriately low — a data-hygiene issue, not user-facing.

### 33. PATCH /stack/{id} silently ignores supervisor/supporting membership changes
`api/src/router/stack.py:195`  _(finders said medium; de-rated after verification)_

update_stack does a blind mass setattr from the request body:
```python
updates = stack.model_dump(exclude_unset=True)
for key, value in updates.items():
    setattr(existing_stack, key, value)
```
`UpdateStack` (lib/stack/models.py) exposes `supervisor: Optional[int]` and `supporting: Optional[list[int]]`, but the `Stack` ORM model has no such columns — only an `agents` relationship. Setting `existing_stack.supervisor`/`existing_stack.supporting` just creates unmapped instance attributes that are never persisted. A client that PATCHes a stack to change its supervisor or supporting agents gets a 200 with no error, but the agent membership is unchanged — a silent no-op / data-loss-of-intent bug.

**Fix:** Handle `supervisor`/`supporting` explicitly (resolve to Agent rows with ownership/type checks like create_stack and reassign `existing_stack.agents`), and pop them out of the generic setattr loop so only real columns (name, description) are set.

**Verified / corrected:** Severity overstated as medium; corrected to low. This is a silent no-op that fails closed — the PATCH returns 200 but membership stays unchanged and nothing is corrupted. Also a minor path correction: the model file is at api/lib/stack/models.py, not lib/stack/models.py.

### 34. Each stack run pins a default-executor thread for its full duration (up to hours), exhausting asyncio.to_thread capacity
`api/src/router/stack.py:416`  _(finders said medium; de-rated after verification)_

`result = await asyncio.to_thread(supervisor.run, messages=messages_for_run)` (line 416) runs the whole multi-agent supervisor loop on the loop's default ThreadPoolExecutor, capped at min(32, cpu_count + 4) threads. The thread is held for the entire run, which can be very long: SupportingAgent retries sleep synchronously with `time.sleep(_RETRY_SLEEP_SECONDS)` = 60s per attempt in that thread (api/lib/agent/__init__.py:253), and the file_request tool blocks the thread in `run_sync(...).result()` while `wait_for_file` waits up to FILE_REQUEST_TIMEOUT_SECONDS = 3600s (settings.py:21, api/src/tool/file.py:130-133, api/lib/file/request.py:62-74) for the user to upload a file. Once N concurrent/paused runs reach the executor cap, every subsequent `asyncio.to_thread` in the process silently queues — new stack runs for ALL users hang with no feedback (their runner task is started but supervisor.run never begins), since the API runs as a single uvicorn worker. There is no dedicated/bounded executor, no queue-depth visibility, and no per-user cap.

**Fix:** Run supervisor.run on a dedicated, explicitly sized ThreadPoolExecutor (loop.run_in_executor(custom_executor, ...)) with a concurrency limit and a fast-fail/queue-full response, and reduce thread hold time (async retry sleeps; reconsider parking a thread for a 1-hour file wait).

**Verified / corrected:** Settings path is api/settings.py:21 (not api/src/settings.py as cited) — immaterial. Severity should be low, not medium: the process-wide-stall-for-all-users scenario requires near-cap concurrent paused runs, which is unrealistic for the single-operator single-worker deployment. Also stronger than stated on one point: the file_request wait blocks the worker thread via a timeout-less `run_coroutine_threadsafe(...).result()` in run_sync, so the thread is genuinely pinned for the full up-to-3600s wait, not merely 'blocked' loosely.

### 35. Dev dependency group pins httpx to a range that contradicts the main dependency constraint
`client/pyproject.toml:24`

Main dependencies require `"httpx (>=0.28.1,<0.29.0)"` (line 12) while `[tool.poetry.group.dev.dependencies]` declares `httpx = "^0.29.0"` (line 24). The two constraints are mutually exclusive, so `poetry lock`/`poetry install` with the dev group fails to resolve — drifted duplicate pinning of the same package.

**Fix:** Remove httpx (and click) from the dev group or align the version ranges with the main dependencies.

**Verified / corrected:** The httpx mutual-exclusivity and resolution-failure claim is correct as stated (line 12 vs line 24, ranges `>=0.28.1,<0.29.0` vs `^0.29.0`=`>=0.29.0,<0.30.0` have empty intersection). However, click is wrongly implicated: main `click (>=8.3.1,<9.0.0)` and dev `click = "^8.3.1"` are equivalent (`^8.3.1` = `>=8.3.1,<9.0.0`), fully compatible, and poetry.lock proves it by locking click 8.3.2 in `groups = ["main", "dev"]`. The fix should target only httpx (align the dev range to `>=0.28.1,<0.29.0` or drop httpx from the dev group); the "(and click)" in the proposed fix is unnecessary. Note the committed lock is already stale relative to the conflicting edit — httpx is locked main-only at 0.28.1.

### 36. Sync httpx.Client is never closed while the async client is carefully closed
`client/src/astro.py:44`

`ctx.obj["client"] = httpx.Client(base_url=url)` is created for every command, but the result_callback close_client (lines 51-63) only closes `async_client`; the sync client and its connection pool are never closed. Asymmetric resource handling — the code clearly intends to clean up clients but misses one of the two.

**Fix:** Call `ctx.obj["client"].close()` in close_client (or use the clients as context managers).

### 37. list_llms missing return after error; get_llm_by_id has no status check
`client/src/commands/llm.py:14`

list_llms: `if response.status_code != 200: click.echo(...)` has no `return`, then `llms = response.json()["llms"]` executes anyway → KeyError/JSONDecodeError crash on any API error (sibling commands like create/update/delete all return after the error message — drifted copy). get_llm_by_id (lines 33-35) performs no status check at all before `response.json()["llm"]`.

**Fix:** Add `return` after the error echo in list_llms and a status check in get_llm_by_id.

### 38. loader() is dead machinery: collected registries are discarded; registration is an import side effect
`tools/lib/tool.py:30`

`loader()` dynamically imports `src.*.tools` and returns a list of registries, but the only caller (`startup()` in tools/api.py:67-69) ignores the return value, and every router already imported its Registry at module import time — so loader() does nothing useful and misleads readers into thinking tools are plugin-loaded at startup. Related latent crash in the same file: `_input = hints.get("input")` (line 14) silently stores `input=None` on ToolDef for a tool function lacking an `input` type hint, which would only blow up later at exec time on `tool.input(**arguments)`.

**Fix:** Delete loader() and the startup hook (or make it the single registration mechanism), and raise at decoration time when a tool function has no 'input' type hint.

### 39. Blocking file I/O in async reporting tools runs on the tools-service event loop
`tools/src/reporting/tools.py:143`

The reporting tools are `async def` but do synchronous filesystem work on the loop: `path.write_text(input.content, encoding="utf-8")` (line 143), `content = path.read_text(encoding="utf-8")` (line 160), the append in `with path.open("a", ...): file.write(section)` (lines 178-179), and the stat/glob loop in list_reports (lines 196-211). Report contents are LLM-generated and can be large; each call briefly blocks the single-worker tools-service event loop, stalling concurrently executing web/dns/asm tool calls. Same dead-timeout caveat as the DNS tools: `asyncio.wait_for(..., timeout=20)` in the router cannot interrupt these since the coroutine never yields during the I/O.

**Fix:** Wrap the read/write/stat operations in `await asyncio.to_thread(...)`.

### 40. Tool exec handlers swallow all exceptions and return str(e) to the caller
`tools/src/web/__init__.py:38`

Every tools-service exec endpoint catches broadly and returns the stringified exception: `except Exception as e: return ExecResponse(result=None, error=str(e))` (web __init__.py:38-42, and identically dns/__init__.py:38, asm/__init__.py:38, reporting/__init__.py:41, threatmodel/__init__.py:40). This both swallows all failure types into a 200 response and forwards raw `str(e)` — which can contain internal paths, library traces, target hostnames, or nmap/dnspython internals — back to the caller, where it propagates into the agent stream and stored transcript. Internal error detail is exposed and genuine faults are masked as ordinary tool results.

**Fix:** Return a generic error message to the caller with an internal log of the full exception, and distinguish expected tool errors from unexpected ones (let unexpected errors produce a 500 rather than a stringified leak).

**Verified / corrected:** The claim that every failure type (including nmap/dnspython/httpx internals) is swallowed and leaked here is overstated: expected tool errors (timeouts, request failures, blacklisted targets) are handled inside the tool functions and returned as normal structured results, so they never reach the broad except at line 38 — only unexpected exceptions, Pydantic ValidationError, and asyncio.TimeoutError do. Also, the API-to-tools boundary is HMAC-signed and the deployment is self-hosted Docker Compose, so the leaked text reaches the operator's own agent/transcript rather than an untrusted external caller. Severity remains low.
