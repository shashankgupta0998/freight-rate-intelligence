# Phase 6 — Deploy to Streamlit Cloud: Design

**Date:** 2026-04-24
**Author:** Shashank Gupta (with Claude)
**Status:** Approved for implementation planning
**Related:** `CLAUDE.md` (Build order §Phase 6, §Common commands, §Environment variables), prior phase specs 2026-04-17 (P1), 2026-04-18 (P2/P3), 2026-04-20 (P4 UI), 2026-04-22 (P5 tests)

---

## 1. Purpose

Ship the live demo. Make the Phase-1-through-5 stack publicly reachable at a Streamlit Cloud URL. Resolve the one Phase-1 .gitignore inconsistency that blocked Cloud (gitignored `requirements.txt`). Document the redeploy workflow so future dep changes ship in one commit + push.

Portfolio story: a complete AI-powered freight-rate-intelligence app, end-to-end from form input to AI recommendation, runnable from any browser.

## 2. Scope

### In scope

| Deliverable | Type | Notes |
|-------------|------|-------|
| `.gitignore` — remove `requirements.txt` line | Code change | 1-line diff; comment block kept as a "why isn't this ignored?" breadcrumb |
| `requirements.txt` — generated from `uv.lock` | Generated, committed | `uv export --no-hashes --no-emit-project --output-file requirements.txt`; ~30 production-only deps at exact `==X.Y.Z` versions |
| Streamlit Cloud app creation | Manual (user) | Dashboard: New app → connect GitHub → `main` branch → `app.py` |
| Streamlit Cloud secrets | Manual (user) | Dashboard → Settings → Secrets: 4 API keys + 3 flags |
| Live smoke check | Manual (user + Claude) | 10-item checklist (see §4.1) |
| `CLAUDE.md` — update Current state + redeploy note | Code change | ~5–8 lines |

**Total new code:** ~1 line `.gitignore` diff + ~30-line generated `requirements.txt` + ~8 lines `CLAUDE.md`.

### Out of scope

- GitHub Actions / CI workflows — Streamlit Cloud auto-redeploys on `main` push (effectively our CI).
- Custom domain — default `*.streamlit.app` subdomain is sufficient for a portfolio demo.
- Sentry / log piping / error monitoring — Streamlit Cloud's built-in logs view is enough for v1.
- Resource scaling / performance tuning — free tier covers the demo load.
- Per-PR deploy previews — single `main` branch only.

### Decisions locked from Q1–Q2

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **`requirements.txt` un-gitignored, exported from `uv.lock`, committed.** Pre-deploy step: `uv export --no-hashes --no-emit-project --output-file requirements.txt`. | Streamlit Cloud reads `requirements.txt` from the repo. `uv.lock` remains source of truth; `requirements.txt` is derived state. Deterministic deploys (lockfile pins carry forward). |
| D2 | **Python version: Streamlit Cloud default (3.12 as of 2025).** No `.python-version` file. | `pyproject.toml`'s `requires-python = ">=3.11,<3.13"` is the source of truth and will fail-loud if Streamlit Cloud drifts to 3.13. `uv.lock` was built on 3.12.13; the exported `requirements.txt` resolves cleanly under 3.12.x. |
| D3 | **Secrets: Streamlit Cloud dashboard only.** Four API keys + three flags as Streamlit secrets. | Dashboard injects to `os.environ` at process start. Code already reads via `os.getenv` (with `python-dotenv` for local dev only — `.env` won't exist on Cloud, `load_dotenv()` is a no-op). Zero code changes needed. |
| D4 | **App subdomain: Streamlit Cloud default** (typically `freightiq-<hash>.streamlit.app`). | Renameable later via dashboard. No DNS / TLS work. |
| D5 | **Smoke check: manual click-through** of all three sidebar example chips on the live URL. | Matches our Phase-3 E2E manual baseline; no automated headless browser tooling needed for v1. |
| D6 | **`USE_PAGEINDEX_RUNTIME` starts `false` on the public demo.** | Faster, deterministic, no external runtime dependency on PageIndex availability. Can flip to `true` via dashboard later if you want the RAG-on-runtime story to be live. |

## 3. Pre-deploy code changes

Single commit. Two files.

### 3.1 `.gitignore` edit

Replace the existing two-line block:
```
# Streamlit Cloud export (regenerated from uv.lock; not source of truth)
requirements.txt
```

With (just the comment, no ignore line):
```
# requirements.txt is committed (Streamlit Cloud needs it in the repo).
# It's derived from uv.lock via `uv export --no-hashes --no-emit-project`
# — re-export and commit when deps change.
```

### 3.2 Generate `requirements.txt`

Single command from project root:
```bash
uv export --no-hashes --no-emit-project --output-file requirements.txt
```

Flags:
- `--no-hashes` — Streamlit Cloud's pip rejects sdist hashes pinned by `uv` for some packages; safer without.
- `--no-emit-project` — exclude the project itself (`freight-rate-intelligence==0.1.0`); Cloud doesn't `pip install .`.
- `--output-file requirements.txt` — atomic write.

Expected output: ~30 lines of production deps + transitives at exact `==X.Y.Z` versions matching `uv.lock`. Includes `streamlit`, `langchain`, `langchain-litellm`, `litellm`, `pydantic`, `requests`, `python-dotenv`, `beautifulsoup4`, `lxml`, etc. Does NOT include `pytest` or `pytest-cov` (dev deps).

### 3.3 Single combined commit

```bash
git add .gitignore requirements.txt
git commit -m "feat(deploy): un-gitignore requirements.txt + commit uv-exported lockfile"
git push origin main
```

### What we're NOT touching

- `pyproject.toml` — `requires-python` already correctly bounded.
- `.streamlit/config.toml` — Phase 4's `headless = true` + `gatherUsageStats = false` + dark theme port to Cloud unchanged.
- `app.py` — `python-dotenv.load_dotenv()` is a no-op on Cloud (no `.env`); `os.getenv()` works because Cloud sets the env var.
- Any agent / pipeline / tool code.

## 4. Streamlit Cloud configuration (manual)

Purely dashboard clicks. Documented as exact steps:

### 4.1 Create the app

1. Sign in at **https://share.streamlit.io** (GitHub account that owns `shashankgupta0998/freight-rate-intelligence`).
2. **New app** → **From existing repo**.
3. Repository: `shashankgupta0998/freight-rate-intelligence`. Branch: `main`. Main file path: `app.py`.
4. App URL: leave default suggestion. Click **Deploy**.

First build: ~2–4 minutes (pip install of `lxml`, `litellm`, `streamlit`, `langchain` stack).

### 4.2 Add secrets

After first build, the app will fail to run pipeline (no `GROQ_API_KEY`). Fix:

1. **⋮ → Settings → Secrets**.
2. Paste (real values from your `.env`):
   ```toml
   GROQ_API_KEY = "gsk_..."
   OPENAI_API_KEY = "sk-proj-..."
   GEMINI_API_KEY = "AIza..."
   PAGEINDEX_API_KEY = "..."
   LIVE_SCRAPING = "false"
   USE_PAGEINDEX_RUNTIME = "false"
   LOG_LEVEL = "INFO"
   ```
3. **Save**. Streamlit Cloud restarts (~30 s).

## 5. Live smoke checklist (10 items)

Run on the deployed URL once secrets are saved.

| # | Check | Expected |
|---|-------|----------|
| 1 | Landing page loads | Dark theme, FreightIQ brand, sidebar + form visible; no stack trace |
| 2 | Weight strip auto-updates | Edit gross weight or any dimension → chargeable weight recomputes in <300 ms |
| 3 | "Delhi → Rotterdam · 200 kg" chip populates form | Cargo=electronics, Origin=Delhi, Destination=Rotterdam, weights filled |
| 4 | "Run rate intelligence →" triggers pipeline | 5-step `st.status` ticker visible; no exception |
| 5 | 10 ranked rate cards render | Trust badge + 4-col metric grid + Book/Caution button per trust band |
| 6 | AI Recommendation panel above cards | Non-empty green-tinted text |
| 7 | "How this was calculated" expander | Shows formulas + N LLM calls |
| 8 | Second run of same route hits cache | Streamlit Cloud logs show `INFO cache: HIT Delhi→Rotterdam ...` |
| 9 | "Mumbai → New York · 50 kg" chip → mode = courier | Router rules fire (<68 kg); cards show `courier` mode pills |
| 10 | "Shanghai → Dubai · 800 kg" chip → mode = sea_freight | Router rules fire (≥500 kg); cards show `sea_freight` mode pills |

If any ❌: open the Streamlit Cloud **Logs** tab. Most likely failure is missing/typo'd secret.

## 6. CLAUDE.md update

After smoke checklist passes, single commit:

### 6.1 Current state extension

Append to the existing Phase-5 Current state block:
```
**Phase 6 complete (2026-04-24):** Live at `<live-app-url>`. Streamlit Cloud auto-redeploys on `main` push.
```

### 6.2 Redeploy command in Common commands

Append to the existing Common-commands block:
```bash
# Redeploy to Streamlit Cloud after dep changes
uv export --no-hashes --no-emit-project --output-file requirements.txt
git commit -am "chore(deploy): refresh requirements.txt"
git push origin main   # Streamlit Cloud auto-redeploys ~3 min
```

## 7. Implementation sequence

```
 1. .gitignore: drop the `requirements.txt` line; keep the comment as a breadcrumb
 2. uv export --no-hashes --no-emit-project --output-file requirements.txt
 3. Verify exported file: no pytest*, no project itself; ~30 deps at == versions
 4. git add .gitignore requirements.txt && git commit && git push origin main
 5. (User) Streamlit Cloud → New app → connect repo + main + app.py
 6. (User) Settings → Secrets: paste 4 API keys + 3 flags
 7. (User) Wait ~3 min for first build
 8. (User + Claude) Live smoke checklist (§5) — 10 items
 9. CLAUDE.md: update Current state + add redeploy command
10. git commit + push CLAUDE.md
```

## 8. Acceptance criteria

- `.gitignore` no longer excludes `requirements.txt`; commented breadcrumb preserved.
- `requirements.txt` committed to `main` with exact `==` versions; no `pytest*` entries; no `freight-rate-intelligence==0.1.0` self-reference.
- Streamlit Cloud build completes successfully (green status in dashboard).
- All 10 smoke items pass on the live URL.
- `CLAUDE.md` Current state shows Phase 6 complete with the live URL.
- `CLAUDE.md` Common commands documents the redeploy workflow.

## 9. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| `requirements.txt` export accidentally pulls dev deps | `--no-emit-project` + `uv export` defaults skip dev groups; manual scan of exported file before commit (§7 step 3) |
| `lxml` wheel fails on Streamlit Cloud's container | Streamlit Cloud's Debian-based image has `libxml2-dev` preinstalled — typically no issue. Fallback: switch BeautifulSoup parser to `"html.parser"` in `tools/scraper.py` (documented in Phase 2 §10 risk row) |
| `litellm` + `langchain-litellm` resolution takes >5 min on first build | Acceptable for first deploy; subsequent redeploys hit cached layers. If still slow, no action — first-run latency only |
| Streamlit Cloud doesn't inject secrets correctly | Documented behaviour as of 2025: secrets land in `os.environ` before app process starts. If it misbehaves, our code path already uses `python-dotenv` as secondary (no-op on Cloud, harmless) |
| First-load `KeyError: GROQ_API_KEY` because secrets aren't set yet | Expected; user enters secrets and waits for restart. Documented in §4.2 |
| Live app accidentally runs `LIVE_SCRAPING=true` | Default-false in code, default-false in secrets template, no code path that sets it true. Triple-locked. |
| User puts wrong API key in secrets | Pipeline fails with provider error in logs; user updates secret; ~30 s restart; retry |

## 10. Phase-6 follow-ups (non-blocking)

- **Custom subdomain** rename via Streamlit Cloud dashboard (e.g., `freightiq-demo.streamlit.app`) — pure UX polish, no code work.
- **GitHub Actions CI** — `uv sync --dev && uv run pytest --cov-fail-under=80` on PRs. Captured in Phase-5 backlog.
- **Flip `USE_PAGEINDEX_RUNTIME=true` on Cloud** as a "RAG-at-runtime" portfolio narrative once the simpler path is verified. One dashboard secret edit, no redeploy.
- **Streaming summarizer output** (Phase-4 backlog item from CLAUDE.md). Could land as a Phase 6.5 polish if you want a more dynamic feel for live demos.

## 11. Non-goals for Phase 6

- No code changes beyond `.gitignore` + `requirements.txt` regen + `CLAUDE.md` update.
- No new tests (Phase 5 already locks behaviour).
- No CI workflow.
- No load testing or scaling tuning.
- No PR-preview deploys.
- No Sentry / observability beyond Streamlit Cloud's default logs.
