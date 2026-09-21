"""Beliefs persist across runs and steer the watch list (offline, synthetic data)."""

from datetime import date, timedelta

from trend_engine import pomdp


async def test_beliefs_persist_and_items_carry_them(service):
    dif = await service.diffusion()
    items = dif["tracked"]["items"]
    assert items and all("belief" in it for it in items)
    assert set(items[0]["belief"]) >= {"b", "phase", "confidence", "updated"}
    assert dif["tracked"]["model"]["sequences"] >= 0 and dif["tracked"]["belief_accuracy"]
    saved = service.store.cache_get("belief:v1", timedelta(days=1))
    assert saved and set(saved) >= {it["keyword"] for it in items}
    # the same day again: the observation is not double counted
    service.store.cache_set("diffusion:v10", None)
    service.store.db.execute("DELETE FROM cache WHERE key='diffusion:v10'"); service.store.db.commit()
    again = await service.diffusion()
    b1 = {it["keyword"]: it["belief"]["b"] for it in items}
    b2 = {it["keyword"]: it["belief"]["b"] for it in again["tracked"]["items"]}
    assert all(b1[k] == b2[k] for k in b1 if k in b2)


def test_watch_list_holds_pending_keywords(service):
    today = date(2026, 9, 21)
    b = pomdp.Belief.initial()
    for _ in range(4):
        b = b.update("확산 대기", days=7)
    service.store.cache_set("belief:v1", {"숨은유행": b.stamp(today - timedelta(days=1)).to_dict()})
    got = service.watch_list(["a", "b", "c"], [], limit=3, today=today)
    assert got[0] == "숨은유행" and len(got) == 3


async def test_model_is_persisted_and_learns_from_the_archive(service, tmp_path):
    from datetime import date as _date

    from trend_engine import archive

    # three weeks of archived daily stages for one keyword -> one extra sequence for the fit
    root = tmp_path / "archive"
    for i in range(21):
        day = _date(2026, 8, 3) + timedelta(days=i)
        archive._write_json(root / day.isoformat() / "diffusion.json",
                            {"stages": {"옛유행": {"stage": "확산 대기", "old_lag_weeks": None}}, "date": day.isoformat()})
    service.settings.archive_dir = str(root)
    seqs = archive.diffusion_sequences(service.store, root, today=_date(2026, 8, 25))
    assert seqs == [[0, 0, 0]]
    dif = await service.diffusion()
    saved = service.store.cache_get("pomdp-model:v1", timedelta(days=1))
    assert saved and saved["sequences"] == dif["tracked"]["model"]["sequences"] >= 1
