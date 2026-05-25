---
name: freight-backlog
description: Phase 5 backlog — known bugs, polish items, and non-blocking improvements surfaced by reviewers
context: fork
---

# Phase 5 Backlog (non-blocking)

> **Status note (2026-04-22):** the Phase 5 test suite LOCKS current behaviour in. Items below describe bugs/polish to fix in a future commit — tests will need updating alongside each fix.

- `tools/cache.py`: `clear_cache` has a redundant `_connect().close()` line that leaks on a failing reconnect — drop it; table is recreated lazily on next call.
- `tools/cache.py`: error logs for unparseable `cached_at` / `rates_json` should include origin/destination in the `%s->%s` format used elsewhere.
- `tools/scraper.py`: `_parse_days_from_text` reuses `_PRICE_RE` but doesn't strip commas; `"2,000 days"` raises `ValueError` (silently drops the row via the per-parser except). Use a dedicated `r"\d+"` or strip commas.
- `tools/scraper.py`: `Query.origin` / `destination` / `mode` are unused in v1 (reserved for live mode) — document with a one-line note or defer trimming until live mode is wired.
- ~~`pipeline.py`: hidden-charge LLM calls are serial (~0.5s × N rates). Parallelise via `ThreadPoolExecutor` or batch all N cards into one LLM call for ~3× latency reduction.~~ **Done (Phase 5.5):** batched into single LLM call.
- `agents/rate_comparator.py`: no LLM call; the `Runnable` wrapper is pure A2A ceremony. If A2A never ships, collapse to a plain function.
- `agents/summarizer.py`: `payload["shipment"]` is an unguarded `[]` access while `router_reason` / `ranked_rates` use `.get(default)` — inconsistent. Either make all three defaults-based or raise a typed error.
- `agents/summarizer.py`: output isn't streamed; Phase 4 Streamlit can add streaming if UX demands.
- `agents/summarizer.py`: optional `query_pageindex(incoterms_doc_id, ...)` call for Incoterms-aware advice — hook exists in design, not wired.
