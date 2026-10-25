"""공개 순위에서 성인물 문서·검색어를 거른다 — 위키 조회수 상위에 늘 섞여 들어오는 것들.

단어 일부만 같은 정상 문서(성교육·수간호사·자위대·밴드 ポルノグラフィティ)는 걸리지 않게 경계를 둔다.
"""

from __future__ import annotations

import re

_ADULT = re.compile(
    r"porn|\bxnxx\b|\bxvideos\b|\bxhamster\b|hentai|\bzoophilia\b|\bbestiality\b|\bmasturbation\b|\bincest\b"
    r"|sexual intercourse|sex position|^sex$|^xxx$"
    r"|포르노|성교(?!육|회)|자위행위|^섹스$|그룹 섹스|^야동$|^수간$|근친상간"
    r"|tình dục|khiêu dâm|giao phối|thủ dâm|loạn luân|phim sex"
    r"|ポルノ(?!グラフィティ)|セックス|性交|自慰|近親相姦|獣姦|アダルトビデオ"
    r"|色情|亂倫|乱伦|做愛|做爱|人獸交",
    re.I,
)


def is_adult(text: str | None) -> bool:
    return bool(text) and bool(_ADULT.search(text.replace("_", " ").strip()))
