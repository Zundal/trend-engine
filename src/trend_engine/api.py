"""HTTP API + dashboard. Run: trend-engine serve  (or uvicorn --factory trend_engine.api:create_app)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .service import TrendService

WEB = Path(__file__).parent / "web"


def _split(v: str | None) -> list[str] | None:
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def create_app(service: TrendService | None = None) -> FastAPI:
    app = FastAPI(title="Trend Engine", version="0.1.0")
    svc = service or TrendService()
    app.state.service = svc

    async def guard(coro):
        try:
            return await coro
        except PermissionError as e:
            raise HTTPException(status_code=412, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/api/meta")
    def meta():
        return svc.meta()

    @app.get("/api/report")
    async def report(region: str = "KR", refresh: bool = False):
        return await svc.report(region, refresh)

    @app.get("/api/segments")
    async def segments(region: str = "KR", top: int = Query(16, ge=1, le=40), segments: str | None = None):
        return await guard(svc.report_segments(region, top, _split(segments)))

    @app.get("/api/keyword")
    async def keyword(q: str, segments: str | None = None):
        kws = _split(q) or []
        if not kws:
            raise HTTPException(400, "q is required (comma separated)")
        return await guard(svc.keyword_segments(kws[:20], _split(segments)))

    @app.get("/api/shopping")
    async def shopping(segments: str | None = None, categories: str | None = None):
        return await svc.shopping(_split(segments), _split(categories))

    @app.get("/api/seoul")
    async def seoul(places: str | None = None):
        return await svc.seoul(_split(places))

    @app.get("/api/history")
    def history(key: str, region: str = "KR"):
        return svc.history(region, key)

    @app.post("/api/brief")
    async def brief(region: str = "KR"):
        return await guard(svc.brief(region))

    return app

