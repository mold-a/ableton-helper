"""Multilingual (RU/EN) query -> recipe scoring.

Russian morphology-lite: lowercase, ё -> е, strip common endings, prefix matching
(>= 4 chars), transliteration-insensitive comparison ("баян" == "bayan",
"бас" == "bass") and a tiny edit-distance tolerance for typos.
No external dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# ------------------------------------------------------------------ stop words
_STOP_RU = """
я хочу хочется хотел хотела хотелось бы мне мы сделай сделать создай создать создайте сделайте
добавь добавить дай нужен нужна нужно нужны надо как у в во на для с со из по и или а же ли типа
вроде похожий похожее похожа похожий звук звука звуки звуком звуку звуков тембр тембра
дорожку дорожка дорожки трек трека пожалуйста плиз такой такого чтобы что это эту этот мой моя
под про подобный типо будто какой какую какое хорошо стиле стиль стилю
инструмент инструмента играет играть сыграй звучит звучать звучание звучащий
""".split()
_STOP_EN = """
i want wanna would like to make create build add give me a an the some of for in on with please
sound sounds tone track instrument need as by from and or that this my style type kind something
similar patch into sort
""".split()
STOPWORDS = frozenset(_STOP_RU + _STOP_EN)

_TOKEN_RE = re.compile(r"[a-zа-я0-9]+")

# ------------------------------------------------------------------ normalisation
_RU_ENDINGS = tuple(sorted(
    [
        "ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ых", "их", "ах", "ях", "ов", "ев", "ей",
        "ой", "ый", "ий", "ая", "яя", "ое", "ее", "ые", "ие", "ом", "ем", "ам", "ям", "ою",
        "ею", "ую", "юю", "ы", "и", "а", "я", "о", "е", "у", "ю", "ь", "й",
    ],
    key=len, reverse=True,
))

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z", "и": "i",
    "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "iu", "я": "ia",
}


def normalize_text(text: str) -> str:
    return text.lower().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(text))


def _is_cyrillic(s: str) -> bool:
    return any("а" <= ch <= "я" for ch in s)


def stem(token: str) -> str:
    """Strip common Russian endings (twice, to handle -ля/-ль) and English plurals."""
    if not token or token.isdigit():
        return token
    if _is_cyrillic(token):
        t = token
        for _ in range(2):
            if len(t) <= 4:
                break
            for end in _RU_ENDINGS:
                if t.endswith(end) and len(t) - len(end) >= 3:
                    t = t[: -len(end)]
                    break
            else:
                break
        return t
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def skeleton(token: str) -> str:
    """Language-independent rough phonetic key (transliterate, fold c/k, y/i, doubles)."""
    t = "".join(_TRANSLIT.get(ch, ch) for ch in token)
    t = t.replace("ph", "f").replace("ck", "k").replace("ch", "x").replace("sh", "s")
    t = t.replace("c", "k").replace("q", "k").replace("w", "v").replace("y", "i").replace("j", "i")
    t = t.replace("h", "")
    return re.sub(r"(.)\1+", r"\1", t)


@dataclass(frozen=True)
class Tok:
    raw: str
    stem: str
    skel: str
    numeric: bool


@lru_cache(maxsize=4096)
def make_tok(raw: str) -> Tok:
    s = stem(raw)
    return Tok(raw, s, skeleton(s), raw.isdigit())


def make_toks(text: str, drop_stop: bool = True) -> list[Tok]:
    words = tokenize(text)
    kept = [w for w in words if w not in STOPWORDS] if drop_stop else words
    if not kept:
        kept = words
    return [make_tok(w) for w in kept]


def _lev(a: str, b: str, limit: int = 3) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def token_match(q: Tok, p: Tok) -> float:
    """Similarity of two tokens in [0, 1]."""
    if q.raw == p.raw or q.stem == p.stem:
        return 1.0
    if q.numeric or p.numeric:
        return 0.0
    if q.skel == p.skel:
        return 0.95
    best = 0.0
    for a, b in ((q.stem, p.stem), (q.skel, p.skel)):
        short, long_ = (a, b) if len(a) <= len(b) else (b, a)
        if len(short) >= 4 and long_.startswith(short):
            best = max(best, 0.85)
    if best:
        return best
    a, b = q.skel, p.skel
    if min(len(a), len(b)) >= 5:
        d = _lev(a, b)
        if d == 1:
            return 0.8
        if d == 2 and min(len(a), len(b)) >= 9:
            return 0.65
    return 0.0


def phrase_score(query: list[Tok], phrase: list[Tok]) -> float:
    """How well a phrase (an alias) is explained by the query, and vice versa."""
    if not query or not phrase:
        return 0.0
    cov_p = sum(max(token_match(q, p) for q in query) for p in phrase) / len(phrase)
    if cov_p == 0:
        return 0.0
    cov_q = sum(max(token_match(q, p) for p in phrase) for q in query) / len(query)
    return cov_p * (0.5 + 0.5 * cov_q)


# ------------------------------------------------------------------ recipe index
@dataclass
class _Entry:
    recipe_id: str
    phrases: list[tuple[list[Tok], float]]
    tag_toks: list[Tok]
    desc_toks: list[Tok]


def _as_text_list(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, str)]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def build_entry(recipe: dict) -> _Entry:
    phrases: list[tuple[list[Tok], float]] = []
    seen: set[tuple[str, ...]] = set()

    def add(text: str, weight: float) -> None:
        toks = make_toks(text)
        key = tuple(t.stem for t in toks)
        if toks and key not in seen:
            seen.add(key)
            phrases.append((toks, weight))

    for alias in _as_text_list(recipe.get("aliases")):
        add(alias, 1.0)
    for nm in _as_text_list(recipe.get("name")):
        add(nm, 0.98)
    rid = recipe.get("id") or ""
    if rid:
        add(rid.replace("_", " "), 0.9)

    tag_words: list[str] = []
    for tag in _as_text_list(recipe.get("tags")):
        tag_words += tokenize(tag)
    tag_words += tokenize(str(recipe.get("category", "")))
    tag_toks = [make_tok(w) for w in tag_words if w not in STOPWORDS]

    desc_words: list[str] = []
    for d in _as_text_list(recipe.get("description")):
        desc_words += tokenize(d)
    desc_toks = [make_tok(w) for w in set(desc_words) if w not in STOPWORDS and len(w) > 3]
    return _Entry(rid, phrases, tag_toks, desc_toks)


def _fraction_matched(query: list[Tok], pool: list[Tok], min_sim: float) -> float:
    if not query or not pool:
        return 0.0
    hit = sum(1 for q in query if any(token_match(q, p) >= min_sim for p in pool))
    return hit / len(query)


def score_entry(query: list[Tok], entry: _Entry) -> float:
    best = 0.0
    for toks, weight in entry.phrases:
        best = max(best, phrase_score(query, toks) * weight)
    extra = 0.2 * _fraction_matched(query, entry.tag_toks, 0.85)
    extra += 0.06 * _fraction_matched(query, entry.desc_toks, 0.85)
    return min(1.0, best + (1.0 - best) * extra)
