from trend_engine.normalize import mentions, mentions_any, norm_key, similar, similar_text


def test_norm_key_ignores_spacing_case_punct():
    assert norm_key("두산에너 빌리티") == norm_key("두산에너빌리티")
    assert norm_key("KT 로건, 연승 도전!") == "kt로건연승도전"
    assert norm_key("Ｇｏｏｇｌｅ") == "google"  # NFKC full-width


def test_similar():
    assert similar(norm_key("허양 임"), norm_key("허양임"))
    assert similar_text("KT 로건 승리 도전", "KT 로건, 연승 도전!")
    assert not similar_text("청하", "청와대")
    assert not similar(norm_key("m"), norm_key("mbc"))  # too short to match by containment


def test_mentions_requires_meaningful_length():
    assert mentions(norm_key("청하"), "청하 (CHUNG HA) 직캠")
    assert not mentions(norm_key("m"), "anything with m")
    assert not mentions(norm_key("ai"), "said")  # 2-char ascii is too ambiguous


def test_mentions_any_word_overlap():
    assert mentions_any({"여의도역 5번 출구 에스컬레이터 화재"}, "여의도역 에스컬레이터 화재 현장 영상")
    assert not mentions_any({"여의도역 5번 출구 에스컬레이터 화재"}, "여의도 한강공원 불꽃축제")


def test_near_identical_but_different_entities_do_not_merge():
    assert not similar_text("아이폰16", "아이폰17")
    assert not similar_text("A키워드", "B키워드")
