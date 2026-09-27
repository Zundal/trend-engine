"""국가 간 전파: every exported language gets the same depth of measurement."""

from datetime import timedelta

import pytest

from trend_engine.config import EXPORT_REGIONS, export_langs


def test_export_langs_covers_every_exported_region_once():
    assert export_langs(EXPORT_REGIONS) == ("ko", "en", "ja", "zh", "vi")  # US and GB share en
    assert export_langs(["KR", "KR-11", "JP"]) == ("ko", "ja")


@pytest.mark.asyncio
async def test_offline_crosscountry_measures_all_exported_languages(service):
    cc = await service.crosscountry()
    assert cc["langs"] == ["ko", "en", "ja", "zh", "vi"]
    assert set(cc["origins"]) == set(cc["measured"]) == set(cc["langs"])
    assert cc["origins"]["ko"] >= 3 and cc["ambiguous"] == 0
    assert any(f["from"] == "ko" and f["leads"] for f in cc["flows"])
    # the cache is per language set, so a narrower ask does not get the wide answer
    assert service.store.cache_get("crosscountry:v2:ko,en,ja,zh,vi", timedelta(days=1))
    narrow = await service.crosscountry(("ko", "en"))
    assert narrow["langs"] == ["ko", "en"]


@pytest.mark.asyncio
async def test_meta_regions_carry_their_language(service):
    langs = {r["code"]: r["lang"] for r in service.meta()["regions"]}
    assert langs["KR"] == "ko" and langs["US"] == langs["GB"] == "en" and langs["TW"] == "zh"
