import pytest

from abhelper.knowledge import KnowledgeBase
from abhelper.knowledge.search import _match_strength


@pytest.fixture
def kb(tmp_path):
    (tmp_path / "warp.md").write_text("""# Варп и растяжение сэмплов
keywords: warp, варп, растяжение, темп сэмпла, warping

Общий обзор варпа.

## Включение варпа
Откройте клип и включите кнопку Warp в Clip View. Режим Beats подходит для ударных.

## Режимы варпа
Beats, Tones, Texture, Re-Pitch, Complex, Complex Pro.
""", encoding="utf-8")
    (tmp_path / "midi.md").write_text("""# Запись MIDI
keywords: midi, запись, record, клавиатура

## Как записать ноты
Включите Arm на MIDI-дорожке, нажмите кнопку Record и играйте. Ёлка тоже работает.

## Квантование
Выделите клип и нажмите Cmd+U для квантования нот.
""", encoding="utf-8")
    (tmp_path / "broken.md").write_text("", encoding="utf-8")
    return KnowledgeBase(tmp_path)


def test_russian_query_finds_warp_section(kb):
    res = kb.search("как включить варп на клипе")
    assert res and res[0]["file"] == "warp.md"
    assert res[0]["section"] == "Включение варпа"
    assert set(res[0]) == {"file", "title", "section", "text", "score"}
    assert res[0]["title"] == "Варп и растяжение сэмплов"


def test_english_keyword_and_title(kb):
    res = kb.search("warping samples")
    assert res[0]["file"] == "warp.md"


def test_prefix_and_morphology(kb):
    assert kb.search("растяжения")[0]["file"] == "warp.md"
    assert kb.search("квантовать")[0]["section"] == "Квантование"


def test_yo_normalisation(kb):
    assert kb.search("елка")[0]["file"] == "midi.md"
    assert kb.search("ёлка")[0]["file"] == "midi.md"


def test_limit_and_no_results(kb):
    assert len(kb.search("midi warp клип", limit=2)) == 2
    assert kb.search("абракадабра zzzzqq") == []
    assert kb.search("") == []
    assert kb.search("как что") == []  # only stopwords


def test_scores_sorted_descending(kb):
    res = kb.search("midi запись record", limit=10)
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True)
    assert res[0]["file"] == "midi.md"


def test_short_tokens_do_not_prefix_match():
    assert _match_strength("mid", "midi") == 0.0
    assert _match_strength("midi", "midi") == 1.0
    assert _match_strength("warp", "warping") > 0


def test_missing_dir_is_empty(tmp_path):
    assert KnowledgeBase(tmp_path / "nope").search("warp") == []


def test_default_docs_dir_loads_without_error():
    # UX engineer's docs may or may not exist yet; must never raise
    KnowledgeBase().search("warp")
