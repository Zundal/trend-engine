import asyncio

import pytest

from trend_engine.config import Settings
from trend_engine.engine import TrendEngine
from trend_engine.publish import public_report
from trend_engine.safety import is_adult
from trend_engine.store import Store


@pytest.mark.parametrize("title", ["Pornhub", "91porn", "XXX", "Sex", "Sexual_intercourse", "성교_체위", "자위행위",
                                   "야동", "Tình_dục_với_động_vật", "Phim_khiêu_dâm", "膣性交", "色情片", "E-Hentai"])
def test_adult_titles_are_caught(title):
    assert is_adult(title)


@pytest.mark.parametrize("title", ["ポルノグラフィティ", "성교육", "수간호사", "자위대", "XXXTentacion", "Sex Pistols",
                                   "Essex", "Middlesex", "Giáo dục giới tính", "", None])
def test_ordinary_titles_pass(title):
    assert not is_adult(title)


@pytest.mark.parametrize("code", ["KR", "JP", "US", "GB", "TW", "VN"])
def test_public_report_has_no_adult_labels(code):
    rep = asyncio.run(TrendEngine(Settings(offline=True, db_path=":memory:"), Store(":memory:")).collect(code, save=False))
    pub = public_report(rep.to_dict())
    labels = [c["label"] for c in pub["clusters"]] + [m["label"] for t in pub["themes"] for m in t["members"]]
    assert labels and not [x for x in labels if is_adult(x)]
