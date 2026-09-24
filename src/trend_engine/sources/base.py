"""Source contract. Every source = pure `parse(raw)` + side-effecting `fetch()`.

Keeping parse pure is what makes the harness work: tests and offline mode feed
recorded raw responses from tests/fixtures/<source>/<region>.<ext> into parse().
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from ..config import Region, Settings
from ..models import Kind, TrendItem

log = logging.getLogger(__name__)

# Transient upstream answers that recover if we wait (shared CI IPs get these often).
RETRY_STATUSES = frozenset({429, 503})


class SourceError(RuntimeError):
    pass


def _retry_wait(resp: httpx.Response, attempt: int, base_wait: float) -> float:
    """Seconds to sleep before the next try. Prefer Retry-After when the server sends it."""
    raw = resp.headers.get("Retry-After")
    if raw:
        try:
            return max(float(raw), 0.5)
        except ValueError:
            pass
    return base_wait * (2 ** attempt)


class Source(ABC):
    name: str  # stable id, also the fixture directory name
    label: str  # human label (Korean UI)
    kind: Kind = "keyword"
    weight: float = 1.0  # contribution to the merged score (see scoring.py)
    family: str = ""  # sources sharing a family are correlated; defaults to own name
    requires: tuple[str, ...] = ()  # Settings attribute names that must be non-empty
    regions: frozenset[str] | None = None  # None = any Google geo code
    fixture_ext: str = "json"
    subregion_aware: bool = False  # True if fetch() differs for KR-11 vs KR (only Google Trends today)
    optional: bool = True  # False = a failure is a real problem (alerts); True = nice-to-have extra

    def fixture_code(self, region: Region) -> str:
        return region.code if self.subregion_aware else region.country

    def supports(self, region: Region) -> bool:
        return self.regions is None or region.code in self.regions

    def missing_keys(self, settings: Settings) -> list[str]:
        return [k for k in self.requires if not getattr(settings, k)]

    def fixture_path(self, settings: Settings, region: Region) -> Path | None:
        base = settings.fixtures_dir / self.name
        for code in (region.code, region.country):
            p = base / f"{code}.{self.fixture_ext}"
            if p.exists():
                return p
        return None

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient, region: Region, settings: Settings) -> str:
        """Return the raw response body exactly as the upstream sent it (decoded to str)."""

    @abstractmethod
    def parse(self, raw: str, region: str) -> list[TrendItem]:
        """Pure: raw body -> ranked items. Must not do I/O."""

    async def collect(self, client: httpx.AsyncClient, region: Region, settings: Settings) -> list[TrendItem]:
        if settings.offline:
            path = self.fixture_path(settings, region)
            if path is None:
                raise SourceError(f"offline: no fixture for {self.name}/{region.code}")
            raw = path.read_text(encoding="utf-8")
        else:
            missing = self.missing_keys(settings)
            if missing:
                raise SourceError(f"missing config: {', '.join(missing)}")
            raw = await self.fetch(client, region, settings)
        return self.parse(raw, region.code)


def rerank(items: list[TrendItem]) -> list[TrendItem]:
    """Make ranks contiguous 1..n after filtering."""
    for i, item in enumerate(items, 1):
        item.rank = i
    return items


async def get_text(client: httpx.AsyncClient, url: str, *, encoding: str | None = None, **kw) -> str:
    resp = await client.get(url, **kw)
    if resp.status_code >= 400:
        raise SourceError(f"HTTP {resp.status_code} from {url.split('?')[0]}: {resp.text[:200]}")
    if encoding:
        return resp.content.decode(encoding, errors="replace")
    return resp.text


async def get_text_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    encoding: str | None = None,
    retries: int = 3,
    base_wait: float = 5.0,
    **kw,
) -> str:
    """Like get_text, but backs off on 429/503 (GitHub Actions shared egress hits these hourly)."""
    last: SourceError | None = None
    for attempt in range(retries + 1):
        resp = await client.get(url, **kw)
        if resp.status_code < 400:
            return resp.content.decode(encoding, errors="replace") if encoding else resp.text
        last = SourceError(f"HTTP {resp.status_code} from {url.split('?')[0]}: {resp.text[:200]}")
        if resp.status_code not in RETRY_STATUSES or attempt == retries:
            raise last
        wait = _retry_wait(resp, attempt, base_wait)
        log.info("retry %s after HTTP %s in %.1fs (attempt %d/%d)",
                 url.split("?")[0], resp.status_code, wait, attempt + 1, retries)
        await asyncio.sleep(wait)
    raise last  # pragma: no cover — loop always returns or raises
