# Phase 1 — Scaffold + RAG Ingest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the Freight Rate Intelligence repo from pre-scaffold to a runnable state where three seed PDFs are ingested into PageIndex MCP and the project is ready for Phase 2.

**Architecture:** Minimal scaffold driven by `uv` (Python 3.11+). A single-module ingest script (`knowledge_base/ingest.py`) reads PDFs from `knowledge_base/tariffs/`, hashes each one with SHA-256, and uploads only new-or-changed files to PageIndex via `POST /doc/`. A persistent JSON registry (`doc_registry.json`) maps filename → `{doc_id, sha256}` so re-runs are idempotent. `.claude/settings.json` is extended with an `mcpServers.pageindex` block so Claude Code agents can later query the ingested documents.

**Tech Stack:** Python 3.11+, `uv` (package manager + lockfile), `requests`, `python-dotenv`, stdlib `hashlib`/`logging`/`argparse`. PageIndex MCP for retrieval; PageIndex REST (`https://api.pageindex.ai/doc/`) for upload.

**Source spec:** `docs/superpowers/specs/2026-04-17-phase1-scaffold-design.md`

**Tests:** Deferred to Phase 5 per the approved spec. Each task instead uses manual verification commands with expected output. Ingest code is factored so `pageindex_upload` is easily mockable when tests are added later.

**Pre-flight check:** `uv` must be installed on the machine (`uv --version`). If missing: `brew install uv` (macOS) or `pip install uv` (fallback). All later `uv` commands assume it is on `$PATH`.

---

## Task 1: Initialize git repository + README stub

**Files:**
- Create: `README.md`
- Run: `git init`

- [ ] **Step 1: Initialize git**

Run from the project root:
```bash
git init
git branch -M main
```
Expected: `Initialized empty Git repository in .../Freight rate intelligence/.git/`

- [ ] **Step 2: Create README.md stub**

Create `README.md`:
```markdown
# Freight Rate Intelligence

AI-powered freight rate comparison with hidden-charge detection. Full docs in `CLAUDE.md` and `freight-rate-intelligence-PRD.md`.
```

- [ ] **Step 3: Initial commit**

```bash
git add README.md CLAUDE.md freight-rate-intelligence-PRD.md docs/ .claude/
git commit -m "chore: initial commit with existing design docs and settings"
```
Expected: clean commit; `git log --oneline` shows one entry.

---

## Task 2: Create pyproject.toml and generate lockfile

**Files:**
- Create: `pyproject.toml`
- Generated (by `uv sync`): `uv.lock`, `.venv/`

- [ ] **Step 1: Write pyproject.toml**

Create `pyproject.toml` with exactly this content:
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
dev-dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Sync environment**

```bash
uv sync
```
Expected: prints `Creating virtual environment at: .venv`, resolves `requests` + `python-dotenv` + transitive deps, writes `uv.lock`, ends with `Installed N packages` (exact N depends on transitive deps).

- [ ] **Step 3: Verify**

```bash
ls .venv/bin/python uv.lock
uv run python -c "import requests, dotenv; print('ok')"
```
Expected: both paths exist; command prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add pyproject.toml and uv.lock (Python 3.11+, requests, python-dotenv)"
```

---

## Task 3: Create .gitignore

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Write .gitignore**

Create `.gitignore`:
```gitignore
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

- [ ] **Step 2: Verify .venv is now ignored**

```bash
git check-ignore -v .venv/ knowledge_base/doc_registry.json requirements.txt .env
```
Expected: each line printed back with a match; exit code 0.

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore (excludes .env, .venv, caches, generated artifacts)"
```

---

## Task 4: Create .env.example

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Write .env.example**

Create `.env.example`:
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

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "feat: add .env.example with blank placeholders for all four API keys"
```

- [ ] **Step 3: Manual user action (not automated)**

Tell the user:
> Copy `.env.example` to `.env` and fill in your real keys (`GROQ_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `PAGEINDEX_API_KEY`). The `.env` file is gitignored and must never be committed.

---

## Task 5: Merge mcpServers block into .claude/settings.json

**Files:**
- Modify: `.claude/settings.json`

- [ ] **Step 1: Read current contents**

```bash
cat .claude/settings.json
```
Expected: JSON with `enabledPlugins` (7 entries including `claude-md-management@claude-plugins-official`) and `extraKnownMarketplaces` (3 entries).

- [ ] **Step 2: Add mcpServers block**

Edit `.claude/settings.json` — keep the existing `enabledPlugins` and `extraKnownMarketplaces` blocks untouched, add `mcpServers` as a new top-level key. Final file:

```json
{
  "enabledPlugins": {
    "claude-md-management@claude-plugins-official": true,
    "superpowers@superpowers-marketplace": true,
    "frontend-design@claude-plugins-official": true,
    "frontend-design@claude-code-plugins": true,
    "code-review@claude-code-plugins": true,
    "security-guidance@claude-code-plugins": true,
    "claude-mem@thedotmack": true
  },
  "extraKnownMarketplaces": {
    "superpowers-marketplace": {
      "source": { "source": "github", "repo": "obra/superpowers-marketplace" }
    },
    "claude-code-plugins": {
      "source": { "source": "github", "repo": "anthropics/claude-code" }
    },
    "thedotmack": {
      "source": { "source": "github", "repo": "thedotmack/claude-mem" }
    }
  },
  "mcpServers": {
    "pageindex": {
      "type": "http",
      "url": "https://api.pageindex.ai/mcp",
      "headers": { "Authorization": "Bearer ${PAGEINDEX_API_KEY}" }
    }
  }
}
```

- [ ] **Step 3: Validate JSON**

```bash
uv run python -c "import json; json.load(open('.claude/settings.json')); print('valid')"
```
Expected: `valid`.

- [ ] **Step 4: Commit**

```bash
git add .claude/settings.json
git commit -m "feat: add PageIndex MCP server block to .claude/settings.json"
```

- [ ] **Step 5: Manual user action**

Tell the user:
> Before your next Claude Code session, export the PageIndex key in your shell:
> ```bash
> export PAGEINDEX_API_KEY=pi-...
> ```
> Claude Code expands `${PAGEINDEX_API_KEY}` at CLI launch — it does NOT auto-read from the project `.env`. A shell integration (e.g. direnv) or putting the export in your zshrc is fine.

---

## Task 6: Create knowledge_base package structure

**Files:**
- Create: `knowledge_base/__init__.py` (empty)
- Create: `knowledge_base/tariffs/.gitkeep` (empty)

- [ ] **Step 1: Create directories and files**

```bash
mkdir -p knowledge_base/tariffs
touch knowledge_base/__init__.py
touch knowledge_base/tariffs/.gitkeep
```

- [ ] **Step 2: Verify structure**

```bash
ls -la knowledge_base/ knowledge_base/tariffs/
```
Expected:
```
knowledge_base/:
__init__.py
tariffs/

knowledge_base/tariffs/:
.gitkeep
```

- [ ] **Step 3: Commit**

```bash
git add knowledge_base/__init__.py knowledge_base/tariffs/.gitkeep
git commit -m "feat: scaffold knowledge_base package with tariffs/ directory"
```

---

## Task 7: Implement knowledge_base/ingest.py

**Files:**
- Create: `knowledge_base/ingest.py`

- [ ] **Step 1: Write ingest.py**

Create `knowledge_base/ingest.py` with exactly this content:

```python
"""Ingest seed PDFs from knowledge_base/tariffs/ into PageIndex.

Idempotent by SHA-256 content hash: skips unchanged PDFs, re-uploads edited ones.
Persists registry after every successful upload so partial progress is saved.
Continues past per-PDF failures; exits non-zero if any PDF failed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import TypedDict

import requests
from dotenv import load_dotenv

logger = logging.getLogger("ingest")

PAGEINDEX_UPLOAD_URL = "https://api.pageindex.ai/doc/"


class RegistryEntry(TypedDict):
    doc_id: str
    sha256: str


class PageIndexError(Exception):
    """Raised when the PageIndex upload returns a non-2xx or malformed response."""


def sha256_of(path: Path) -> str:
    """SHA-256 hex digest of the file bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_registry(path: Path) -> dict[str, RegistryEntry]:
    """Read the registry JSON or return {} if the file does not exist."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(path: Path, registry: dict[str, RegistryEntry]) -> None:
    """Atomically write the registry so a crash mid-save cannot corrupt it."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.replace(tmp, path)


def pageindex_upload(pdf_bytes: bytes, filename: str, api_key: str) -> str:
    """POST the PDF to PageIndex and return the doc_id.

    Raises PageIndexError on any non-2xx response or missing doc_id in body.
    """
    response = requests.post(
        PAGEINDEX_UPLOAD_URL,
        headers={"api_key": api_key},
        files={"file": (filename, pdf_bytes, "application/pdf")},
        timeout=120,
    )
    if not response.ok:
        raise PageIndexError(
            f"upload failed: HTTP {response.status_code} — {response.text[:200]}"
        )
    try:
        body = response.json()
    except ValueError as e:
        raise PageIndexError(f"upload response was not JSON: {e}") from e
    doc_id = body.get("doc_id")
    if not doc_id:
        raise PageIndexError(f"upload response missing doc_id: {body}")
    return doc_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upload PDFs from knowledge_base/tariffs/ to PageIndex.",
    )
    parser.add_argument(
        "--tariffs-dir",
        type=Path,
        default=Path("knowledge_base/tariffs"),
        help="Directory containing PDFs to ingest (default: %(default)s)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("knowledge_base/doc_registry.json"),
        help="Path to registry JSON (default: %(default)s)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable DEBUG logging."
    )
    args = parser.parse_args(argv)

    load_dotenv()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    api_key = os.getenv("PAGEINDEX_API_KEY")
    if not api_key:
        logger.error(
            "PAGEINDEX_API_KEY not set. Export it in your shell or add it to .env."
        )
        return 1

    if not args.tariffs_dir.is_dir():
        logger.error(
            "Tariffs directory does not exist: %s. Create it and drop PDFs in.",
            args.tariffs_dir,
        )
        return 1

    pdfs = sorted(args.tariffs_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning(
            "No PDFs found in %s — nothing to do.", args.tariffs_dir
        )
        return 0

    registry = load_registry(args.registry)
    uploaded, skipped = 0, 0
    failures: list[tuple[str, str]] = []

    for pdf in pdfs:
        filename = pdf.name
        sha = sha256_of(pdf)
        entry = registry.get(filename)
        if entry and entry.get("sha256") == sha:
            logger.info("%s: unchanged, skipped", filename)
            skipped += 1
            continue
        try:
            pdf_bytes = pdf.read_bytes()
            doc_id = pageindex_upload(pdf_bytes, filename, api_key)
            registry[filename] = {"doc_id": doc_id, "sha256": sha}
            save_registry(args.registry, registry)
            logger.info("%s: uploaded → %s", filename, doc_id)
            uploaded += 1
        except (PageIndexError, requests.RequestException) as e:
            logger.error("%s: %s", filename, e)
            failures.append((filename, str(e)))

    logger.info(
        "Summary: %d uploaded, %d skipped, %d failed",
        uploaded,
        skipped,
        len(failures),
    )
    if failures:
        for fn, err in failures:
            logger.error("FAILED: %s — %s", fn, err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Dry verification — help output**

```bash
uv run python -m knowledge_base.ingest --help
```
Expected: argparse help text listing `--tariffs-dir`, `--registry`, `--verbose`/`-v`. Exit 0.

- [ ] **Step 3: Dry verification — empty directory short-circuit**

(Directory is empty because PDFs haven't been dropped in yet.)
```bash
unset PAGEINDEX_API_KEY  # ensure the missing-key path is tested separately
uv run python -m knowledge_base.ingest
```
Expected: `ERROR ingest: PAGEINDEX_API_KEY not set...` and exit code 1.

Then, export a dummy key and re-run to test the empty-directory path:
```bash
PAGEINDEX_API_KEY=dummy uv run python -m knowledge_base.ingest
```
Expected: `WARNING ingest: No PDFs found in knowledge_base/tariffs — nothing to do.` and exit code 0.

- [ ] **Step 4: Commit**

```bash
git add knowledge_base/ingest.py
git commit -m "feat(ingest): add PageIndex PDF ingest script with hash-based idempotency"
```

---

## Task 8: User drops PDFs + run real ingest

**Files:**
- Dropped by user: `knowledge_base/tariffs/iata_tariff.pdf`, `incoterms_2020.pdf`, `surcharge_bulletin.pdf`
- Generated: `knowledge_base/doc_registry.json`

- [ ] **Step 1: Manual user action**

Tell the user:
> Move your three PDFs from `~/Desktop/` into `knowledge_base/tariffs/`:
> ```bash
> mv ~/Desktop/iata_tariff.pdf ~/Desktop/incoterms_2020.pdf ~/Desktop/surcharge_bulletin.pdf knowledge_base/tariffs/
> ```
> (Adjust filenames to match what you actually have on the Desktop. After the move, `ls knowledge_base/tariffs/` should list all three `.pdf` files.)

- [ ] **Step 2: Verify PDFs landed**

```bash
ls knowledge_base/tariffs/
```
Expected: three `.pdf` entries plus `.gitkeep`.

- [ ] **Step 3: Confirm the real API key is set**

```bash
test -n "$PAGEINDEX_API_KEY" && echo "key is set" || echo "KEY MISSING — export it or put in .env"
```
Expected: `key is set`. If not, either `export PAGEINDEX_API_KEY=pi-...` or ensure `.env` contains the real key (ingest will load it via `python-dotenv`).

- [ ] **Step 4: Run the ingest**

```bash
uv run python -m knowledge_base.ingest
```
Expected (exact filenames depend on what the user has; doc_ids are PageIndex-assigned):
```
INFO ingest: iata_tariff.pdf: uploaded → pi-xxxxxxxx
INFO ingest: incoterms_2020.pdf: uploaded → pi-yyyyyyyy
INFO ingest: surcharge_bulletin.pdf: uploaded → pi-zzzzzzzz
INFO ingest: Summary: 3 uploaded, 0 skipped, 0 failed
```
Exit code: 0.

- [ ] **Step 5: Inspect the registry**

```bash
cat knowledge_base/doc_registry.json
```
Expected: JSON with exactly three keys (one per PDF); each value is an object with both `doc_id` and `sha256` as non-empty strings.

- [ ] **Step 6: Confirm the registry is gitignored**

```bash
git status --short knowledge_base/
```
Expected: no entry for `doc_registry.json` (it is ignored). If it shows up, the `.gitignore` entry from Task 3 is not taking effect — revisit that task.

No commit on this task — `doc_registry.json` is gitignored by design and the only other state change (PDFs in `tariffs/`) is gitignored-by-subdirectory because they are per-user.

**Note:** PDFs themselves are not gitignored — only `doc_registry.json` is. If the user wants the PDFs committed so collaborators have the same corpus, add them explicitly: `git add knowledge_base/tariffs/*.pdf && git commit -m "feat: add seed PDFs"`. If the user wants them excluded, add `knowledge_base/tariffs/*.pdf` to `.gitignore`. Ask the user which they prefer before deciding.

---

## Task 9: Verify idempotency

**Files:** none modified — verification only.

- [ ] **Step 1: Re-run ingest**

```bash
uv run python -m knowledge_base.ingest
```
Expected:
```
INFO ingest: iata_tariff.pdf: unchanged, skipped
INFO ingest: incoterms_2020.pdf: unchanged, skipped
INFO ingest: surcharge_bulletin.pdf: unchanged, skipped
INFO ingest: Summary: 0 uploaded, 3 skipped, 0 failed
```
Exit code: 0. No network traffic to PageIndex (observable via the "skipped" lines — the upload function is never reached).

- [ ] **Step 2: Simulate a content change**

Touch one PDF's modification time AND modify its bytes slightly (mtime alone won't trigger — the hash is content-based, which is the whole point of D3 in the spec):
```bash
# Append a harmless trailing byte so the SHA changes but the PDF still opens
printf '\n' >> knowledge_base/tariffs/iata_tariff.pdf
```
(If the user is concerned about corrupting the PDF, they can skip this verification step — the idempotency logic is small enough to trust.)

- [ ] **Step 3: Re-run ingest**

```bash
uv run python -m knowledge_base.ingest
```
Expected: `iata_tariff.pdf: uploaded → pi-newid`, the other two `unchanged, skipped`, `Summary: 1 uploaded, 2 skipped, 0 failed`.

- [ ] **Step 4: Revert the PDF (optional)**

If Step 2 modified the PDF and the user wants the original back, they should restore from Desktop or a backup. Document this risk in the user-facing notes.

---

## Task 10: Update CLAUDE.md to reflect shipped state

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update Current state section**

Find:
```markdown
## Current state (2026-04-16)
Pre-scaffold: only PRD + CLAUDE.md exist. No `app.py`, `agents/`, `tools/`, `knowledge_base/`, or `tests/` on disk yet. Follow the **Build order** section when creating files — do not skip phases.
```

Replace with:
```markdown
## Current state (2026-04-17)
Phase 1 complete: repo is git-initialised, `uv` manages deps, `.env.example`/`.gitignore`/MCP config in place, and `knowledge_base/ingest.py` has uploaded the three seed PDFs to PageIndex. Phases 2–6 (scraper, agents, UI, tests, deploy) remain. Follow the **Build order** section.
```

- [x] **Step 2: Update MCP config heading** — *Already done by controller during Task 5 repair. The plan originally specified `.claude/settings.json` for MCP config, but authoritative Claude Code guidance confirms project-scoped `mcpServers` live in `.mcp.json` at project root (not `.claude/settings.json`). CLAUDE.md was updated to reflect this. SKIP this step.*

- [ ] **Step 3: Update Knowledge base files section for new registry schema**

Find:
```markdown
- `knowledge_base/doc_registry.json` — gitignored, rebuilt by ingest.py
```

Replace with:
```markdown
- `knowledge_base/doc_registry.json` — gitignored; maps `{filename: {doc_id, sha256}}`. Updated in place by `ingest.py` (idempotent by SHA-256 content hash — unchanged PDFs are skipped on re-run).
```

- [ ] **Step 4: Add the PageIndex env-var caveat**

Find (at the end of the PageIndex MCP section, after "Never fetch the whole document..."):
```markdown
**Never** fetch the whole document — always use tight page ranges from step 2.
```

Append immediately after (preserve the line above):
```markdown
**Never** fetch the whole document — always use tight page ranges from step 2.

**Env-var loading caveat:** Claude Code expands `${PAGEINDEX_API_KEY}` in the MCP config at CLI launch, reading from the shell environment — it does NOT auto-load from the project `.env`. Export the key in your shell (or use direnv / shell-rc integration) before starting a session. The `ingest.py` script has its own `load_dotenv()` and works standalone.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): update current state, registry schema, MCP env-var caveat for Phase 1"
```

---

## Task 11: Final Phase 1 acceptance check

**Files:** none modified — end-to-end verification.

- [ ] **Step 1: Fresh-clone simulation**

```bash
rm -rf .venv
uv sync
```
Expected: `.venv` is recreated from `uv.lock`; no errors.

- [ ] **Step 2: Idempotent run**

```bash
uv run python -m knowledge_base.ingest
```
Expected: all three PDFs report `unchanged, skipped` and exit 0.

- [ ] **Step 3: PageIndex MCP reachability (manual in a fresh Claude Code session)**

Tell the user:
> Start a fresh Claude Code session and verify that the PageIndex MCP tool `find_relevant_documents` appears in the available tool list (usually visible in the MCP status or when Claude attempts to call it). If it does not appear, check that `PAGEINDEX_API_KEY` is exported in the shell that launched Claude Code.

- [ ] **Step 4: Final commit log review**

```bash
git log --oneline
```
Expected: ~10 commits from Tasks 1–10, all with conventional-commit prefixes (`chore:`, `feat:`, `feat(ingest):`, `docs(claude):`).

---

## Self-review notes

Checked against the spec before finalising:

- **Spec §2 In scope** (primary + supporting): pyproject.toml (Task 2), .gitignore (Task 3), .env.example (Task 4), MCP block (Task 5), ingest.py (Task 7), `__init__.py` + `.gitkeep` (Task 6), README.md stub (Task 1) — all covered.
- **Spec §3 decisions** D1–D9 all implemented verbatim (uv, Python `>=3.11,<3.13`, hash idempotency, continue-on-error, minimal deps, registry schema, blank env, gitignored requirements.txt, committed uv.lock).
- **Spec §4 ingest control flow**: Task 7 implements all 7 control-flow steps in `main()`; error table rows 1–5 are all exercised in Step 3 verifications and the normal-path Task 8.
- **Spec §9 implementation sequence** (11 steps) maps to Tasks 1–10; Task 11 is the final acceptance check.
- **Spec §10 acceptance criteria** (6 items): `uv sync` clean (Task 11 Step 1); three-entry registry (Task 8 Step 5); re-run skip-all (Task 9 Step 1 / Task 11 Step 2); edit → partial re-upload (Task 9 Step 3); MCP reachable (Task 11 Step 3); CLAUDE.md updated (Task 10).
- **Spec §11 risks**: PageIndex endpoint shape resolved via WebFetch before plan was written (`POST /doc/`, multipart `file` field, `api_key` header, `{doc_id}` response) — reflected in Task 7 code. Git-init status resolved in Task 1.
- **Type consistency**: `RegistryEntry` TypedDict used consistently; `pageindex_upload` signature stable across code and documentation; all paths defaulted to the same `knowledge_base/` locations.
- **Placeholder scan**: no TBDs, TODOs, "similar to Task N", or "add appropriate error handling" patterns — all error handling is shown concretely.
