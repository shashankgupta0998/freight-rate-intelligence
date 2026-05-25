---
paths:
  - "agents/**"
---

- Always import `get_llm()` from `tools.llm_router` — never instantiate ChatGroq, ChatOpenAI, or ChatGoogleGenerativeAI directly
- All agents receive `chargeable_weight_kg`, never `gross_weight_kg`
- All agents return via Pydantic BaseModel + `with_structured_output`
- Use temperature 0.2 for classification/scoring, 0.5 for prose generation
- Hidden-charge agent includes `confidence` field (high/low/unclear) in all output paths
