# Fork Changes

This fork updates ASTRO after an independent third-party review of the project.
It focuses on user-impacting correctness, reliability, operational hardening,
and safer defaults.

## Methodology

The original review used Claude Fable 5 in Ultracode mode for multi-agent
subsystem mapping, dimension-specific review passes, completeness checking, and
adversarial finding verification. Claude Opus 4.8 in Ultracode mode completed
and re-verified the findings against source, with GPT-5.5 used as an
independent rubber-duck reviewer. Fix implementation was prepared with Codex and
reviewed against the findings with GPT-5.5 before validation.

## What changed

- Fixed API correctness issues around route ordering, prompt updates, stack
  membership updates, pagination, and LLM update behavior.
- Reduced event-loop blocking by moving CPU-heavy or synchronous work off the
  main async paths where practical.
- Hardened authentication, session invalidation, password handling, bootstrap
  setup, and CLI credential file permissions.
- Reworked credential handling around split deployment secrets and a new
  credential-encryption key path; obsolete credential records are invalidated
  rather than migrated.
- Added stricter tenant boundaries for files, specs, tool credentials, LLM
  ownership, memory access, and stack execution.
- Tightened tool execution by adding request signing coverage, replay
  protection, explicit outbound allowlisting, safer error responses, and
  bounded upload/output behavior.
- Improved Docker/deploy defaults by removing baked-in environment files,
  running services as a non-root user, requiring generated DB/Redis credentials,
  and limiting exposed service ports.
- Pinned dependency ranges and added focused tests for the new security helper
  behavior.
