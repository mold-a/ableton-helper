"""RU/EN alias search over the recipe library."""

import pytest

from abhelper.sound import RecipeLibrary, RecipeMatch
from abhelper.sound.matching import make_toks, stem, token_match, tokenize, make_tok

LIB = RecipeLibrary.load_default()

QUERIES = [
    ("хочу звук баяна", "bayan"),
    ("я хочу звук баяна", "bayan"),
    ("сделай гармошку", "bayan"),
    ("accordion", "bayan"),
    ("акордеон", "bayan"),                      # typo / spelling variant
    ("губная гармошка", "harmonica"),
    ("рояль", "grand_piano"),
    ("рояля", "grand_piano"),
    ("фоно", "grand_piano"),
    ("grand piano", "grand_piano"),
    ("родес", "electric_piano"),
    ("клавиши", "electric_piano"),
    ("wurlitzer", "wurlitzer"),
    ("орган хаммонд", "organ_drawbar"),
    ("церковный орган", "church_organ"),
    ("струнные", "strings_ensemble"),
    ("скрипка", "solo_violin"),
    ("скрипку", "solo_violin"),
    ("violin", "solo_violin"),
    ("виолончель", "solo_cello"),
    ("пиццикато", "pizzicato_strings"),
    ("духовая секция", "brass_section"),
    ("труба", "trumpet"),
    ("флейта", "flute"),
    ("флейту", "flute"),
    ("кларнет", "clarinet"),
    ("саксофон", "saxophone"),
    ("хор", "choir_aah"),
    ("пэд", "warm_analog_pad"),
    ("сделай тёплый пэд как у Boards of Canada", "warm_analog_pad"),
    ("warm analog pad", "warm_analog_pad"),
    ("амбиент пэд", "ambient_pad"),
    ("лид", "supersaw_lead"),
    ("supersaw", "supersaw_lead"),
    ("чиптюн", "chiptune_lead"),
    ("8-bit square lead", "chiptune_lead"),
    ("pluck", "pluck_synth"),
    ("колокольчики", "glockenspiel"),
    ("маримба", "marimba"),
    ("калимба", "kalimba"),
    ("арфа", "harp"),
    ("гитара", "acoustic_guitar"),
    ("электрогитара", "electric_guitar"),
    ("балалайка", "balalaika"),
    ("ситар", "sitar"),
    ("steel drum", "steel_drum"),
    ("саб", "sub_bass"),
    ("басуха", "sub_bass"),
    ("жирный бас", "sub_bass"),
    ("reese", "reese_bass"),
    ("ацид", "acid_bass"),
    ("303", "acid_bass"),
    ("808", "bass_808"),
    ("бас 808", "bass_808"),
    ("вобл бас", "wobble_bass"),
    ("дабстеп", "wobble_bass"),
    ("басуха как в техно", "techno_rumble"),
    ("жирный бас для техно", "techno_rumble"),
    ("бас-гитара", "electric_bass"),
    ("808 kit", "drum_kit_808"),
    ("ударные", "drum_kit_acoustic"),
    ("барабаны", "drum_kit_acoustic"),
    ("лоуфай бит", "lofi_drums"),
    ("рисер", "riser_fx"),
    ("жирный рисер", "riser_fx"),
    ("ветер", "noise_sweep_wind"),
    ("музыкальная шкатулка", "music_box"),
    ("лоуфай клавиши", "vinyl_lofi_keys"),
    ("колокола", "tubular_bells"),
]


@pytest.mark.parametrize("query,expected", QUERIES)
def test_query_finds_expected_recipe(query, expected):
    matches = LIB.search(query)
    assert matches, f"no matches for {query!r}"
    assert matches[0].recipe_id == expected, [(m.recipe_id, m.score) for m in matches[:3]]
    assert matches[0].score >= 0.5      # strong enough for the engine to pick it automatically


def test_at_least_25_queries_covered():
    assert len(QUERIES) >= 25


def test_match_dataclass_and_ordering():
    matches = LIB.search("хочу звук баяна", limit=5)
    assert all(isinstance(m, RecipeMatch) for m in matches)
    assert matches[0].name == "Баян" and matches[0].category == "reed"
    scores = [m.score for m in matches]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert len(LIB.search("баян", limit=2)) <= 2
    assert matches[0].to_dict()["recipe_id"] == "bayan"


def test_garbage_and_empty_queries_do_not_match_strongly():
    assert LIB.search("") == []
    assert LIB.search("   ") == []
    weak = LIB.search("квантовая хромодинамика")
    assert not weak or weak[0].score < 0.5


def test_specific_phrase_beats_generic_word():
    """'губная гармошка' must not fall back to the accordion ('гармошка')."""
    assert LIB.search("губная гармошка")[0].recipe_id == "harmonica"
    assert LIB.search("гармошка")[0].recipe_id == "bayan"


def test_techno_context_selects_rumble_over_generic_bass():
    assert LIB.search("бас для техно")[0].recipe_id == "techno_rumble"
    assert LIB.search("бас")[0].recipe_id == "sub_bass"


def test_get_all_and_membership():
    assert LIB.get("bayan")["id"] == "bayan"
    assert LIB.get("nope") is None
    assert "bayan" in LIB and len(LIB.all()) == len(LIB)


# ------------------------------------------------------------------ morphology helpers
@pytest.mark.parametrize("a,b", [("баяна", "баян"), ("рояля", "рояль"), ("скрипку", "скрипка"), ("флейты", "флейта"),
                                 ("струнные", "струнных"), ("колокольчиков", "колокольчики")])
def test_russian_forms_share_a_stem(a, b):
    assert stem(a) == stem(b), (stem(a), stem(b))


def test_yo_and_case_are_normalised():
    assert tokenize("Тёплый ПЭД") == ["теплый", "пэд"]
    assert make_toks("тёплый")[0].stem == make_toks("теплый")[0].stem


def test_transliteration_and_typos():
    assert token_match(make_tok("баян"), make_tok("bayan")) >= 0.9
    assert token_match(make_tok("бас"), make_tok("bass")) >= 0.9
    assert token_match(make_tok("аккордеон"), make_tok("accordion")) >= 0.6
    assert token_match(make_tok("piano"), make_tok("violin")) == 0.0
    assert token_match(make_tok("808"), make_tok("809")) == 0.0


def test_prefix_match_needs_four_chars():
    assert token_match(make_tok("гармон"), make_tok("гармонь")) >= 0.85
    assert token_match(make_tok("бас"), make_tok("басуха")) < 0.85


def test_stopwords_are_dropped_but_kept_if_nothing_else_remains():
    assert [t.raw for t in make_toks("я хочу звук баяна")] == ["баяна"]
    assert [t.raw for t in make_toks("звук")] == ["звук"]
