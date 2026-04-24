# Freight Rate Intelligence Tool
**Author:** Shashank Gupta | **Stack:** Python, Streamlit, LangChain, Groq, PageIndex MCP

---

## Project purpose
AI-powered web app: given product + gross weight + dimensions + origin + destination, find the cheapest verified freight route, flag hidden charges, and recommend a booking site. Target user: small business owners with no freight expertise.

---

## Current state (2026-04-24)
Phase 6 complete: **Live at https://freightit.streamlit.app/**. Streamlit Cloud auto-redeploys on `main` push.

Phase 5: **96 pytest tests across 10 test files** lock every phase's behaviour in. Coverage: `agents/` **100%** (all 4 agents + `__init__`), `pipeline.py` **100%**, `tools/cache.py` **94%**, `tools/validator.py` **94%**, `tools/pageindex_client.py` **97%**, `tools/scraper.py` **92%**, `tools/llm_router.py` **100%** — **96% aggregate** on the CLAUDE.md-mandated scope, every module >80% target. Shared `tests/conftest.py` exposes `FakeChatModel` (inherits LangChain `Runnable` so `_PROMPT | fake` composes natively) + `install_fake_llm` fixture; zero network I/O during the 2.25 s suite. CLAUDE.md-mandated smoke test `(electronics, 12 kg, 40×30×20 cm, Delhi, Rotterdam)` passes end-to-end against mocked LLMs with assertions on `ScoredRate` schema, mode, sort order, and cache-hit behaviour. All 6 phases green.

**Phase 2 + 3 notes:**
- `LIVE_SCRAPING=false` is both default and production in v1. `LIVE_SCRAPING=true` raises `NotImplementedError` from `tools.scraper.fetch_site`.
- `USE_PAGEINDEX_RUNTIME=false` is the default; set to `true` to let the hidden-charge agent fetch surcharge-bulletin context from PageIndex's `/chat/completions` endpoint for each rate. `charge_patterns.json` is always the primary data source; PageIndex is additive context only.
- Cache key is `(origin, destination, query_date)` per CLAUDE.md — known to be too coarse (ignores weight + mode); acceptable for single-route demo, tighten to `(origin, destination, date, mode, weight_bucket)` when multi-route support lands.
- Pipeline makes ~12 LLM calls per request (1 router + N hidden-charge + 1 summarizer, where N = scraped rate count). Worst-case ~6 s serial latency. Phase 5 optimisations: parallelise or batch hidden-charge.

**Phase 5 backlog (non-blocking, surfaced by reviewers):**
> **Status note (2026-04-22):** the Phase 5 test suite LOCKS current behaviour in. Items below describe bugs/polish to fix in a future "Phase 5.5 polish" commit — tests will need updating alongside each fix.

- `tools/cache.py`: `clear_cache` has a redundant `_connect().close()` line that leaks on a failing reconnect — drop it; table is recreated lazily on next call.
- `tools/cache.py`: error logs for unparseable `cached_at` / `rates_json` should include origin/destination in the `%s->%s` format used elsewhere.
- `tools/scraper.py`: `_parse_days_from_text` reuses `_PRICE_RE` but doesn't strip commas; `"2,000 days"` raises `ValueError` (silently drops the row via the per-parser except). Use a dedicated `r"\d+"` or strip commas.
- `tools/scraper.py`: `Query.origin` / `destination` / `mode` are unused in v1 (reserved for live mode) — document with a one-line note or defer trimming until live mode is wired.
- `pipeline.py`: hidden-charge LLM calls are serial (~0.5s × N rates). Parallelise via `ThreadPoolExecutor` or batch all N cards into one LLM call for ~3× latency reduction.
- `agents/rate_comparator.py`: no LLM call; the `Runnable` wrapper is pure A2A ceremony. If A2A never ships, collapse to a plain function.
- `agents/summarizer.py`: `payload["shipment"]` is an unguarded `[]` access while `router_reason` / `ranked_rates` use `.get(default)` — inconsistent. Either make all three defaults-based or raise a typed error.
- `agents/summarizer.py`: no length guard on `recommendation`; a 10KB LLM response is schema-valid but blows up the Streamlit card. Consider `Field(max_length=2000)` or log a warning over N chars.
- `agents/summarizer.py`: empty-string `recommendation` silently accepted; use `Field(min_length=1)` or fall back to canned message.
- `agents/summarizer.py`: output isn't streamed; Phase 4 Streamlit can add streaming if UX demands.
- `agents/summarizer.py`: optional `query_pageindex(incoterms_doc_id, ...)` call for Incoterms-aware advice — hook exists in design, not wired.

> **Source of truth:** where CLAUDE.md and `freight-rate-intelligence-PRD.md` diverge, CLAUDE.md wins. Notably, the LLM fallback chain (Groq → OpenAI → Gemini) supersedes the PRD's Groq-only spec.

---

## Directory layout (planned)

```
freight-rate-intelligence/
├── app.py                  # Streamlit entry
├── .env.example            # env-var template (create in Phase 1)
├── pyproject.toml          # deps + Python 3.11+ pin; managed by uv
├── uv.lock                 # committed lockfile
├── requirements.txt        # generated for Streamlit Cloud (via `uv export`)
├── agents/                 # router, rate_comparator, hidden_charge, summarizer
├── tools/                  # llm_router, scraper, cache, validator
├── knowledge_base/         # ingest.py, charge_patterns.json, tariffs/*.pdf
└── tests/                  # fixtures/, test_agents, test_rag, test_smoke
```

---

## Common commands

```bash
# Python 3.11+ (pinned in pyproject.toml; LangChain + Playwright compatibility)
# Package manager: uv (https://docs.astral.sh/uv/) — one-time: `brew install uv` or `pip install uv`

# First-time setup (uv auto-creates .venv from pyproject.toml + uv.lock)
uv sync
cp .env.example .env                        # .env.example to be created in Phase 1
uv run playwright install chromium          # one-time, for JS-heavy scraping

# Ingest knowledge base PDFs (idempotent by SHA-256; updates doc_registry.json)
uv run python -m knowledge_base.ingest

# Run the app
uv run streamlit run app.py

# Tests
uv run pytest                                             # full suite
uv run pytest tests/test_agents.py                        # one file
uv run pytest tests/test_smoke.py::test_delhi_rotterdam   # one test
uv run pytest --cov=agents --cov=tools --cov-report=term-missing   # coverage

# Lint / format / typecheck
uv run ruff check . && uv run ruff format --check .
uv run mypy agents tools

# Redeploy to Streamlit Cloud after dep changes
uv export --no-hashes --no-emit-project --no-dev --output-file requirements.txt
git commit -am "chore(deploy): refresh requirements.txt"
git push origin main   # Streamlit Cloud auto-redeploys ~3 min
```

---

## Stack
- **LLM:** LiteLLM fallback chain — Groq (`llama-3.3-70b-versatile`) → OpenAI (`gpt-4o-mini`) → Gemini (`gemini-1.5-flash`)
- **LLM router:** `tools/llm_router.py` — all agents call `get_llm()`, never instantiate `ChatGroq` directly
- **Orchestration:** LangChain 1.x `Runnable`-based agents (AgentExecutor was removed in v1.x — `Runnable` is the equivalent agent-object interface, same `.invoke(input) -> output` protocol)
- **RAG:** PageIndex MCP — vectorless, reasoning-based (no ChromaDB, no embeddings)
- **Scraping:** BeautifulSoup + requests; Playwright for JS-heavy pages
- **Cache:** SQLite — rate cache TTL 6h, keyed by `(origin, destination, date)`
- **Frontend:** Streamlit
- **Deploy:** Streamlit Cloud (export `requirements.txt` via `uv export --no-hashes` before deploying)
- **Package manager:** `uv` (pyproject.toml + uv.lock, Python 3.11+)
- **Tests:** pytest + unittest.mock

---

## Critical formulas — never change without explicit instruction

```python
# Chargeable weight (runs before any agent call)
volume_weight_kg    = (length_cm * width_cm * height_cm) / 5000  # IATA divisor
chargeable_weight_kg = max(gross_weight_kg, volume_weight_kg)
weight_basis         = "volume" if volume_weight_kg > gross_weight_kg else "gross"

# Sea freight CBM (display only)
cbm = (length_cm * width_cm * height_cm) / 1_000_000
```

---

## Data contracts — all agents must conform exactly

### ShipmentInput
```python
{
  "product": str,
  "gross_weight_kg": float,
  "length_cm": float, "width_cm": float, "height_cm": float,
  "volume_weight_kg": float,      # computed: L*W*H / 5000
  "chargeable_weight_kg": float,  # computed: max(gross, volume)
  "weight_basis": str,            # "gross" | "volume"
  "origin": str,
  "destination": str,
  "urgency": str                  # "standard" | "express"
}
```

### ScrapedRate
```python
{
  "carrier": str,
  "base_price_usd": float,
  "chargeable_weight_kg": float,
  "transit_days": int,
  "booking_url": str,
  "source_site": str,
  "scraped_at": str,   # ISO 8601
  "mode": str          # "air_freight" | "sea_freight" | "courier" | "road_freight"
}
```

### ScoredRate (extends ScrapedRate)
```python
{
  **ScrapedRate,
  "trust_score": int,        # 0–100
  "flags": list[str],        # plain-English warnings
  "estimated_total_usd": float,
  "verified_site": bool
}
```

---

## Agent roster

| Agent | File | Input | Output |
|-------|------|-------|--------|
| Router | `agents/router.py` | ShipmentInput | `{mode, reason}` |
| Rate comparator | `agents/rate_comparator.py` | `list[ScoredRate]` | ranked `list[ScoredRate]` |
| Hidden charge detector | `agents/hidden_charge.py` | ScrapedRate + PageIndex pages from `surcharge_bulletin.pdf` | `{trust_score, flags}` |
| Summarizer | `agents/summarizer.py` | ranked list + flags | recommendation str |

- All agents call `get_llm()` from `tools/llm_router.py` — never instantiate `ChatGroq` directly
- Fallback order on `RateLimitError`: see Stack.
- All agents receive `chargeable_weight_kg`, never `gross_weight_kg`
- Router mode thresholds (chargeable weight): <68kg → courier; <500kg → air; ≥500kg → sea

**Data flow:** Router (mode) → Scraper (rates) → Hidden-charge (trust_score, flags) → Rate-comparator (ranked) → Summarizer (recommendation)

---

## PageIndex MCP — RAG retrieval

**MCP config** (lives in `.mcp.json` at the project root, added in Phase 1 — `.claude/settings.json` does NOT accept `mcpServers`; per-project MCP servers always go in `.mcp.json`):
```json
{
  "mcpServers": {
    "pageindex": {
      "type": "http",
      "url": "https://api.pageindex.ai/mcp",
      "headers": { "Authorization": "Bearer ${PAGEINDEX_API_KEY}" }
    }
  }
}
```

**Ingest** (see Common commands for the invocation):
- Uploads PDFs from `knowledge_base/tariffs/` to PageIndex API
- Saves `{filename: doc_id}` in `knowledge_base/doc_registry.json`

**Agent retrieval sequence** (always 3 steps):
1. `find_relevant_documents(query)` → identify doc
2. `get_document_structure(docName)` → get TOC with page ranges
3. `get_page_content(docName, pages="X-Y")` → fetch only relevant pages

**Document assignments:**
- Hidden charge agent → `surcharge_bulletin.pdf`
- Summarizer → `incoterms_2020.pdf`
- Rate comparator → `iata_tariff.pdf`

**Never** fetch the whole document — always use tight page ranges from step 2.

**Env-var loading caveat:** Claude Code expands `${PAGEINDEX_API_KEY}` in the MCP config at CLI launch, reading from the shell environment — it does NOT auto-load from the project `.env`. Export the key in your shell (or use direnv / shell-rc integration) before starting a session. The `ingest.py` script has its own `load_dotenv()` and works standalone.

---

## Knowledge base files

- `knowledge_base/tariffs/` — seed PDFs (IATA tariff, Incoterms 2020, surcharge bulletins)
- `knowledge_base/doc_registry.json` — gitignored; maps `{filename: {doc_id, sha256}}`. Updated in place by `ingest.py` (idempotent by SHA-256 content hash — unchanged PDFs are skipped on re-run; edited PDFs re-upload)
- `knowledge_base/charge_patterns.json` — direct JSON load (NOT in PageIndex), structure:
```json
{
  "red_flags": ["PSS not shown upfront", "DHC not itemised", "chassis fee unlisted", ...],
  "verified_sites": ["freightos.com", "flexport.com", "dhl.com"],
  "flagged_sites": []
}
```

---

## Environment variables

```
GROQ_API_KEY=          # Primary LLM
OPENAI_API_KEY=        # Fallback 1
GEMINI_API_KEY=        # Fallback 2
PAGEINDEX_API_KEY=     # Required
LIVE_SCRAPING=false    # true only in production
LOG_LEVEL=INFO
```

**Streamlit Cloud secrets:** add all four API keys (`GROQ_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `PAGEINDEX_API_KEY`) under Settings → Secrets.

**Loading:** `python-dotenv` (`load_dotenv()` at app start) in local dev; Streamlit Cloud injects these automatically from Settings → Secrets — no dotenv call needed in prod.

---

## Scraper rules
- `LIVE_SCRAPING=false` during all development — use fixtures in `tests/fixtures/`
- Cache key: `(origin, destination, date)` — TTL 6 hours
- Scraper failure = fall back to PageIndex tariff estimate + add disclaimer to UI
- Never hardcode rate site URLs — keep in config dict in `tools/scraper.py`

---

## Trust score bands
- 80–100 → Verified ✓ (green)
- 50–79  → Caution ⚠ (amber)
- 0–49   → High risk ✗ (red)
- Sites in `flagged_sites` → auto-score 0, never show booking link

---

## Streamlit UI requirements
- Weight display (always visible before results):
  ```
  Gross: 12.0 kg | Volume: 18.4 kg | Chargeable: 18.4 kg ✦ volume applies
  ```
- Result cards: 3-column (carrier/mode | estimated total | transit days)
- `st.expander("How this was calculated")` → agent reasoning chain
- `st.link_button("Book now →", url)` — only shown for trust_score ≥ 50

---

## Testing requirements
- ≥ 80% coverage on `agents/` and `tools/`
- Every agent tested with mocked `get_llm()` responses (provider-agnostic — covers the full Groq → OpenAI → Gemini fallback chain); assert on output schema, not LLM text
- `tests/test_rag.py` — mock PageIndex MCP tool responses, assert correct page ranges requested
- `tests/test_smoke.py` — fixed query `(electronics, 12kg, 40×30×20cm, Delhi, Rotterdam)` must complete end-to-end

---

## Prohibited patterns
- No bare `except:` — always catch specific exceptions
- No `print()` for debugging — use `logging`
- No hardcoded API keys anywhere in code
- Never instantiate `ChatGroq`, `ChatOpenAI`, or `ChatGoogleGenerativeAI` directly in agents — always use `get_llm()` from `tools/llm_router.py`
- Never pass `gross_weight_kg` to agents — always `chargeable_weight_kg`
- Never fetch full PageIndex documents — tight page ranges only
- Never commit `doc_registry.json`, `.env`, or `__pycache__`

---

## Claude Code slash commands (planned — not yet created)
Files under `.claude/commands/` do not exist yet. Create them during Phase 1 scaffolding.
- `/fix-tests` — run pytest, fix failures one by one
- `/validate-schema` — check all agents return correct ScoredRate schema
- `/run-smoke` — run the fixed Delhi→Rotterdam smoke test end-to-end

---

## Build order (do not skip phases)
1. **Phase 1 — Scaffold + RAG ingest**
   - `.gitignore` (covers `.env`, `doc_registry.json`, `__pycache__`, `.venv/`, `*.db`; `uv.lock` IS committed)
   - `.env.example`
   - `pyproject.toml` (Python 3.11+, deps) + `uv.lock`
   - `.mcp.json` at project root with `mcpServers` block
   - `knowledge_base/ingest.py` + upload PDFs
2. `tools/scraper.py` + `tools/cache.py` with fixtures
3. All 4 agents + LangChain wiring
4. `app.py` Streamlit UI
5. Tests (unit → integration → smoke)
6. Deploy to Streamlit Cloud

---

## Installed plugins (Claude Code)

**Enabled in this repo** (`.claude/settings.json`):
- `claude-md-management@claude-plugins-official` — CLAUDE.md audit/improver workflow
- `superpowers@superpowers-marketplace` — brainstorm → plan → TDD workflow
- `claude-mem@thedotmack` — session memory across restarts
- `frontend-design@claude-plugins-official` + `frontend-design@claude-code-plugins` — Streamlit UI quality
- `code-review@claude-code-plugins` — PR review
- `security-guidance@claude-code-plugins` — real-time security hook

**User-level skills** (at `~/.claude/skills/`, not a plugin):
- `gstack` — plan-review, code-review, ship, QA slash commands
