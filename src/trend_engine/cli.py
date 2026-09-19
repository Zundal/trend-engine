"""Command line: trend-engine <command>. Every command supports --json for agents/scripts."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from .config import Settings


def _print(data: Any, as_json: bool, render) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        render(data)


def _render_report(r: dict) -> None:
    print(f"\n■ {r['region_name']} ({r['region']}) 트렌드 — {r['generated_at']} UTC\n")
    arrows = {"new": "NEW", "rising": "▲", "falling": "▼", "steady": "-", None: " "}
    for i, c in enumerate(r["clusters"][:30], 1):
        ch = arrows[c.get("status")]
        if c.get("rank_change"):
            ch += str(abs(c["rank_change"]))
        srcs = ",".join(c["sources"])
        extra = "".join(f" +{k}:{len(v)}" for k, v in c.get("mentions", {}).items())
        print(f"{i:>3}. {c['label'][:34]:<34} {c['score']:>6.1f} {ch:<5} [{srcs}]{extra}")
    print("\n소스 상태:")
    for name, st in r["source_status"].items():
        print(f"  {'✓' if st['ok'] else '✗'} {name:<14} {st['count']:>3}개  {st['error'] or ''}")


def _render_segments(s: dict) -> None:
    if s.get("synthetic"):
        print("⚠ 오프라인 합성 데이터 — 실제 수치가 아닙니다.")
    print(f"기간 {s['period'][0]} ~ {s['period'][1]}, 기준어 '{s['anchor']}' (affinity 100 = 전체 평균)\n")
    labels = s.get("labels", {})
    for seg, rows in s["top_by_segment"].items():
        tops = ", ".join(f"{labels.get(r['keyword'], r['keyword'])}({r['affinity']:.0f})" for r in rows[:5])
        print(f"  {seg:<8} {tops}")
    for e in s.get("errors", []):
        print(f"  ! {e}")


def _render_seoul(d: dict) -> None:
    if d.get("sample"):
        print("⚠ SEOUL_API_KEY 없음: 공개 sample 키로 1개 장소만 표시합니다.")
    for p in d["places"]:
        ages = " ".join(f"{k}:{v:.0f}%" for k, v in p["ages"].items())
        print(f"  {p['name']:<18} {p['congestion']:<6} {p['population_min']:,}~{p['population_max']:,}명  "
              f"주 연령층: {p.get('dominant_group') or '-'}  | {ages}")
    for e in d.get("errors", []):
        print(f"  ! {e}")


def _render_shopping(d: dict) -> None:
    print(f"쇼핑 인기 검색어 {d['period'][0]} ~ {d['period'][1]} (★ = 전체 순위엔 없는 그룹 고유 관심)\n")
    for seg, cats in d["by_segment"].items():
        print(f"■ {seg}")
        for cat, v in cats.items():
            dist = set(v["distinctive"])
            print(f"  {cat:<8} " + ", ".join(("★" if k in dist else "") + k for k in v["top"][:6]))
    for e in d.get("errors", []):
        print(f"  ! {e}")


def _render_brief(b: dict) -> None:
    print(f"\n{b['headline']}\n")
    for t in b["themes"]:
        print(f"● [{t['category']}] {t['title']} — {t['summary']}\n   {', '.join(t['keywords'])}")
    for s in b["segment_insights"]:
        print(f"◆ {s['segment']}: {s['insight']}")
    if b.get("seoul"):
        print(f"\n서울: {b['seoul']}")
    for c in b.get("caveats", []) + b.get("warnings", []):
        print(f"  ※ {c}")


def _render_doctor(rows: list[dict]) -> None:
    icon = {"ok": "✓", "warn": "!", "fail": "✗", "skip": "·"}
    for r in rows:
        print(f"  {icon[r['status']]} {r['check']:<16} {r['status']:<5} {r.get('count', ''):>4} {r.get('detail', '')}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="trend-engine", description="구글·네이버·유튜브·실시간 검색어 트렌드 엔진")
    p.add_argument("--offline", action="store_true", help="네트워크 대신 tests/fixtures 사용 (데모/테스트)")
    p.add_argument("--json", action="store_true", help="JSON 출력")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("collect", help="지금 트렌드 수집·랭킹")
    c.add_argument("-r", "--region", default="KR", help="KR, KR-11(서울), US, JP ... (Google geo)")
    c.add_argument("-s", "--source", action="append", help="특정 소스만 (반복 가능)")

    s = sub.add_parser("segments", help="상위 트렌드의 연령/성별 affinity (네이버 DataLab)")
    s.add_argument("-r", "--region", default="KR")
    s.add_argument("--top", type=int, default=16)
    s.add_argument("--segments", help="예: '20대,30대,20대 여성'")

    k = sub.add_parser("keyword", help="임의 키워드의 연령/성별 affinity")
    k.add_argument("keywords", nargs="+")
    k.add_argument("--segments")

    se = sub.add_parser("seoul", help="서울 핫스팟 실시간 인구·연령 분포")
    se.add_argument("--places", help="쉼표 구분 장소명 (서울시 POI 명칭)")

    sh = sub.add_parser("shopping", help="연령·성별 쇼핑 인기 검색어 (네이버 쇼핑인사이트, 키 불필요)")
    sh.add_argument("--segments", help="예: '20대,20대 여성,60대+'")
    sh.add_argument("--categories", help="예: '패션의류,디지털/가전'")

    b = sub.add_parser("brief", help="Claude AI 트렌드 브리핑")
    b.add_argument("-r", "--region", default="KR")

    sv = sub.add_parser("serve", help="API + 대시보드 실행")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)

    d = sub.add_parser("doctor", help="모든 업스트림 라이브 점검 (harness)")
    d.add_argument("-r", "--region", default="KR")

    rc = sub.add_parser("record", help="라이브 응답으로 tests/fixtures 갱신 (harness)")
    rc.add_argument("--regions", default="KR,KR-11,US,JP")

    ex = sub.add_parser("export", help="GitHub Pages 용 정적 사이트 생성")
    ex.add_argument("--out", default="site")
    ex.add_argument("--regions", default="KR,US,JP,GB,TW,VN")
    ex.add_argument("--archive", help="일별 요약 저장 위치 (기본: TREND_ENGINE_ARCHIVE 또는 data/archive)")
    ex.add_argument("--health", help="점검 결과 파일 (사이트 밖에 저장, 예: health.json)")

    hc = sub.add_parser("health-check", help="export 가 남긴 점검 결과 확인 — 문제 있으면 종료코드 1")
    hc.add_argument("path", nargs="?", default="health.json")

    args = p.parse_args(argv)
    if args.offline:
        os.environ["TREND_ENGINE_OFFLINE"] = "1"
        os.environ.setdefault("TREND_ENGINE_DB", "data/offline.db")
    settings = Settings.from_env()
    split = lambda v: [x.strip() for x in v.split(",") if x.strip()] if v else None  # noqa: E731

    if args.cmd == "serve":
        import uvicorn

        print(f"대시보드: http://{args.host}:{args.port}  {'(offline 데모)' if settings.offline else ''}")
        uvicorn.run("trend_engine.api:create_app", factory=True, host=args.host, port=args.port)
        return 0

    from . import harness
    from .service import TrendService

    if args.cmd == "health-check":
        from pathlib import Path

        from .health import check

        ok, body = check(Path(args.path))
        print(body if not ok else "health: OK")
        return 0 if ok else 1
    if args.cmd == "doctor":
        rows = asyncio.run(harness.doctor(settings, args.region))
        _print(rows, args.json, _render_doctor)
        return 1 if any(r["status"] == "fail" for r in rows) else 0
    if args.cmd == "record":
        for line in asyncio.run(harness.record(settings, split(args.regions) or ["KR"])):
            print(line)
        return 0

    svc = TrendService(settings)
    if args.cmd == "export":
        from pathlib import Path

        from .export import export_site

        for line in asyncio.run(export_site(svc, Path(args.out), split(args.regions) or ["KR"],
                                                  Path(args.archive) if args.archive else None,
                                                  Path(args.health) if args.health else None)):
            print(line)
        return 0
    try:
        if args.cmd == "collect":
            r = asyncio.run(svc.engine.collect(args.region, args.source)).to_dict()
            _print(r, args.json, _render_report)
        elif args.cmd == "segments":
            _print(asyncio.run(svc.report_segments(args.region, args.top, split(args.segments))), args.json, _render_segments)
        elif args.cmd == "keyword":
            _print(asyncio.run(svc.keyword_segments(args.keywords, split(args.segments))), args.json, _render_segments)
        elif args.cmd == "shopping":
            _print(asyncio.run(svc.shopping(split(args.segments), split(args.categories))), args.json, _render_shopping)
        elif args.cmd == "seoul":
            _print(asyncio.run(svc.seoul(split(args.places))), args.json, _render_seoul)
        elif args.cmd == "brief":
            _print(asyncio.run(svc.brief(args.region)), args.json, _render_brief)
    except PermissionError as e:
        print(f"설정 필요: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
