"""Watchlist + alerts: the engine watches for you instead of waiting to be opened.

Rules fire only on a *change* versus the previous run (state kept in the store), so a trend that
stays 확산 중 for a week does not alert every hour. Output:
  - `feed.xml` (plain RSS at the site root — readers can't decrypt, and it carries keywords only)
  - `alerts.dat` (encrypted, for the dashboard card)
  - optional Slack POST when SLACK_WEBHOOK_URL is set
Watchlist: one keyword per line in watchlist.txt (# comments), always tracked and alerted on.
"""

from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VS_OLDER_ALERT = 2.0  # 10·20대가 30대 이상보다 2배 이상 찾기 시작하면
STAGE_ALERTS = ("확산 대기", "확산 중", "윗세대 상승")
FORECAST_WEEKS = 4  # 정점이 4주 안으로 들어오면
KEEP_DAYS = 14


@dataclass
class Alert:
    date: str
    kind: str  # stage / youth / forecast / watchlist
    keyword: str
    category: str
    message: str
    watched: bool = False

    @property
    def id(self) -> str:
        return f"{self.date}:{self.kind}:{self.keyword}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"id": self.id}


def load_watchlist(path: Path) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def evaluate(tracked: dict[str, Any], youth: dict[str, Any] | None, previous: dict[str, Any] | None,
             watchlist: list[str], today: str) -> tuple[list[Alert], dict[str, Any]]:
    """-> (new alerts, state to store for next time)."""
    prev = previous or {}
    prev_stage, prev_youth = prev.get("stages", {}), prev.get("youth", {})
    watched = {w.strip() for w in watchlist}
    alerts: list[Alert] = []
    stages: dict[str, str] = {}
    youth_max: dict[str, float] = {}

    for it in tracked.get("items", []):
        kw, stage = it["keyword"], it["stage"]
        stages[kw] = stage
        is_watched = kw in watched
        if stage in STAGE_ALERTS and prev_stage.get(kw) != stage:
            msg = {"확산 대기": "10·20대에서 뜨는 중 — 윗세대는 아직 조용",
                   "확산 중": f"윗세대로 번지는 중{f' (40대+ {it['old_lag_weeks']}주 차이)' if it.get('old_lag_weeks') else ''}",
                   "윗세대 상승": "윗세대에서 오르기 시작"}[stage]
            alerts.append(Alert(today, "stage", kw, it.get("category") or "기타", f"{stage}: {msg}", is_watched))
        ages = (it.get("forecast") or {}).get("ages") or {}
        soon = {a: f for a, f in ages.items() if 0 <= f.get("weeks_from_now", 99) <= FORECAST_WEEKS}
        if soon and prev_stage.get(kw) != stage:  # only alongside a stage change, not every day
            when = ", ".join(f"{a} {f['weeks_from_now']}주 뒤" for a, f in sorted(soon.items()))
            alerts.append(Alert(today, "forecast", kw, it.get("category") or "기타", f"정점 예상: {when}", is_watched))

    for rows in (youth or {}).get("groups", {}).values():
        for r in rows:
            kw, vs = r["keyword"], r.get("vs_older") or 0
            youth_max[kw] = max(youth_max.get(kw, 0), vs)
    for kw, vs in youth_max.items():
        if vs >= VS_OLDER_ALERT and prev_youth.get(kw, 0) < VS_OLDER_ALERT:
            alerts.append(Alert(today, "youth", kw, "", f"10·20대가 30대 이상보다 {vs:.1f}배 검색", kw in watched))

    for kw in watched:  # a watched keyword showing up at all is worth knowing
        if kw in stages and kw not in prev_stage:
            alerts.append(Alert(today, "watchlist", kw, "", "관심 키워드가 추적 목록에 들어옴", True))

    alerts.sort(key=lambda a: (not a.watched, a.kind, a.keyword))
    return alerts, {"stages": stages, "youth": youth_max}


def merge_recent(new: list[Alert], history: list[dict[str, Any]], keep_days: int = KEEP_DAYS) -> list[dict[str, Any]]:
    seen = {a["id"] for a in history}
    out = [a.to_dict() for a in new if a.id not in seen] + history
    dates = sorted({a["date"] for a in out}, reverse=True)[:keep_days]
    return [a for a in out if a["date"] in dates][:200]


def to_rss(alerts: list[dict[str, Any]], site_url: str, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731
    items = []
    for a in alerts[:50]:
        title = f"[{a['kind'] == 'watchlist' and '관심' or a['category'] or '트렌드'}] {a['keyword']} — {a['message']}"
        items.append(f"""    <item>
      <title>{esc(title)}</title>
      <description>{esc(a["message"])}</description>
      <link>{esc(site_url)}#diffusion</link>
      <guid isPermaLink="false">{esc(a["id"])}</guid>
      <pubDate>{datetime.fromisoformat(a["date"]).strftime("%a, %d %b %Y 00:00:00 +0000")}</pubDate>
    </item>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Trend Engine 알림</title>
    <link>{esc(site_url)}</link>
    <description>10·20대에서 뜨는 것, 윗세대로 번지는 것, 관심 키워드 변화</description>
    <language>ko</language>
    <lastBuildDate>{now.strftime("%a, %d %b %Y %H:%M:%S +0000")}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""


async def notify_slack(webhook: str, alerts: list[Alert], site_url: str, client) -> bool:
    if not webhook or not alerts:
        return False
    lines = [f"• *{a.keyword}* — {a.message}" + (" 🔖" if a.watched else "") for a in alerts[:10]]
    text = f"*Trend Engine* 새 알림 {len(alerts)}건\n" + "\n".join(lines) + f"\n{site_url}#diffusion"
    r = await client.post(webhook, json={"text": text})
    return r.status_code < 300


SOURCE_WORDS = re.compile(r"google|youtube|naver|네이버|nate|signal|wikipedia", re.I)
