"""Ranking of browser search results."""

import pytest

from abhelper.sound.presets import PresetSearcher, category_weights, clean_name, score_item
from abhelper.bridge.fake import FakeBridge
from sound_testkit import FakeClock

W = category_weights()


def item(path, category=None, **kw):
    name = path.rsplit("/", 1)[-1]
    d = {"name": name, "uri": "u:" + path, "path": path, "category": category or path.split("/", 1)[0],
         "is_loadable": True, "is_device": False, "is_folder": False}
    d.update(kw)
    return d


def test_clean_name_strips_live_extensions():
    assert clean_name("Grand Piano.adg") == "Grand Piano"
    assert clean_name("Kick.wav") == "Kick"
    assert clean_name("No Extension") == "No Extension"


def test_exact_name_scores_highest():
    exact = score_item(item("sounds/Piano & Keys/Grand Piano.adg"), "grand piano", W)
    longer = score_item(item("sounds/Piano & Keys/Grand Piano Bright Soft.adg"), "grand piano", W)
    partial = score_item(item("sounds/Piano & Keys/Upright Piano.adg"), "grand piano", W)
    assert exact > longer > partial
    assert exact >= 0.95 and partial < 0.6


def test_whole_words_only():
    assert score_item(item("sounds/Keys/Pianoforte.adv"), "piano", W) == 0.0
    assert score_item(item("sounds/Keys/Pianos.adv"), "piano", W) > 0.8        # plural is fine


def test_category_preference():
    sound = score_item(item("sounds/Strings/Strings.adg"), "strings", W)
    instrument = score_item(item("instruments/Operator/Strings.adv"), "strings", W)
    sample = score_item(item("samples/One Shots/Strings.wav"), "strings", W)
    clip = score_item(item("clips/Strings.alc"), "strings", W)
    assert sound > instrument > sample > clip > 0


def test_sampler_recipes_prefer_samples():
    ws = category_weights("keys", "Simpler")
    assert score_item(item("samples/One Shots/Accordion C3.wav"), "accordion", ws) > \
        score_item(item("sounds/Reed/Accordion.adv"), "accordion", ws)


def test_drum_recipes_prefer_the_drums_category():
    wd = category_weights("drums", "Drum Rack")
    assert score_item(item("drums/Drum Rack/808 Core Kit.adg"), "808 kit", wd) > \
        score_item(item("sounds/Drums/808 Core Kit.adg"), "808 kit", wd)
    assert score_item(item("drums/Drum Rack/808 Core Kit.adg"), "808 kit", W) < 0.6      # a drum rack is wrong for a pad


def test_devices_folders_and_unloadable_items_never_score():
    assert score_item(item("instruments/Operator", is_device=True), "operator", W) == 0
    assert score_item(item("sounds/Piano", is_folder=True), "piano", W) == 0
    assert score_item(item("sounds/Piano/Piano.adv", is_loadable=False), "piano", W) == 0
    assert score_item(item("audio_effects/Reverb/Piano Hall.adv"), "piano hall", W) == 0


def test_instrument_family_conflicts_are_penalised():
    plain = score_item(item("sounds/Piano & Keys/Piano.adg"), "piano", W, allowed=set())
    bass = score_item(item("sounds/Bass/Piano Bass.adv"), "piano", W, allowed=set())
    assert bass < 0.6 <= plain
    # a bass recipe explicitly allows the family
    assert score_item(item("sounds/Bass/Sub Bass.adv"), "sub bass", W, allowed={"bass"}) > 0.9


def test_earlier_terms_weigh_slightly_more():
    first = score_item(item("sounds/Piano/Piano.adg"), "piano", W, term_rank=0)
    later = score_item(item("sounds/Piano/Piano.adg"), "piano", W, term_rank=3)
    assert first > later >= first * 0.8


def test_searcher_merges_terms_and_dedupes():
    bridge = FakeBridge()
    found = PresetSearcher(bridge).search(["electric piano", "piano"], limit=10)
    names = [f["name"] for f in found]
    assert names[0] == "Electric Piano Mk I.adg"
    assert names.count("Grand Piano.adg") == 1
    assert found[0]["matched_term"] == "electric piano"


def test_searcher_splits_a_multiword_term_when_nothing_matches():
    items = [{"path": "sounds/Keys/Soft Piano.adv"}]
    found = PresetSearcher(FakeBridge(browser_items=items)).search(["upright piano"])
    # whole phrase finds nothing; the individual word does, but is only a partial match
    assert [f["name"] for f in found] == ["Soft Piano.adv"] and found[0]["score"] < 0.6


def test_searcher_respects_limit_and_blank_terms():
    s = PresetSearcher(FakeBridge())
    assert len(s.search(["piano", "strings", "pad", "bass"], limit=2)) == 2
    assert s.search(["", "  "]) == []


def test_searcher_waits_only_when_the_index_is_incomplete():
    clock = FakeClock()
    PresetSearcher(FakeBridge(), sleep=clock.sleep, clock=clock.clock).search(["piano"])
    assert clock.sleeps == []
