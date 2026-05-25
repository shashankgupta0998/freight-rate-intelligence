Run the test suite, identify failures, and fix them one by one.

1. Run `uv run pytest -v` and capture output
2. For each failing test, read the test file and the source file it tests
3. Fix the minimal code change to make the test pass
4. Re-run the single test to confirm it passes
5. After all fixes, run the full suite to check for regressions
6. Commit with message: "fix: resolve test failures"
