Validate that all agent outputs conform to their Pydantic schemas.

1. Import all agent builders: `build_router_agent`, `build_hidden_charge_agent`, `build_rate_comparator_agent`, `build_summarizer_agent`
2. Use FakeChatModel from `tests/conftest.py` to mock LLM calls
3. Invoke each agent with the SHIPMENT_200KG fixture
4. Assert output dicts contain all required keys per CLAUDE.md data contracts:
   - Router: `{mode, reason}`
   - Hidden-charge: `{trust_score, flags, verified_site, confidence}`
   - Rate-comparator: `{estimated_total_usd}` added to input rates
   - Summarizer: `{recommendation}` (1-2000 chars)
5. Report pass/fail per agent
