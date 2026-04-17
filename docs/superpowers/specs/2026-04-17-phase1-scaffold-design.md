# Phase 1 — Scaffold + RAG Ingest: Design

**Date:** 2026-04-17
**Author:** Shashank Gupta (with Claude)
**Status:** Approved for implementation planning
**Related:** `CLAUDE.md` (Build order §Phase 1), `freight-rate-intelligence-PRD.md`

---

## 1. Purpose

Bootstrap the Freight Rate Intelligence repo from pre-scaffold to a runnable state where the knowledge base is ingested into PageIndex MCP and the project is ready for Phase 2 (scraper + cache). Phase 1 ships no agents, no UI, no tests — only the foundations needed for later phases to proceed.

## 2. Scope

### In scope

Primary deliverables:

1. `pyproject.toml` + `uv.lock` — Python 3.11+ pin, Phase-1 dependencies only
2. `.gitignore` — excludes secrets, caches, generated artifacts
3. `.env.example` — env-var template with blank placeholders
4. `.claude/settings.json` — merge a new `mcpServers.pageindex` block with existing contents
5. `knowledge_base/ingest.py` + `knowledge_base/tariffs/` directory + three PDFs uploaded to PageIndex

Supporting files (required for the above to work):

6. `knowledge_base/__init__.py` (empty) — makes `knowledge_base` a package so `python -m knowledge_base.ingest` resolves
7. `knowledge_base/tariffs/.gitkeep` — so the (otherwise empty until you drop PDFs in) directory is tracked in git
8. `README.md` (one-line stub) — required by `pyproject.toml`'s `readme` field; full content deferred

### Out of scope

`tools/`, `agents/`, `app.py`, `tests/`, `charge_patterns.json`, README.md body content (stub only for now), CI configuration. All deferred to Phases 2–6.

## 3. Decisions locked in during brainstorm

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Package manager: `uv`** (not pip or poetry) | ~10–100× faster installs, proper lockfile, modern Python tooling. `pyproject.toml` + `uv.lock` committed; `requirements.txt` generated on demand for Streamlit Cloud via `uv export --no-hashes`. |
| D2 | **Python: `>=3.11,<3.13`** | Upper bound guards against LangChain/Playwright breakage on a future Python. Easy to raise later. |
| D3 | **Ingest idempotency: SHA-256 content hash** | Registry stores `{doc_id, sha256}`. Unchanged PDFs are skipped on re-run; edited PDFs are re-uploaded. Guarantees PageIndex reflects current content without wasting quota. |
| D4 | **Ingest failure mode: continue-on-error, persist-per-success** | Non-zero exit if any PDF failed. Registry is saved after every successful upload (atomic temp-file rename). Combined with D3, a retry re-uploads only the failed ones. |
| D5 | **Phase-1 deps minimal: `requests` + `python-dotenv` only** | No `pypdf` — SHA-256 runs on raw file bytes, no parsing needed (PageIndex does extraction server-side). Dev deps (`pytest`, `ruff`, `mypy`) deferred to Phase 5 to keep `uv sync` fast. |
| D6 | **Registry schema bump** | CLAUDE.md originally described `{filename: doc_id}`. Updated to `{filename: {doc_id, sha256}}` to support D3. CLAUDE.md's "Knowledge base files" note will be updated as a Phase-1 step so docs stay consistent. |
| D7 | **`.env.example` values left blank** | Fake strings risk shipping to prod. Blank = missing key errors immediately and visibly. |
| D8 | **`requirements.txt` gitignored** | Source of truth is `uv.lock`. `requirements.txt` is a deploy artifact regenerated per Streamlit Cloud push. |
| D9 | **`uv.lock` committed** | Reproducible installs across contributors and CI. |

## 4. `knowledge_base/ingest.py` architecture

Single-module script, ~120 lines, no framework.

### Control flow

```
1. load .env via python-dotenv
2. read PAGEINDEX_API_KEY or exit(1) with instruction
3. scan knowledge_base/tariffs/*.pdf
4. load existing doc_registry.json (or {} if absent)
5. for each pdf:
     sha = sha256(file_bytes)
     entry = registry.get(filename)
     if entry and entry["sha256"] == sha:
         log.info("unchanged, skipped")
         continue
     try:
         doc_id = pageindex_upload(pdf_bytes, filename)
         registry[filename] = {"doc_id": doc_id, "sha256": sha}
         save_registry(registry)     # persist after every success
         log.info("uploaded → doc_id")
     except PageIndexError as e:
         failures.append((filename, str(e)))
         log.error(str(e))
6. print summary: N uploaded, M skipped, K failed
7. exit(0) if not failures else exit(1)
```

### Key functions

| Function | Responsibility |
|----------|----------------|
| `sha256_of(path: Path) -> str` | SHA-256 hex digest of file bytes |
| `load_registry(path: Path) -> dict` | Read JSON, return `{}` if missing |
| `save_registry(path: Path, reg: dict) -> None` | Atomic write via temp file + `os.replace` to prevent mid-save corruption |
| `pageindex_upload(pdf_bytes, filename) -> str` | POST to PageIndex upload endpoint; return `doc_id`; raise `PageIndexError` on non-2xx |
| `main()` | Orchestration + stdlib `argparse` for `--tariffs-dir`, `--registry`, `--dry-run`, `--verbose` |

### Registry schema

```json
{
  "iata_tariff.pdf":        { "doc_id": "doc_abc123", "sha256": "f4e8..." },
  "incoterms_2020.pdf":     { "doc_id": "doc_def456", "sha256": "a1b2..." },
  "surcharge_bulletin.pdf": { "doc_id": "doc_ghi789", "sha256": "9c7d..." }
}
```

### Error handling

| Condition | Behaviour |
|-----------|-----------|
| Missing `PAGEINDEX_API_KEY` | exit 1 with "export PAGEINDEX_API_KEY=... or fill `.env`" |
| Missing `knowledge_base/tariffs/` | exit 1 with "create `knowledge_base/tariffs/` and drop PDFs in" |
| Empty `tariffs/` | warning, exit 0 (no work is not a failure) |
| Per-PDF upload fails (non-2xx, network, timeout) | logged, appended to failures, loop continues |
| Ctrl-C mid-save | atomic rename guarantees `doc_registry.json` is never half-written |

### Logging

Stdlib `logging` at `INFO` (default) or `DEBUG` (`--verbose`). Matches CLAUDE.md's `LOG_LEVEL=INFO` and the "no `print()` for debugging" prohibition.

### Testing

Deferred to Phase 5. Code is factored so `pageindex_upload` is easily mockable and `main()` is the only I/O orchestration point.

### Open implementation detail

PageIndex's exact upload HTTP shape (single-step `POST /documents` with multipart, vs. two-step `/upload-url` + `PUT`, vs. JSON+base64) will be resolved during implementation planning via a quick docs fetch. The `pageindex_upload` wrapper is designed as a thin single-responsibility function so whichever shape wins can be implemented without rippling into the rest of the script.

## 5. `.claude/settings.json` — merged MCP block

Merge with existing contents (do not overwrite `enabledPlugins` or `extraKnownMarketplaces`):

```json
{
  "enabledPlugins":        { /* unchanged */ },
  "extraKnownMarketplaces": { /* unchanged */ },
  "mcpServers": {
    "pageindex": {
      "type": "http",
      "url": "https://api.pageindex.ai/mcp",
      "headers": { "Authorization": "Bearer ${PAGEINDEX_API_KEY}" }
    }
  }
}
```

**Important caveat (to be documented in CLAUDE.md as a Phase-1 step):** Claude Code expands `${PAGEINDEX_API_KEY}` at CLI launch time from the environment the CLI was started in. It does NOT auto-load from the project's `.env`. Users must `export PAGEINDEX_API_KEY=...` (or use a shell integration) before launching a Claude Code session.

## 6. `.env.example`

```
# LLM providers (fallback chain: Groq → OpenAI → Gemini)
GROQ_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=

# PageIndex MCP (required for RAG)
PAGEINDEX_API_KEY=

# Feature flags
LIVE_SCRAPING=false
LOG_LEVEL=INFO
```

Blank values per D7.

## 7. `.gitignore`

```
# Python
__pycache__/
*.py[cod]
.pytest_cache/
.ruff_cache/
.mypy_cache/

# Virtual env
.venv/

# Env vars
.env

# Generated artifacts
knowledge_base/doc_registry.json
*.db
*.sqlite3

# Streamlit Cloud export (regenerated from uv.lock; not source of truth)
requirements.txt

# OS
.DS_Store
```

Committed (not ignored): `uv.lock`, `pyproject.toml`, `.env.example`.

## 8. `pyproject.toml`

```toml
[project]
name = "freight-rate-intelligence"
version = "0.1.0"
description = "AI-powered freight rate comparison with hidden-charge detection"
authors = [{ name = "Shashank Gupta" }]
requires-python = ">=3.11,<3.13"
readme = "README.md"

dependencies = [
  "requests>=2.31",
  "python-dotenv>=1.0",
]

[tool.uv]
dev-dependencies = []   # populated in Phase 5

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Lower-bound pins in `pyproject.toml`; exact versions in `uv.lock`. `hatchling` is uv's default build backend (zero config).

## 9. Implementation sequence

Each step independently verifiable:

```
 1. README.md (one-line stub)                  → required by pyproject's readme field
 2. pyproject.toml + `uv sync`                 → .venv created, deps installed
 3. .gitignore                                 → before any generated artifact lands
 4. .env.example                               → user copies to .env, fills keys
 5. .claude/settings.json (merge mcpServers)   → PageIndex MCP available to Claude Code
 6. knowledge_base/tariffs/ + .gitkeep         → empty dir tracked
 7. knowledge_base/__init__.py (empty)         → enables `python -m knowledge_base.ingest`
 8. knowledge_base/ingest.py                   → the script
 9. User drops 3 PDFs into tariffs/            → manual
10. `uv run python -m knowledge_base.ingest`   → uploads, writes doc_registry.json
11. CLAUDE.md touch-ups                        → registry schema note; PageIndex env-var caveat
```

## 10. Acceptance criteria

Phase 1 is complete when all of these hold:

- `uv sync` completes cleanly on a fresh clone.
- With all three PDFs present in `knowledge_base/tariffs/`, `uv run python -m knowledge_base.ingest` produces a `doc_registry.json` with three entries (each `{doc_id, sha256}`) and exits 0.
- A second run prints "unchanged, skipped" for all three and makes zero PageIndex API calls.
- Editing the bytes of one PDF and re-running re-uploads only that PDF; the other two entries are untouched.
- PageIndex MCP is reachable from a fresh Claude Code session (the `find_relevant_documents` tool appears in the available tool list).
- CLAUDE.md's "Knowledge base files" section reflects the `{doc_id, sha256}` registry schema.

## 11. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| PageIndex upload shape unknown until docs read | `pageindex_upload` is a thin wrapper; implementation plan starts with a WebFetch against PageIndex docs |
| User hasn't exported `PAGEINDEX_API_KEY` before launching Claude Code | Documented caveat in CLAUDE.md; ingest script itself reads from `.env` and works standalone |
| PageIndex rate-limits a 3-PDF upload burst | Continue-on-error means other PDFs still succeed; failed ones resolve on a later run (with D3 idempotency, no re-upload of successes) |
| Repo is not currently git-initialised | Flagged to user; `git init` is a one-off step outside brainstorming scope |

## 12. Non-goals for Phase 1

- No retry/backoff logic on uploads (add later if needed; YAGNI for a 3-PDF seed corpus)
- No parallel uploads (serial is fine for 3 files; complexity not justified)
- No validation that PDFs are actually PDFs (PageIndex will reject invalid inputs)
- No CLI pretty-printing (stdlib `logging` output is sufficient)
- No README
