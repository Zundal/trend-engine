"""Settings and region definitions. Everything is env-driven so agents/tests can override."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Region:
    code: str  # Google geo code: "KR", "KR-11"(서울), "US" ...
    name: str
    country: str  # ISO country for APIs that only accept countries (YouTube, News)
    lang: str  # wikipedia / news language


REGIONS: dict[str, Region] = {
    r.code: r
    for r in [
        Region("KR", "대한민국", "KR", "ko"),
        Region("KR-11", "서울", "KR", "ko"),
        Region("KR-26", "부산", "KR", "ko"),
        Region("US", "미국", "US", "en"),
        Region("JP", "일본", "JP", "ja"),
        Region("GB", "영국", "GB", "en"),
        Region("DE", "독일", "DE", "de"),
        Region("FR", "프랑스", "FR", "fr"),
        Region("TW", "대만", "TW", "zh"),
        Region("VN", "베트남", "VN", "vi"),
        Region("IN", "인도", "IN", "en"),
        Region("BR", "브라질", "BR", "pt"),
    ]
}


def get_region(code: str) -> Region:
    code = code.upper()
    if code in REGIONS:
        return REGIONS[code]
    # Any other Google geo code still works for Google sources.
    country = code.split("-")[0]
    return Region(code, code, country, "en")


@dataclass
class Settings:
    naver_client_id: str = ""
    naver_client_secret: str = ""
    naver_api: str = ""  # "hub" (NAVER API HUB key), "legacy" (developers.naver.com key), "web" (no key); "" = auto
    youtube_api_key: str = ""
    offline: bool = False
    db_path: str = "data/trends.db"
    archive_dir: str = "data/archive"  # daily summaries (committed to the `data` branch in CI)
    fixtures_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2] / "tests" / "fixtures")
    user_agent: str = "trend-engine/0.1 (+https://github.com/; research use)"
    timeout: float = 15.0

    @property
    def naver_mode(self) -> str:
        """Explicit NAVER_API wins; otherwise use the key if present, else the keyless web form."""
        if self.naver_api in ("hub", "legacy", "web"):
            return self.naver_api
        return "hub" if (self.naver_client_id and self.naver_client_secret) else "web"

    @property
    def naver_modes(self) -> list[str]:
        """Primary mode first, then fallbacks: with a key the keyless web path backs up the API
        (and vice versa when web is forced), so one blocked path doesn't stop age analysis."""
        has_key = bool(self.naver_client_id and self.naver_client_secret)
        primary = self.naver_mode
        others = [m for m in (["hub", "web"] if has_key else ["web"]) if m != primary]
        return [primary, *others]

    @classmethod
    def from_env(cls, dotenv: bool = True) -> "Settings":
        if dotenv:
            _load_dotenv()
        env = os.environ.get
        return cls(
            naver_client_id=env("NAVER_CLIENT_ID", ""),
            naver_client_secret=env("NAVER_CLIENT_SECRET", ""),
            naver_api=env("NAVER_API", "").strip().lower(),
            youtube_api_key=env("YOUTUBE_API_KEY", ""),
            offline=env("TREND_ENGINE_OFFLINE", "0") in ("1", "true", "yes"),
            db_path=env("TREND_ENGINE_DB", "data/trends.db"),
            archive_dir=env("TREND_ENGINE_ARCHIVE", "data/archive"),
        )
