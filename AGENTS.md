# AGENTS.md

## Project mission

`dler-kun2` is the successor implementation. The installed CLI command remains `dler-kun` and must resolve to `dler_kun2.presentation.cli.main:main`. Keep the legacy `dler_kun` package only while migration compatibility work requires it; do not route the command back to the archived implementation.

## Ownership and layout

- `src/dler_kun2/domain/`: immutable requests, plans, results, and common errors.
- `src/dler_kun2/application/`: download, crawl, ranking, and job use cases.
- `src/dler_kun2/routing/`: the only default route registry and service ownership evidence.
- `src/dler_kun2/engines/<id>/`: site-specific adapters, parsers, clients, and response validation.
- `src/dler_kun2/infrastructure/`: shared HTTP, rate limiting, storage, configuration, and durable state.
- `src/dler_kun2/presentation/cli/`: CLI arguments and user-facing output.
- `src/dler_kun2/vendor/`: vendored tools. Preserve their provenance and prefer wrapper changes.
- `src/dler_kun/`: migration-era compatibility code; do not copy new v2 behavior into it by default.

## Architecture rules

- CLI calls application services; engines do not write to CLI output or own output directories.
- `EngineRegistry` owns routing. Do not route by a domain name alone when the same host may use different backends. Confirm page/API shape before adding aliases.
- Keep verified aliases in `routing/defaults.py`; keep uncertain aliases quarantined in `routing/registry.py`. A failed or unavailable probe is not proof of service ownership.
- Each engine returns common plans/results/errors. Unsupported operations use `unsupported_capability`.
- Shared HTTP calls use `HttpRuntime`; respect per-origin concurrency and `Retry-After`. Never rotate IP, account, token, proxy, or user-agent to evade limits.
- Output paths must remain under the selected root. Treat filenames, redirects, API data, and media URLs as untrusted.
- Never expose cookies, passwords, tokens, authorization headers, signed URLs, or secret query parameters in logs, fixtures, CLI output, or persisted metadata.
- Keep optional imports inside runtime paths so importing `dler_kun2` stays lightweight.

## Engine routing notes

- `gofile.io` is the GoFile API engine. `gofile-douga.com` and `gofilelab.com` are accepted only for verified ranking paths.
- `gofile.run` and Fun800/VLL share hosts are separate from `gofile.io` and use `gofilerun` or `mvfile`.
- Twimg-like aliases confirmed to use Fun800 are owned by `mvfile`. The legacy Twimg adapter has no default route until a distinct backend is verified.
- `85xo.com`, `85po.com`, and other aliases in `UNVERIFIED_HOSTS` remain unavailable until live page/API evidence supports registration.
- Current route/capability inventory is documented in `docs/engines.md` and can be checked with `dler-kun sites --json`.

## Quality gates

Before committing code changes:

```powershell
python -m ruff check src/dler_kun2 tests
python -m basedpyright
python -m pytest -q
python -m dler_kun2 --help
python -m dler_kun2 sites --json
```

Use focused checks while iterating. Do not claim an engine is fully compatible from a route match alone; verify parser behavior, partial failures, and output accounting. Update docs when supported routes, capabilities, command behavior, or configuration changes.
