# Testing Guide for AI Agents

This repository uses `pytest` for unit testing and `uv` for package management. When modifying code or adding new features, agents should verify that existing functionality remains intact by running the complete test suite.

## How to Run Tests

1. **Test Location:** All tests are located in the `tests/` directory.
2. **Environment:** The project is managed by `uv`. Use the `uv run` command, which automatically executes within the correct virtual environment cross-platform.

### Command

```bash
uv run pytest tests
```

*(If `uv run` is not available directly, fallback to using the `.venv\Scripts\python.exe -m pytest tests` on Windows or `.venv/bin/python -m pytest tests` on Linux/macOS)*

## Validating Changes

- Run tests **before** making changes to understand the baseline (if needed).
- Always run tests **after** modifying `src/` to ensure no regressions were introduced.
- If you add new logic, ensure your changes successfully pass existing assertions or update the tests if the behavior was intentionally changed.
