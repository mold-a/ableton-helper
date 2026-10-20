"""registry.json schema and consistency with the recipe library."""

import copy
import json

import pytest

from abhelper.samples import REGISTRY_PATH, find_pack, load_registry, validate_registry
from abhelper.sound import RecipeLibrary

DATA = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_shipped_registry_is_valid_and_matches_the_recipe_library():
    ids = {r["id"] for r in RecipeLibrary.load_default().all()}
    errors = validate_registry(DATA, ids)
    assert errors == []


def test_every_default_pack_is_verified_cc0_with_hashes():
    packs = load_registry()
    assert packs and len({p.id for p in packs}) == len(packs)
    for p in packs:
        assert p.license["name"].startswith("CC0") and p.license["url"].startswith("https://creativecommons.org/")
        assert p.preset_name.startswith("AbletonHelper ")
        if p.default:
            assert p.verified and p.sha256 and p.size_bytes
        assert p.url.startswith("https://")


def test_bayan_pack_is_the_hohner_accordion():
    packs = load_registry()
    p = find_pack(packs, "accordion-hn")
    assert p is not None and "bayan" in p.recipe_ids and "accordion" in p.aliases
    assert p.preset_name == "AbletonHelper Accordion HN" and p.archive == "7z"
    assert p.url.endswith("ButtonAccordionHN-SFZ+WAV-20240329.7z") and p.size_bytes == 6020026
    assert find_pack(packs, "ACCORDION-HN") is p and find_pack(packs, "nope") is None


def mutated(**changes):
    data = copy.deepcopy(DATA)
    data["packs"][0].update(changes)
    return data


@pytest.mark.parametrize("changes,fragment", [
    ({"id": "Bad Id"}, "id"),
    ({"url": "http://insecure.example/x.7z"}, "HTTPS"),
    ({"archive": "rar"}, "archive"),
    ({"preset_name": "Accordion"}, "AbletonHelper"),
    ({"preset_name": "AbletonHelper a/b"}, "символы"),
    ({"sha256": "XYZ"}, "sha256"),
    ({"size_bytes": -1}, "size_bytes"),
    ({"license": {"name": "CC0"}}, "license"),
    ({"aliases": "accordion"}, "aliases"),
    ({"recipe_ids": ["no_such_recipe"]}, "no_such_recipe"),
    ({"verified": False}, "default=true"),
    ({"sha256": None}, "verified=true"),
    ({"name": ""}, "name"),
])
def test_validation_catches(changes, fragment):
    errors = validate_registry(mutated(**changes), {"bayan"})
    assert any(fragment in e for e in errors), errors


def test_duplicate_ids_and_preset_names_and_bad_shape():
    data = copy.deepcopy(DATA)
    data["packs"].append(copy.deepcopy(data["packs"][0]))
    errors = validate_registry(data)
    assert any("повторяется" in e for e in errors)
    assert validate_registry([]) and validate_registry({"packs": "x"})
    assert validate_registry({"packs": [5]})


def test_unverified_packs_are_allowed_when_not_default():
    p = mutated(verified=False, default=False, sha256=None, size_bytes=None)
    assert validate_registry(p) == []


def test_find_pack_by_alias_kind_and_recipe():
    from abhelper.samples import find_pack, load_registry
    packs = load_registry()
    for ident in ("accordion-hn", "accordion", "баян", "bayan", "Accordion"):
        p = find_pack(packs, ident)
        assert p is not None and p.id == "accordion-hn", ident
    assert find_pack(packs, "no-such-pack") is None
