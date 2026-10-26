"""Run health: collect problems during export so a broken source never fails *silently*.

export writes health.json (outside the published site); `trend-engine health-check` turns it into a
red CI run + a GitHub issue (see .github/workflows/pages.yml). The site is still deployed with
whatever data succeeded — the alert is about noticing, not about blocking.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Missing optional keys are configuration, not breakage.
IGNORED = ("missing config",)

# 상위 20개 중 '다른 소스가 함께 확인한' 이슈 수의 하한 — 2026-10-26 실측의 절반쯤.
# 소스가 조용히 막히면(배포 서버 IP 차단 등) 이 숫자가 먼저 떨어진다.
CONFIRMED_FLOOR = {"KR": 7, "JP": 4, "US": 5, "GB": 4, "TW": 5, "VN": 6}
TOP = 20


def confirmation(clusters: list[dict[str, Any]], top: int = TOP) -> dict[str, int]:
    """confirmed: 소스 2곳 이상이거나 헤드라인 언급이 있는 이슈 수 / multi: 소스 2곳 이상인 이슈 수."""
    head = clusters[:top]
    return {"confirmed": sum(1 for c in head if len(c.get("sources", {})) >= 2 or c.get("mentions")),
            "multi": sum(1 for c in head if len(c.get("sources", {})) >= 2)}


@dataclass
class Health:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    depth: dict[str, dict[str, int]] = field(default_factory=dict)

    def problem(self, msg: str) -> None:
        self.problems.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def check_report(self, region: str, report: dict[str, Any]) -> None:
        from .sources import REGISTRY

        status = report.get("source_status", {})
        broken = {n: s["error"] for n, s in status.items() if not s["ok"] and not str(s.get("error", "")).startswith(IGNORED)}
        for name, err in broken.items():
            # extras (community feeds, charts) come and go — worth knowing, not worth a red build
            report_it = self.warn if getattr(REGISTRY.get(name), "optional", True) else self.problem
            report_it(f"[{region}] 소스 실패: {name} — {str(err)[:160]}")
        for name, s in status.items():
            if s["ok"] and s.get("stale"):  # blocked, but a recent good result stood in (engine._run_source)
                self.warn(f"[{region}] 소스 일시 오류: {name} — 직전 결과로 대체 ({str(s['stale'])[:160]})")
        ok = sum(1 for s in status.values() if s["ok"])
        if ok < 2:
            self.problem(f"[{region}] 정상 소스가 {ok}개뿐")
        if len(report.get("clusters", [])) < 10:
            self.problem(f"[{region}] 랭킹 키워드가 {len(report.get('clusters', []))}개뿐")
        self.depth[region] = d = confirmation(report.get("clusters", []))
        floor = CONFIRMED_FLOOR.get(region)
        if floor is not None and d["confirmed"] < floor:
            self.warn(f"[{region}] 교차 확인 이슈가 상위 {TOP}개 중 {d['confirmed']}개 (기준 {floor}) — 소스가 막혔는지 확인")

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"ok": self.ok}

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")


def markdown(h: dict[str, Any], run_url: str = "") -> str:
    lines = ["자동 점검에서 문제가 발견됐습니다. 사이트는 성공한 데이터로 배포됐습니다.", ""]
    lines += [f"- ❌ {p}" for p in h.get("problems", [])]
    lines += [f"- ⚠️ {w}" for w in h.get("warnings", [])]
    if run_url:
        lines += ["", f"실행 로그: {run_url}"]
    lines += ["", "로컬 점검: `uv run trend-engine doctor` · 이 이슈는 정상으로 돌아오면 자동으로 닫힙니다."]
    return "\n".join(lines)


def check(path: Path) -> tuple[bool, str]:
    """Read health.json; also export `count`/`body` to $GITHUB_OUTPUT for the alert job."""
    h = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"problems": ["health.json 없음 — export 가 끝까지 실행되지 않음"], "warnings": []}
    if os.environ.get("HEALTH_SIMULATE"):  # workflow_dispatch test of the alert path
        h.setdefault("problems", []).append("(테스트) 알림 경로 점검용 가짜 문제")
    run_url = os.environ.get("RUN_URL", "")
    body = markdown(h, run_url)
    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"count={len(h.get('problems', []))}\n")
            f.write(f"body<<__HEALTH__\n{body}\n__HEALTH__\n")
    return not h.get("problems"), body
