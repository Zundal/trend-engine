---
name: trend-engine
description: Use when the user asks about real-time trends, rising keywords, what 10·20대 (Gen Z / youth) are searching for, generational trend diffusion (10·20대 to 40대+), age/gender search affinity, shopping keywords, or cross-country issues (KR, US, JP, TW, VN, GB) using trend-engine.
---

# Trend Engine Skill

`trend-engine` crosses multiple keyless public signals (search surges, portal real-time issues, Wikipedia pageviews, news, shopping rankings, and video charts) into a verified trend ranking, broken down by **country, age, gender, and generational diffusion**.

## 1. Setup & Quick Check

If `trend-engine` is already installed in the current workspace or environment:

```bash
uv run trend-engine --help
```

If not yet cloned locally, run it from a temporary or dedicated directory:

```bash
git clone https://github.com/Zundal/trend-engine.git
cd trend-engine
uv sync --all-extras
```

All core features work **without API keys**. Pass `--json` to any CLI command for structured agent consumption, or `--offline` to run deterministically from recorded fixtures without network access.

## 2. Core Commands for Agents

### Country & City Real-Time Trends (`collect`)
Collect and rank cross-verified issues for a region (`KR`, `KR-11` for Seoul, `US`, `JP`, `TW`, `VN`, `GB`, or any Google geo code):

```bash
uv run trend-engine collect -r KR --json
uv run trend-engine collect -r US --json
```

Key fields in `--json` output:
- `clusters`: Ranked issues with `label`, `score`, `status` (`new` | `rising` | `falling` | `steady`), `rank_change`, `category`, `related` headlines.
- `source_status`: Health and item count per upstream source.

### Age & Gender Search Affinity (`segments` / `keyword`)
Compare which demographic group searches for current issues or arbitrary keywords (`100` = all-age average, anchor-normalized):

```bash
# Top trending issues broken down by age/gender
uv run trend-engine segments -r KR --top 14 --segments "10대,20대,30대,40대,50대,60대+,남성,여성" --json

# Compare arbitrary keywords directly
uv run trend-engine keyword 아이폰 갤럭시 --segments "10대,20대,40대,50대" --json
```

> **Interpretation rule:** Affinity `180` in `20대` means the keyword's share of 20s searches is **1.8×** the all-age average — NOT that 180% of searchers are in their 20s.

### Age & Gender Distinctive Shopping Keywords (`shopping`)
Find shopping search terms popular in specific age/gender groups (`distinctive` = terms unique to that group and absent from overall top rankings):

```bash
uv run trend-engine shopping --segments "10대,20대 여성,20대 남성,50대" --json
```

### Youth Discovery & Generational Diffusion (Python API)
For 10·20대 discovery ("what youth search N× more than 30+") and generational diffusion stages (`확산 대기` → `확산 중` → `윗세대 상승`), query `TrendService`:

```bash
uv run python -c "
import asyncio, json
from trend_engine.config import Settings
from trend_engine.service import TrendService

svc = TrendService(Settings.from_env())
print(json.dumps(asyncio.run(svc.youth()), ensure_ascii=False, indent=2))
"
```

Replace `svc.youth()` with `svc.diffusion()` for generational diffusion stages, `svc.attention("KR")` for ranking turnover/concentration, or `svc.shapes("KR")` for burst shape classification (`예고형` / `하루형` / `대칭형` / `여운형`).

### Local Dashboard & Static Export
```bash
uv run trend-engine serve --port 8765           # Live web dashboard at http://127.0.0.1:8765
uv run trend-engine --offline serve --port 8765 # Offline demo with recorded fixtures
uv run trend-engine doctor -r KR                # Check live upstream health
```
