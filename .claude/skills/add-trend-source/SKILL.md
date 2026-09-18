---
name: add-trend-source
description: Use when adding a new trend data source (chart, SNS trend, portal keyword feed, API) to trend-engine, or when an existing source's upstream format changed and parse() must be fixed.
---

# Add / repair a trend source

Follow docs/ADDING_A_SOURCE.md. Checklist — do every step, in order:

1. Probe the upstream first with curl; confirm it works without auth or note the required key. Record the raw response shape.
2. Implement `sources/<name>.py`: `fetch()` returns the raw body unchanged; `parse()` is pure (no I/O, clock, random) and returns `rerank(items)`.
3. Pick `kind` (keyword vs content), `weight` (≤ existing peers unless clearly stronger), and `family` if it mirrors an existing source's origin.
4. Register in `sources/__init__.py`.
5. Save a fixture: `uv run trend-engine record --regions KR` (review: no API keys inside). Synthetic fixture only if no key — mark `_synthetic` and list it in tests/fixtures/README.md.
6. `uv run pytest -q` must pass (contract tests pick the source up automatically). Add a focused test for any tricky parsing.
7. `uv run trend-engine --offline collect` and `uv run trend-engine doctor` — confirm the source shows up and ranks sensibly.
8. Update docs/SOURCES.md, `.env.example` + `config.Settings` if a key is needed, and the `SRC` label map in `web/index.html`.

Repairing a broken source: `doctor` → `record` → failing contract test → fix `parse()` → commit fixture + code together.
