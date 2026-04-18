# Product Requirements Document
## Freight Rate Intelligence Tool

**Version:** 1.0  
**Author:** Shashank Gupta  
**Date:** April 2026  
**Status:** Draft

---

## 1. Problem Statement

Small business owners shipping freight internationally face two consistent pain points:

1. **Rate opacity** — quoted prices rarely reflect the final invoice. Hidden surcharges (fuel, peak season, destination handling, chassis fees) routinely add 30–80% to the base rate.
2. **Decision paralysis** — comparing rates across Freightos, iContainers, Flexport, and carrier sites is time-consuming, requires domain knowledge, and yields inconsistent data formats.

There is no free tool that aggregates rates, flags hidden charges, and recommends a verified booking site in a single workflow.

---

## 2. Goal

Build an AI-powered web app that takes a shipment spec (product, weight, origin, destination) and returns:

- The cheapest **verified** route with total landed cost estimate
- A ranked list of alternatives with trust scores
- Plain-language warnings for sites/quotes with hidden charge patterns
- A direct booking link to a legitimate forwarder

---

## 3. Target User

**Primary:** Small business owner (1–20 employees) shipping internationally, 1–20 shipments/month. No freight broker. Makes booking decisions personally. Budget-sensitive, time-poor, low freight domain knowledge.

**Secondary:** Freelance importers, e-commerce sellers, portfolio reviewers / technical interviewers evaluating the project.

---

## 4. User Journey

```
User enters: product type, gross weight (kg), dimensions (L × W × H in cm), origin city, destination city
         ↓
System calculates volume weight and determines chargeable weight
         ↓
System classifies shipment mode (air / sea / courier / road)
         ↓
System scrapes live rates from 3–4 freight aggregator sites
         ↓
Hidden charge agent scans each quote against known surcharge patterns
         ↓
Each quote gets a trust score (0–100) and a flags list
         ↓
Summarizer ranks results by estimated total cost (base + likely surcharges)
         ↓
User sees: ranked route cards + warnings + recommended booking link
         ↓
User clicks "Book now →" → redirected to verified forwarder site
```

---

## 5. Core Features

### F1 — Shipment Input Form
- Fields: product name/type, gross weight (kg), length × width × height (cm), origin (city or port), destination (city or port)
- Optional: urgency (standard / express), shipment value (for customs estimation)
- Validation: gross weight > 0, all dimensions > 0, origin ≠ destination, recognisable city/port names
- UI: dimensions as three side-by-side number inputs (L / W / H) with a "cm" label

### F1.5 — Chargeable Weight Calculator
Runs immediately on form submit, before any agent call.

**Volume weight formula (industry standard):**
```
volume_weight_kg = (length_cm × width_cm × height_cm) / 5000
```
The divisor 5000 is the standard for air freight and most couriers (IATA).  
Sea freight uses CBM (cubic metres) instead — show both.

**Chargeable weight:**
```
chargeable_weight_kg = max(gross_weight_kg, volume_weight_kg)
```

**UI display** (shown before results, always visible):
```
Gross weight:    12.0 kg
Volume weight:   18.4 kg  ← L×W×H / 5000
Chargeable weight: 18.4 kg  ✦ volume weight applies
```
If gross > volume: show "actual weight applies"  
If volume > gross: show "volume weight applies — your shipment is light but bulky"  
If equal: show "weights match"

All downstream agents receive `chargeable_weight_kg`, not gross weight.

### F2 — Shipment Mode Classifier (Agent)
- Classify into: `air_freight`, `sea_freight`, `courier`, `road_freight`
- Rules based on **chargeable weight**: <68kg → courier candidate; <500kg → air candidate; >500kg → sea preferred
- Output: recommended mode + brief reason (1 sentence)
- Powered by: LiteLLM fallback chain — Groq (`llama-3.3-70b-versatile`) → OpenAI (`gpt-4o-mini`) → Gemini (`gemini-1.5-flash`), orchestrated by LangChain. All agents call `get_llm()` from `tools/llm_router.py`; providers swap automatically on `RateLimitError`.

### F3 — Live Rate Scraper
- Sources: Freightos, iContainers, SeaRates (BeautifulSoup + requests)
- JS-rendered fallback: Playwright headless for SPA pages
- Output per quote: `{carrier, base_price_usd, transit_days, booking_url, source_site, scraped_at}`
- Cache: SQLite keyed by `(origin, destination, date)` — TTL 6 hours
- Failure mode: if scraping fails, fall back to RAG-retrieved tariff estimates with a clear disclaimer

### F4 — Hidden Charge Detection (Agent)
- Cross-reference each quote against `charge_patterns.json` (curated surcharge rules)
- Patterns include: PSS (peak season surcharge), DHC (destination handling), chassis fee, documentation fee > $75, fuel surcharge not itemised upfront
- Output per quote: `trust_score` (0–100), `flags` (list of plain-English warnings)
- Trust score bands: 80–100 = Verified ✓, 50–79 = Caution ⚠, 0–49 = High risk ✗
- `flagged_sites` list in config: sites with known deceptive practices are auto-scored 0

### F5 — RAG Knowledge Base (PageIndex MCP)
- Documents: IATA tariff tables, Incoterms 2020 guide, carrier surcharge bulletins (PDFs)
- Strategy: vectorless reasoning-based RAG via PageIndex MCP — no embeddings, no ChromaDB, no chunking
- PageIndex builds a hierarchical tree index on their cloud servers from uploaded PDFs
- Ingest: `knowledge_base/ingest.py` uploads PDFs once, saves `{filename: doc_id}` in `doc_registry.json`
- Retrieval: agents call 3 MCP tools in sequence:
  1. `find_relevant_documents(query)` → identifies which doc is relevant
  2. `get_document_structure(docName)` → returns hierarchical TOC with page ranges
  3. `get_page_content(docName, pages="8-11")` → fetches only the relevant pages
- Used by: hidden charge agent (surcharge bulletins), summarizer (Incoterms), rate comparator (tariff tables)
- MCP config in `.mcp.json` at project root (checked into git; shared with team) — used by Claude Code dev sessions; the Streamlit app uses PageIndex's Python SDK / HTTP directly, not the MCP protocol

### F6 — Rate Comparison & Recommendation (Agent)
- Rank quotes by: estimated total cost = base_price + expected_surcharges (derived from trust_score)
- Output: ordered list of route cards, top recommendation highlighted
- Each card: carrier, mode, base price, transit days, trust score badge, flags, booking link

### F7 — Streamlit UI
- Single-page app: input form → results
- Result cards: 3-column layout (carrier/mode | total cost | transit days)
- Trust badge: colour-coded (green / amber / red)
- Warning callout: plain-English flag list per quote
- Reasoning expander: `st.expander("How this was calculated")` → agent chain of thought
- Booking button: `st.link_button("Book now →", url)`
- Sidebar: app description, example queries, disclaimer

### F8 — Booking Site Validator
- Lookup each `booking_url` domain against `verified_sites` and `flagged_sites` lists
- For unverified sites: append disclaimer "Not independently verified — check reviews before booking"

---

## 6. Technical Architecture

| Layer | Component | Technology |
|-------|-----------|------------|
| Frontend | Web app | Streamlit |
| Orchestration | Agent executor | LangChain 1.x `Runnable`-based agents (AgentExecutor was removed in v1.x — `Runnable` is the equivalent agent-object interface) |
| LLM | Inference | LiteLLM fallback — Groq (`llama-3.3-70b-versatile`) → OpenAI (`gpt-4o-mini`) → Gemini (`gemini-1.5-flash`) via `tools/llm_router.py` |
| RAG | Vectorless retrieval | PageIndex MCP (cloud) |
| Scraping | Live rate fetch | BeautifulSoup, requests, Playwright |
| Caching | Rate cache | SQLite |
| Knowledge base | Surcharge rules | JSON (charge_patterns.json) |
| Config | Secrets | python-dotenv (.env) |
| Deploy | Hosting | Streamlit Cloud |
| Testing | Test suite | pytest + unittest.mock |

### Agent Roster

| Agent | Input | Output | LLM call? |
|-------|-------|--------|-----------|
| Router | product, weight, origin, destination | shipment_mode, reason | Yes |
| Rate comparator | list of scraped quotes | ranked list with total cost | Yes |
| Hidden charge detector | single quote + KB context | trust_score, flags | Yes |
| Summarizer | ranked list + flags | recommendation text | Yes |

---

## 7. File Structure

```
freight-rate-intelligence/
├── app.py                        # Streamlit entry point
├── CLAUDE.md                     # Claude Code context file
├── .env.example                  # Env var template
├── requirements.txt
├── README.md
│
├── agents/
│   ├── __init__.py
│   ├── router.py                 # Mode classifier agent
│   ├── rate_comparator.py        # Ranking agent
│   ├── hidden_charge.py          # Surcharge detection agent
│   └── summarizer.py             # Recommendation agent
│
├── tools/
│   ├── __init__.py
│   ├── llm_router.py             # get_llm() — LiteLLM fallback chain (Groq → OpenAI → Gemini)
│   ├── scraper.py                # BeautifulSoup + Playwright rate scraper
│   ├── validator.py              # Booking site legitimacy checker
│   └── cache.py                  # SQLite rate cache
│
├── knowledge_base/
│   ├── ingest.py                 # Upload PDFs to PageIndex API, save doc_registry.json
│   ├── doc_registry.json         # {filename: doc_id} map (gitignored, rebuilt by ingest.py)
│   ├── charge_patterns.json      # Curated hidden charge rules + site lists
│   └── tariffs/                  # Seed PDF documents (IATA, Incoterms, surcharge bulletins)
│
├── tests/
│   ├── fixtures/                 # Mock scraper responses + mock PageIndex responses (JSON)
│   ├── test_agents.py
│   ├── test_scraper.py
│   ├── test_rag.py               # Tests PageIndex MCP tool calls with mocked responses
│   └── test_smoke.py             # End-to-end smoke test
│
└── .claude/
    ├── settings.json             # MCP config: pageindex + groq
    └── commands/
        ├── fix-tests.md
        ├── validate-schema.md
        └── run-smoke.md
```

---

## 8. Data Contracts

### Shipment Input Object
```python
{
  "product": str,
  "gross_weight_kg": float,
  "length_cm": float,
  "width_cm": float,
  "height_cm": float,
  "volume_weight_kg": float,      # (L × W × H) / 5000
  "chargeable_weight_kg": float,  # max(gross, volume)
  "weight_basis": str,            # "gross" | "volume"
  "origin": str,
  "destination": str,
  "urgency": str                  # "standard" | "express"
}
```

### Scraped Rate Object
```python
{
  "carrier": str,           # e.g. "Maersk"
  "base_price_usd": float,
  "chargeable_weight_kg": float,  # passed in from input object
  "transit_days": int,
  "booking_url": str,
  "source_site": str,       # e.g. "freightos.com"
  "scraped_at": str,        # ISO 8601
  "mode": str               # air_freight | sea_freight | courier | road_freight
}
```

### Scored Rate Object (after hidden charge agent)
```python
{
  **scraped_rate,
  "trust_score": int,       # 0–100
  "flags": list[str],       # plain-English warning strings
  "estimated_total_usd": float,
  "verified_site": bool
}
```

---

## 9. Environment Variables

```
GROQ_API_KEY=                  # Primary LLM inference
OPENAI_API_KEY=                # Fallback 1 (on Groq RateLimitError)
GEMINI_API_KEY=                # Fallback 2 (on OpenAI RateLimitError)
PAGEINDEX_API_KEY=             # Required — PageIndex MCP document retrieval
LIVE_SCRAPING=false            # Set true only in production
LOG_LEVEL=INFO
```

Loaded via `python-dotenv` (`load_dotenv()` at app start) in local dev; on Streamlit Cloud, inject from Settings → Secrets (no dotenv call needed in prod).

---

## 10. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Response time (cached) | < 3 seconds |
| Response time (live scrape) | < 15 seconds |
| Test coverage | ≥ 80% on agents/ and tools/ |
| Streamlit Cloud deploy | Zero config changes from local |
| Scraper failure tolerance | App must return RAG estimate if all scrapers fail |
| Mobile readability | Streamlit default responsive layout sufficient |

---

## 11. Out of Scope (v1.0)

- User accounts / saved searches
- Email alerts for rate changes
- Customs duty calculation
- Direct API integrations (Freightos API, Flexport API) — scraping only
- Multi-leg / transshipment route planning
- Non-English language support

---

## 12. Success Metrics (Portfolio)

- Demo scenario works end-to-end: `Delhi → Rotterdam, 200kg electronics`
- Hidden charge agent flags ≥ 3 known surcharge types in test fixtures
- Trust score correctly distinguishes verified vs flagged sites
- Agent reasoning visible in UI expander
- Passes smoke test in CI before every deploy
- README opens with a compelling real-world scenario (not a feature list)

---

## 13. Build Phases

| Phase | Deliverable | Est. effort |
|-------|-------------|-------------|
| 1 | Scaffold + knowledge base ingest | 1 day |
| 2 | Scraper + SQLite cache | 1–2 days |
| 3 | All 4 agents + LangChain wiring | 2 days |
| 4 | Streamlit UI | 1 day |
| 5 | Tests (unit + integration + smoke) | 1 day |
| 6 | Deploy to Streamlit Cloud | 0.5 day |
