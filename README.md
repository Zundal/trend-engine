# Trend Engine — history archive

Written automatically by `.github/workflows/pages.yml` (do not edit by hand).
One folder per finished KST day:

- `trends-<COUNTRY>.json` — keywords that trended that day: label, hours in ranking, best rank, avg score
- `segments.json` — 연령·성별 groups' over-indexed keywords (Korea)
- `shopping.json` — 연령·성별 shopping keywords (Korea, 7-day window as of that day)

Source-neutral by design (no provider names). Read with `trend_engine.archive`.
