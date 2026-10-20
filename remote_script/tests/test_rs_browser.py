import pytest

from AbletonHelper.browser_index import BrowserIndex, CATEGORY_ORDER
from rs_fakes import (FakeApplication, FakeBrowserItem, FakeSong, SilentBrowser, error, make_dispatcher,
                      make_world, result)


class Clock(object):
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_index_is_incremental_across_ticks():
    song, app = make_world()
    idx = BrowserIndex(app)
    idx.start(0)
    assert idx.status() == {"indexed": 0, "complete": False, "scanning": True, "truncated": False}
    steps = 0
    while not idx.status()["complete"]:
        assert idx.step(budget=10, max_items=3) <= 3
        steps += 1
        assert steps < 100
    assert steps > 3
    st = idx.status()
    assert st["complete"] and not st["scanning"] and not st["truncated"]
    assert st["indexed"] == 11


def test_index_waits_for_start_delay():
    song, app = make_world()
    clock = Clock()
    idx = BrowserIndex(app, clock=clock)
    idx.start(2.0)
    assert idx.step(1.0) == 0 and idx.status()["indexed"] == 0
    clock.t = 2.5
    assert idx.step(1.0) > 0


def test_index_time_budget_limits_work_per_step():
    song, app = make_world()
    app.browser.packs = FakeBrowserItem("Packs", [FakeBrowserItem("p%d" % i, loadable=True) for i in range(100)])

    class TickingClock(object):
        t = 0.0

        def __call__(self):
            TickingClock.t += 1.0   # every clock read costs one "second"
            return TickingClock.t

    idx = BrowserIndex(app, clock=TickingClock())
    idx.start(0)
    n = idx.step(budget=0.5, max_items=1000)
    assert n == 20 and not idx.status()["complete"]   # budget is checked every 20 items
    while not idx.status()["complete"]:
        idx.step(budget=0.5, max_items=1000)
    assert idx.status()["indexed"] == 111


def test_category_order_and_entries():
    song, app = make_world()
    idx = BrowserIndex(app)
    idx.start(0)
    idx.step(10, 100000)
    cats = []
    for e in idx._entries:
        if not cats or cats[-1] != e["category"]:
            cats.append(e["category"])
    assert cats == [c for c in CATEGORY_ORDER if c in cats]
    assert cats[0] == "instruments" and cats[-1] == "user_folders"
    by_path = dict((e["path"], e) for e in idx._entries)
    op = by_path["instruments/Operator"]
    assert op["is_device"] and op["is_loadable"] and op["uri"] == "query:Instruments#Operator"
    assert by_path["sounds/Piano & Keys"]["is_folder"]
    # no uri attribute -> path used as uri
    assert by_path["sounds/Piano & Keys/Piano Pad.adv"]["uri"] == "sounds/Piano & Keys/Piano Pad.adv"
    assert "user_folders/MyFolder/Accordion.wav" in by_path


def test_missing_categories_are_skipped():
    song = FakeSong()
    app = FakeApplication(song)
    for c in list(app.browser.CATS):
        delattr(app.browser, c)
    app.browser.drums = FakeBrowserItem("Drums", [FakeBrowserItem("Kit", loadable=True)])
    idx = BrowserIndex(app)
    idx.start(0)
    idx.step(10, 1000)
    assert [e["path"] for e in idx._entries] == ["drums/Kit"]
    assert idx.status()["complete"]


def test_truncated_flag_at_item_limit():
    song, app = make_world()
    idx = BrowserIndex(app, max_items=5)
    idx.start(0)
    idx.step(10, 1000)
    st = idx.status()
    assert st["indexed"] == 5 and st["truncated"] is True and st["complete"] is True


def test_depth_limit():
    song, app = make_world()
    node = FakeBrowserItem("leaf", loadable=True)
    for i in range(12):
        node = FakeBrowserItem("d%d" % i, [node])
    app.browser.packs = FakeBrowserItem("Packs", [node])
    idx = BrowserIndex(app, max_depth=8)
    idx.start(0)
    idx.step(10, 100000)
    depths = [e["path"].count("/") for e in idx._entries if e["category"] == "packs"]
    assert max(depths) == 8   # item at depth 8 is indexed, its children are not
    assert len(depths) == 8


def test_default_limits_match_protocol():
    from AbletonHelper import browser_index
    assert browser_index.MAX_DEPTH == 8 and browser_index.MAX_ITEMS == 60000
    assert browser_index.CATEGORY_ORDER == ("instruments", "sounds", "drums", "audio_effects", "midi_effects",
                                            "user_library", "packs", "samples", "clips", "plugins",
                                            "max_for_live", "user_folders")


def test_rescan_single_category():
    song, app = make_world()
    d = make_dispatcher(song, app)
    before = result(d, "browser_status")
    assert before["complete"] and before["indexed"] == 11
    app.browser.audio_effects = FakeBrowserItem("Audio Effects", [FakeBrowserItem("Delay", loadable=True, device=True)])
    assert result(d, "browser_rescan", categories=["audio_effects"]) == {"started": True}
    assert result(d, "browser_status")["scanning"] is True
    d.ctx.browser_index.step(10, 1000)
    names = [i["name"] for i in result(d, "browser_search", query="", loadable_only=False, limit=100)["items"]]
    assert "Delay" in names and "Reverb" not in names and "Operator" in names
    assert error(d, "browser_rescan", categories="x") == "bad_request"


# ---------------------------------------------------------------- search

def test_search_matching_and_ranking():
    song, app = make_world()
    app.browser.sounds = FakeBrowserItem("Sounds", [
        FakeBrowserItem("Keys", [
            FakeBrowserItem("Grand Piano.adg", loadable=True, uri="u1"),
            FakeBrowserItem("Piano Folder", [FakeBrowserItem("Deep Grand Piano Long Name.adv", loadable=True, uri="u2")]),
            FakeBrowserItem("Organ.adv", loadable=True, uri="u3"),
        ]),
        FakeBrowserItem("Piano Collection", [FakeBrowserItem("Soft.adv", loadable=True, uri="u4")]),
    ])
    d = make_dispatcher(song, app)
    out = result(d, "browser_search", query="grand PIANO")
    assert out["index_complete"] is True
    assert [i["uri"] for i in out["items"]] == ["u1", "u2"]   # both words in name first, shorter path first
    out = result(d, "browser_search", query="piano")
    # name matches first (u1, u2), then path-only matches (Soft.adv under 'Piano Collection')
    assert out["items"][0]["name"] == "Grand Piano.adg"
    assert out["items"][-1]["uri"] == "u4"
    assert set(out["items"][0]) == {"name", "uri", "path", "category", "is_loadable", "is_device", "is_folder"}


def test_search_filters_and_limit():
    song, app = make_world()
    d = make_dispatcher(song, app)
    names = lambda **kw: [i["name"] for i in result(d, "browser_search", **kw)["items"]]
    assert "Piano & Keys" not in names(query="piano")           # folders hidden by default
    assert "Piano & Keys" in names(query="piano", loadable_only=False)
    assert names(query="e", categories=["audio_effects"]) == ["Reverb"]
    assert len(names(query="", limit=3)) == 3
    assert names(query="zzz") == []
    assert error(d, "browser_search") == "bad_request"
    assert error(d, "browser_search", query="a", limit=0) == "bad_request"


def test_search_partial_while_scanning():
    song, app = make_world()
    d = make_dispatcher(song, app, index_complete=False)
    d.ctx.browser_index.start(0)
    d.ctx.browser_index.step(10, 4)
    out = result(d, "browser_search", query="", loadable_only=False, limit=100)
    assert out["index_complete"] is False and 0 < len(out["items"]) <= 4


# ---------------------------------------------------------------- list / load

def test_browser_list_categories_and_children():
    song, app = make_world()
    d = make_dispatcher(song, app, with_index=False)
    cats = [i["name"] for i in result(d, "browser_list")["items"]]
    assert cats[0] == "instruments" and "user_folders" in cats and "current_project" not in cats
    items = result(d, "browser_list", path="sounds/Piano & Keys")["items"]
    assert [i["name"] for i in items] == ["Grand Piano.adg", "Piano Pad.adv"]
    assert items[0]["path"] == "sounds/Piano & Keys/Grand Piano.adg" and items[0]["category"] == "sounds"
    items = result(d, "browser_list", path="user_folders")["items"]
    assert [i["path"] for i in items] == ["user_folders/MyFolder"]
    assert result(d, "browser_list", path="user_folders/MyFolder")["items"][0]["name"] == "Accordion.wav"
    ci = result(d, "browser_list", path="Sounds/piano & keys")["items"]
    assert ci[0]["path"] == "sounds/Piano & Keys/Grand Piano.adg"
    assert error(d, "browser_list", path="sounds/Nope") == "not_found"
    assert error(d, "browser_list", path="bogus") == "not_found"


def test_load_browser_item_by_uri_and_path():
    song, app = make_world()
    d = make_dispatcher(song, app)
    out = result(d, "load_browser_item", track_index=0, uri="query:Sounds#Grand")
    assert out["loaded"] is True and out["name"] == "Grand Piano.adg"
    assert out["devices"] == [{"index": 0, "name": "Instrument Rack", "class_name": "InstrumentGroupDevice", "type": "instrument"}]
    assert "pending" not in out
    assert song.view.selected_track is song.tracks[0]
    out = result(d, "load_browser_item", track_index=0, path="audio_effects/Reverb")
    assert [x["name"] for x in out["devices"]] == ["Instrument Rack", "Reverb"]


def test_load_browser_item_falls_back_to_live_path_walk():
    song, app = make_world()
    d = make_dispatcher(song, app, index_complete=False)   # empty index
    out = result(d, "load_browser_item", track_index=0, path="instruments/Wavetable")
    assert out["devices"][0]["name"] == "Wavetable"


def test_load_browser_item_errors():
    song, app = make_world()
    d = make_dispatcher(song, app)
    assert error(d, "load_browser_item", track_index=0) == "bad_request"
    assert error(d, "load_browser_item", track_index=0, uri="nope") == "not_found"
    assert error(d, "load_browser_item", track_index=5, uri="query:Sounds#Grand") == "not_found"
    assert error(d, "load_browser_item", track_index=0, path="sounds/Piano & Keys") == "bad_request"   # folder


def test_load_browser_item_pending_when_device_list_unchanged():
    song, app = make_world(browser_class=SilentBrowser)
    d = make_dispatcher(song, app)
    out = result(d, "load_browser_item", track_index=0, uri="query:Sounds#Grand")
    assert out["loaded"] is True and out["pending"] is True and out["devices"] == []
