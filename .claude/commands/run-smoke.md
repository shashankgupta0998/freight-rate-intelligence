Run the CLAUDE.md-mandated Delhi→Rotterdam smoke test.

```
uv run pytest tests/test_smoke.py::test_smoke_delhi_rotterdam_12kg_completes_end_to_end -v
```

Expected: PASS with courier mode, 10 rates, no errors, non-empty recommendation.
