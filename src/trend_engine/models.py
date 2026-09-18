"""Core data shapes shared by every layer. Sources emit TrendItem; the engine emits TrendCluster."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Kind = Literal["keyword", "content"]
# keyword: 검색어 자체가 신호 (Google Trends, 실시간 검색어, 위키 문서명)
# content: 콘텐츠 제목 (YouTube 영상, 뉴스 헤드라인) — 키워드 언급 여부로 교차 검증에 쓰인다


@dataclass
class TrendItem:
    source: str
    region: str
    rank: int  # 1-based, contiguous within one (source, region) fetch
    keyword: str  # display text (keyword or content title)
    kind: Kind = "keyword"
    volume: float | None = None  # source-native magnitude: traffic, views, pageviews
    url: str | None = None
    category: str | None = None
    related: list[str] = field(default_factory=list)  # e.g. related news headlines
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def query(self) -> str:
        """Best short search query for this item (used for Naver DataLab profiling)."""
        return self.meta.get("query") or self.keyword

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrendCluster:
    """One 'interest' merged across sources (e.g. '두산에너빌리티' from Google + Nate + news)."""

    label: str
    key: str
    score: float
    variants: list[str] = field(default_factory=list)
    sources: dict[str, int] = field(default_factory=dict)  # source -> best rank
    mentions: dict[str, list[str]] = field(default_factory=dict)  # content source -> titles
    related: list[str] = field(default_factory=list)
    query: str = ""
    volume: float | None = None
    status: Literal["new", "rising", "steady", "falling"] | None = None  # None = no history yet
    rank_change: int | None = None  # + means moved up vs previous snapshot
    segments: dict[str, float] = field(default_factory=dict)  # segment -> affinity index (100 = avg)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrendReport:
    region: str
    region_name: str
    generated_at: str
    clusters: list[TrendCluster]
    content: dict[str, list[TrendItem]]  # source -> items (youtube, news)
    source_status: dict[str, dict[str, Any]]  # source -> {ok, count, error}

    def to_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "region_name": self.region_name,
            "generated_at": self.generated_at,
            "clusters": [c.to_dict() for c in self.clusters],
            "content": {k: [i.to_dict() for i in v] for k, v in self.content.items()},
            "source_status": self.source_status,
        }
