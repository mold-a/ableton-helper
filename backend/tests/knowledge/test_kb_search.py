import json
from pathlib import Path

import pytest

from abhelper.knowledge import COLLECTIONS, DEFAULT_DOCS_DIR, KnowledgeBase
from abhelper.knowledge.search import SYNONYMS_PATH, normalize, stem, tokenize

WARP = """# Варп и растяжение сэмплов
keywords: warp, варп, растяжение, темп сэмпла, warping

Общий обзор варпа.

## Включение варпа
Откройте клип и включите кнопку Warp в Clip View. Режим Beats подходит для ударных.

## Режимы варпа
Beats, Tones, Texture, Re-Pitch, Complex, Complex Pro.
"""

MIDI = """# Запись MIDI
keywords: midi, запись, record, клавиатура

## Как записать ноты
Включите Arm на MIDI-дорожке, нажмите кнопку Record и играйте. Ёлка тоже работает.

## Квантование
Выделите клип и нажмите Cmd+U для квантования нот.
"""

FILTER = """# Operator: фильтр
keywords: operator, фильтр, filter

## Срез фильтра
Параметр Filter Freq (cutoff) задаёт частоту среза. Чем выше cutoff, тем звук ярче.

## Огибающая
Ae Attack и Ae Release формируют амплитуду.
"""

THEORY = """# Лады и гаммы
keywords: лад, гамма, scale, mode, дорийский

## Дорийский лад
Дорийский лад — минор с повышенной шестой ступенью. Пример: D E F G A B C.

## Источники
- https://example.org/lad
- https://example.org/scale
"""


@pytest.fixture
def docs(tmp_path):
    for sub, name, text in (("help", "warp.md", WARP), ("help", "midi.md", MIDI), ("sound", "operator.md", FILTER),
                            ("theory", "scales.md", THEORY)):
        d = tmp_path / sub
        d.mkdir(exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")
    (tmp_path / "help" / "broken.md").write_text("", encoding="utf-8")
    return tmp_path


@pytest.fixture
def kb(docs):
    return KnowledgeBase(docs)


# --------------------------------------------------------------------------- basics
def test_result_shape_and_collections(kb):
    res = kb.search("как включить варп на клипе")
    assert res and res[0]["file"] == "warp.md" and res[0]["collection"] == "help"
    assert set(res[0]) == {"collection", "file", "title", "section", "text", "score"}
    assert res[0]["section"] == "Включение варпа" and res[0]["title"] == "Варп и растяжение сэмплов"
    assert kb.collections() == {"help": 5, "sound": 2, "theory": 2}


def test_collection_filter(kb):
    assert {r["collection"] for r in kb.search("фильтр cutoff лад warp запись", limit=20)} == {"help", "sound", "theory"}
    only = kb.search("фильтр cutoff лад warp запись", limit=20, collection="sound")
    assert only and {r["collection"] for r in only} == {"sound"}
    assert kb.search("warp", collection="theory") == [] or all(r["collection"] == "theory" for r in kb.search("warp", collection="theory"))
    assert kb.search("warp", collection="nope") == []
    assert kb.search("варп", collection="HELP")[0]["file"] == "warp.md"  # case-insensitive


def test_english_keyword_and_title(kb):
    assert kb.search("warping samples")[0]["file"] == "warp.md"


def test_prefix_and_morphology(kb):
    assert kb.search("растяжения")[0]["file"] == "warp.md"
    assert kb.search("квантовать")[0]["section"] == "Квантование"
    assert kb.search("записывать")[0]["file"] == "midi.md"


def test_yo_normalisation(kb):
    assert kb.search("елка")[0]["file"] == "midi.md"
    assert kb.search("ёлка")[0]["file"] == "midi.md"
    assert normalize("Ёлка") == "елка"


def test_limit_no_results_and_stopwords(kb):
    assert len(kb.search("midi warp клип", limit=2)) == 2
    assert kb.search("абракадабра zzzzqq") == []
    assert kb.search("") == []
    assert kb.search("как что") == []  # only stopwords
    assert kb.search("warp", limit=0) == []


def test_scores_sorted_descending(kb):
    res = kb.search("midi запись record", limit=10)
    scores = [r["score"] for r in res]
    assert scores == sorted(scores, reverse=True)
    assert res[0]["file"] == "midi.md"


def test_missing_dir_is_empty(tmp_path):
    kb = KnowledgeBase(tmp_path / "nope")
    assert kb.search("warp") == [] and kb.sections == [] and kb.collections() == {}


def test_index_is_lazy_and_built_once(docs, monkeypatch):
    kb = KnowledgeBase(docs)
    assert kb._chunks is None
    kb.search("warp")
    first = kb._chunks
    assert first is not None
    kb.search("midi")
    assert kb._chunks is first
    kb.reload()
    assert kb._chunks is None and kb.search("warp")


def test_legacy_root_level_files_belong_to_help(tmp_path):
    (tmp_path / "old.md").write_text("# Старое\nkeywords: старое\n\n## Раздел\nТекст про лупы.\n", encoding="utf-8")
    res = KnowledgeBase(tmp_path).search("лупы")
    assert res and res[0]["collection"] == "help"


# --------------------------------------------------------------------------- synonyms / stemming
def test_synonym_expansion_ru_to_en_terms(kb):
    # the doc says "cutoff" and "ярче"; the query uses "brighter" / "светлее" which are in the same synonym group
    res = kb.search("how to make it brighter", collection="sound")
    assert res and res[0]["section"] == "Срез фильтра"
    res = kb.search("сделать ярче", collection="sound")
    assert res and res[0]["section"] == "Срез фильтра"


def test_synonym_en_to_ru(kb):
    res = kb.search("dorian mode", collection="theory")
    assert res and res[0]["section"] == "Дорийский лад"
    assert kb.search("дорийская гамма")[0]["collection"] == "theory"


def test_multiword_synonym_phrase(kb):
    res = kb.search("filter cutoff", collection="sound")
    assert res[0]["section"] == "Срез фильтра"


def test_sources_sections_are_demoted(kb):
    res = kb.search("scale lad", collection="theory", limit=5)
    assert res[0]["section"] == "Дорийский лад"
    assert [r["section"] for r in res][-1] == "Источники"


def test_stem_and_tokenize():
    assert stem("растяжение") == stem("растяжения") == stem("растягивать")
    assert stem("варпа") == stem("варп") or stem("варпа").startswith(stem("варп"))
    assert stem("включить") == stem("включение") or stem("включить").startswith("включ")
    assert stem("warping") == stem("warps") == stem("warp") == "warp"
    assert stem("filters") == stem("filtering") == "filter"
    assert stem("scales") == "scale" and stem("adding") == stem("add")
    assert stem("808") == "808"
    assert tokenize("Time-stretch и Ёлка") == ["time-stretch", "time", "stretch", "и", "елка"]


def test_synonyms_file_is_valid():
    data = json.loads(SYNONYMS_PATH.read_text(encoding="utf-8"))
    groups = data["groups"]
    assert len(groups) >= 150
    assert all(isinstance(g, list) and len(g) >= 2 and all(isinstance(t, str) and t for t in g) for g in groups)
    flat = {t for g in groups for t in g}
    for needle in ("ярче", "brighter", "cutoff", "срез", "реверб", "reverb", "ревер", "атака", "attack", "бас", "bass",
                   "басуха", "аккорд", "chord", "лад", "scale", "mode", "гамма", "варп", "warp", "сайдчейн", "sidechain"):
        assert needle in flat, needle


# --------------------------------------------------------------------------- chunking
def test_long_section_is_split_into_chunks_of_bounded_size(tmp_path):
    d = tmp_path / "help"
    d.mkdir()
    paras = "\n\n".join(f"Абзац {i}: " + ("слово " * 60) + f"uniquemarker{i}" for i in range(12))
    (d / "big.md").write_text(f"# Большой\nkeywords: большой\n\n## Длинный раздел\n{paras}\n", encoding="utf-8")
    kb = KnowledgeBase(tmp_path)
    assert len(kb.sections) >= 3
    assert all(len(c.text) <= 1200 for c in kb.sections)
    res = kb.search("uniquemarker7")
    assert res and "uniquemarker7" in res[0]["text"] and len(res[0]["text"]) <= 1200


def test_code_blocks_and_headings_in_code_are_not_sections(tmp_path):
    (tmp_path / "x.md").write_text("# Т\nkeywords: к\n\n## Раздел\nТекст\n```\n## не раздел\n```\nконец\n", encoding="utf-8")
    kb = KnowledgeBase(tmp_path)
    assert [c.section for c in kb.sections] == ["Раздел"]


def test_keywords_and_title_boost(tmp_path):
    (tmp_path / "a.md").write_text("# Сайдчейн\nkeywords: ducking, пампинг\n\n## Как\nНастройте компрессор.\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Другое\nkeywords: другое\n\n## Как\nИногда говорят ducking в разговоре о компрессоре.\n", encoding="utf-8")
    res = KnowledgeBase(tmp_path).search("ducking")
    assert res[0]["file"] == "a.md"


# --------------------------------------------------------------------------- real docs
def test_default_docs_dir_layout_and_loading():
    help_dir = DEFAULT_DOCS_DIR / "help"
    assert len(list(help_dir.glob("*.md"))) == 19
    assert not list(DEFAULT_DOCS_DIR.glob("*.md")), "docs must live in collection sub-folders"
    kb = KnowledgeBase()
    assert kb.collections().get("help", 0) >= 100
    assert set(kb.collections()) <= set(COLLECTIONS)


@pytest.mark.parametrize("query,file", [
    ("как включить варп", "06-warping.md"),
    ("как включить warp у сэмпла", "06-warping.md"),
    ("how to warp a loop", "06-warping.md"),
    ("сайдчейн компрессор", "12-mixing-sidechain.md"),
    ("как сделать сайдчейн на бас", "12-mixing-sidechain.md"),
    ("как заморозить дорожку freeze", "13-export-freeze-flatten.md"),
    ("задержка latency размер буфера", "16-preferences-audio-latency.md"),
    ("горячие клавиши", "01-interface-views.md"),
    ("макрос ручки в рэке", "08-devices-racks.md"),
])
def test_real_help_docs_top1(query, file):
    kb = KnowledgeBase()
    res = kb.search(query, collection="help")
    assert res and res[0]["file"] == file, [(r["file"], r["section"]) for r in res]


def test_real_help_warp_section_is_found_first():
    res = KnowledgeBase().search("как включить варп")
    assert res[0]["file"] == "06-warping.md" and res[0]["collection"] == "help"
    assert any("Warp" in r["section"] for r in res[:3])


def test_real_theory_docs_when_present():
    kb = KnowledgeBase()
    if "theory" not in kb.collections():
        pytest.skip("theory docs not written yet")
    res = kb.search("аккордовая прогрессия в миноре", collection="theory")
    assert res and all(r["collection"] == "theory" for r in res)
    res = kb.search("дорийский лад", collection="theory")
    assert res and "scales" in res[0]["file"]


def test_real_search_is_fast():
    import time

    kb = KnowledgeBase()
    kb.search("warp")  # build
    t = time.perf_counter()
    for q in ("варп", "reverb brighter", "аккорд минор", "сайдчейн на бас"):
        kb.search(q, limit=4)
    assert time.perf_counter() - t < 0.5


def test_package_data_covers_collection_layout():
    root = Path(__file__).resolve().parents[3]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "knowledge/docs/*/*.md" in text and "knowledge/*.json" in text
