"""Pure-python retrieval over the knowledge base (docs/<collection>/*.md, format: docs/INTERFACES.md §6).

BM25 over section chunks. A collection is the name of the sub-folder of ``docs/`` (``help``, ``sound``,
``theory``). Russian/English tokenisation, light stemming, a stop-word list, a title / ``keywords:`` boost
and a RU<->EN synonym expansion (``synonyms.json``). The index is built lazily, once, and has no
third-party dependencies.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DOCS_DIR = Path(__file__).resolve().parent / "docs"
SYNONYMS_PATH = Path(__file__).resolve().parent / "synonyms.json"
DEFAULT_COLLECTION = "help"  # collection of markdown files lying directly in docs/ (legacy layout)
MAX_CHUNK_CHARS = 1200

# BM25 parameters and field weights (weighted term frequency: body + heading + title + keywords)
K1 = 1.4
B = 0.5
W_HEADING = 4.0
W_TITLE = 1.5
W_KEYWORDS = 0.6
SYNONYM_WEIGHT = 0.45
PREFIX_WEIGHT = 0.5

_WORD_RE = re.compile(r"[a-zа-я0-9]+(?:[-'][a-zа-я0-9]+)*", re.IGNORECASE)
_SOURCES_RE = re.compile(r"^\s*(источники|ссылки|литература|sources|references|links)\b", re.IGNORECASE)
_CYR_RE = re.compile(r"[а-я]")

STOPWORDS = frozenset("""
как что где это эти этот эта для при или про над под без как-то можно нужно надо хочу хотел хотела хотим
сделать делать сделай сделайте использовать пользоваться подскажи подскажите пожалуйста помоги помогите
чтобы если когда какой какая какие какое каких какую мне меня мой моя мои есть быть будет там тут его ее
так вот уже еще ещё очень тоже также только свой свою свои себя наш ваш они она оно мы вы мне нам вам
и в во на не но по до из за от то же ли бы да нет это этом этой этих того тот
the and for how what where when why can could should would does with from into that this these those
are was were has have you your use using make get want need please just also some any all not but
a an of to in on is it be as at by or if my me we
""".split())

# Russian inflection endings (longest first), stripped before prefix truncation
_RU_ENDINGS = sorted("""
ами ями ого его ому ему ыми ими ией ией ают яют ует уют ишь ешь ить еть ать ять оть уть ться тся
ов ев ей ам ям ах ях ом ем ую юю ая яя ое ее ые ие ый ий ой ым им ыx их ых ют ут ет ит ат ят ть ти ла ли ло на
а я ы и у ю е о ь й
""".split(), key=len, reverse=True)
_RU_PREFIX_LEN = 5


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    """Lower-cased word tokens (ё -> е); hyphenated words yield the whole word and its parts."""
    out: list[str] = []
    for m in _WORD_RE.finditer(normalize(text)):
        w = m.group(0)
        out.append(w)
        if "-" in w:  # "time-stretch" is findable as "time" and "stretch" too
            out.extend(p for p in w.split("-") if p)
    return out


def stem(word: str) -> str:
    """Light stemmer: Russian endings stripped + prefix truncation (~5 chars), English suffix stripping."""
    w = normalize(word)
    if not w:
        return w
    if _CYR_RE.search(w):
        if len(w) > 4:
            for end in _RU_ENDINGS:
                if w.endswith(end) and len(w) - len(end) >= 4:
                    w = w[: -len(end)]
                    break
        return w[:_RU_PREFIX_LEN]
    if len(w) <= 3 or w.isdigit() or any(c.isdigit() for c in w):
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ing") and len(w) > 5:
        w = w[:-3]
        if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
            w = w[:-1]
        return w
    if w.endswith("ed") and len(w) > 4:
        w = w[:-2]
        if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "lsz":
            w = w[:-1]
        return w
    if w.endswith(("sses", "xes", "ches", "shes")) and len(w) > 4:
        return w[:-2]
    if w.endswith("es") and len(w) > 4 and w[-3] not in "aeiou":
        return w[:-1]  # "scales" -> "scale"
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return w[:-1]
    if w.endswith("ly") and len(w) > 5:
        return w[:-2]
    return w


def _terms(text: str) -> list[str]:
    """Stemmed, stop-word-free index/query terms of ``text``."""
    return [stem(t) for t in tokenize(text) if t not in STOPWORDS and len(t) >= 2]


# --------------------------------------------------------------------------- synonyms
class _Synonyms:
    """Stem -> group ids for single words; normalized phrase -> group ids for multi-word terms."""

    def __init__(self, groups: list[list[str]]):
        self.group_terms: list[list[str]] = []  # group id -> stems to expand with
        self.by_stem: dict[str, set[int]] = defaultdict(set)
        self.phrases: list[tuple[str, int]] = []
        for gid, group in enumerate(groups):
            stems: list[str] = []
            for term in group:
                words = _WORD_RE.findall(normalize(term))
                if not words:
                    continue
                if len(words) == 1:  # one word (a hyphenated word stays whole: "side-chain")
                    s = stem(words[0])
                    self.by_stem[s].add(gid)
                    stems.append(s)
                else:  # multi-word term: only recognised as a phrase in the query
                    self.phrases.append((" " + " ".join(w.replace("-", " ") for w in words) + " ", gid))
            self.group_terms.append(list(dict.fromkeys(stems)))

    @classmethod
    def load(cls, path: Path = SYNONYMS_PATH) -> "_Synonyms":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            groups = [g for g in data.get("groups", []) if isinstance(g, list)]
        except (OSError, ValueError) as e:
            log.warning("knowledge: cannot load synonyms %s: %s", path, e)
            groups = []
        return cls(groups)


# --------------------------------------------------------------------------- chunks
@dataclass
class _Chunk:
    collection: str
    file: str
    title: str
    section: str
    text: str
    keywords: list[str] = field(default_factory=list)
    length: int = 0
    haystack: str = ""
    kw_phrases: list[str] = field(default_factory=list)
    head_terms: frozenset = frozenset()


class KnowledgeBase:
    def __init__(self, docs_dir: str | Path | None = None, synonyms: Path | None = None):
        self.docs_dir = Path(docs_dir) if docs_dir is not None else DEFAULT_DOCS_DIR
        self._synonyms_path = synonyms or SYNONYMS_PATH
        self._chunks: list[_Chunk] | None = None
        self._postings: dict[str, dict[int, float]] = {}
        self._df: dict[str, int] = {}
        self._avg_len = 1.0
        self._syn: _Synonyms | None = None

    # ------------------------------------------------------------------ loading
    @property
    def sections(self) -> list[_Chunk]:
        """All indexed chunks (the index is built on first access)."""
        self._ensure()
        return self._chunks or []

    def reload(self) -> None:
        """Drop the index; it is rebuilt on the next access."""
        self._chunks = None

    def collections(self) -> dict[str, int]:
        counts: Counter = Counter(c.collection for c in self.sections)
        return dict(sorted(counts.items()))

    def _ensure(self) -> None:
        if self._chunks is not None:
            return
        self._chunks = []
        self._postings = {}
        self._df = {}
        self._syn = _Synonyms.load(self._synonyms_path)
        if self.docs_dir.is_dir():
            for path in sorted(self.docs_dir.glob("*.md")):
                self._load_file(path, DEFAULT_COLLECTION)
            for sub in sorted(p for p in self.docs_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
                for path in sorted(sub.glob("*.md")):
                    self._load_file(path, sub.name)
        self._build_index()

    def _load_file(self, path: Path, collection: str) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            log.warning("knowledge: cannot read %s: %s", path, e)
            return
        assert self._chunks is not None
        self._chunks.extend(self._parse(collection, path.name, text))

    @staticmethod
    def _parse(collection: str, filename: str, text: str) -> list[_Chunk]:
        title = Path(filename).stem
        keywords: list[str] = []
        sections: list[tuple[str, list[str]]] = [("", [])]  # (heading, lines)
        seen_title = False
        in_code = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
            if not in_code:
                if not seen_title and line.startswith("# "):
                    title = line[2:].strip() or title
                    seen_title = True
                    continue
                if line.startswith("## "):
                    sections.append((line[3:].strip(), []))
                    continue
                m = re.match(r"^keywords\s*:\s*(.*)$", stripped, re.IGNORECASE)
                if m and len(sections) == 1:
                    keywords.extend(k.strip() for k in re.split(r"[,;]", m.group(1)) if k.strip())
                    continue
            sections[-1][1].append(line)

        out: list[_Chunk] = []
        kw_phrases = [" ".join(_terms(k)) for k in keywords]
        kw_phrases = [k for k in kw_phrases if k]
        for heading, lines in sections:
            body = "\n".join(lines).strip()
            if not body:
                continue
            for piece in _split_body(body):
                ch = _Chunk(collection=collection, file=filename, title=title, section=heading, text=piece,
                            keywords=list(keywords), kw_phrases=kw_phrases)
                ch.head_terms = frozenset(_terms(heading))
                ch.haystack = " " + " ".join(_terms(" ".join([title, heading, piece]))) + " "
                out.append(ch)
        return out

    def _build_index(self) -> None:
        chunks = self._chunks or []
        postings: dict[str, dict[int, float]] = defaultdict(dict)
        total_len = 0
        for cid, ch in enumerate(chunks):
            body_terms = _terms(ch.text)
            ch.length = max(len(body_terms), 1)
            total_len += ch.length
            wtf: Counter = Counter(body_terms)
            for t in _terms(ch.section):
                wtf[t] += W_HEADING
            for t in _terms(ch.title):
                wtf[t] += W_TITLE
            for t in {t for k in ch.keywords for t in _terms(k)}:
                wtf[t] += W_KEYWORDS
            for t, v in wtf.items():
                postings[t][cid] = v
        self._postings = dict(postings)
        self._df = {t: len(p) for t, p in postings.items()}
        self._avg_len = (total_len / len(chunks)) if chunks else 1.0

    # ------------------------------------------------------------------ query analysis
    def _analyze(self, query: str) -> list[dict]:
        """Query units: {"stem", "alts": {stem: weight}}. Each original term is a unit with its synonym alternatives."""
        assert self._syn is not None
        syn = self._syn
        toks = [t for t in dict.fromkeys(tokenize(query)) if t not in STOPWORDS and len(t) >= 2]
        stems = list(dict.fromkeys(stem(t) for t in toks))
        norm_query = " " + " ".join(_WORD_RE.findall(normalize(query))) + " "
        norm_query = norm_query.replace("-", " ")
        phrase_groups = {gid for ph, gid in syn.phrases if ph in norm_query}

        units: list[dict] = []
        used_groups: set[int] = set()
        for s in stems:
            alts: dict[str, float] = {}
            for gid in syn.by_stem.get(s, ()):
                used_groups.add(gid)
                for a in syn.group_terms[gid]:
                    if a != s and a not in stems:
                        alts[a] = SYNONYM_WEIGHT
            # unknown word: tolerate truncated / extended forms present in the index (>= 4 chars)
            if s not in self._postings and len(s) >= 4 and not s.isdigit():
                for term in self._postings:
                    if len(term) >= 4 and (term.startswith(s) or s.startswith(term)):
                        alts.setdefault(term, PREFIX_WEIGHT)
            units.append({"stem": s, "alts": alts})
        for gid in phrase_groups - used_groups:  # multi-word synonym phrase triggered on its own
            alts = {a: SYNONYM_WEIGHT for a in syn.group_terms[gid] if a not in stems}
            if alts:
                units.append({"stem": None, "alts": alts, "phrase": True})
        return units

    def _idf(self, term: str) -> float:
        n = len(self._chunks or [])
        df = self._df.get(term, 0)
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def _tf_norm(self, wtf: float, length: int) -> float:
        return wtf * (K1 + 1.0) / (wtf + K1 * (1.0 - B + B * length / self._avg_len))

    # ------------------------------------------------------------------ search
    def search(self, query: str, limit: int = 4, collection: str | None = None) -> list[dict]:
        """Top chunks for ``query``: ``{"collection","file","title","section","text","score"}``."""
        self._ensure()
        chunks = self._chunks or []
        if not chunks or not isinstance(query, str):
            return []
        col = collection.strip().lower() if isinstance(collection, str) and collection.strip() else None
        units = self._analyze(query)
        if not units:
            return []
        real_units = [u for u in units if u["stem"] is not None]
        n_real = max(len(real_units), 1)

        scores: dict[int, float] = defaultdict(float)
        covered: dict[int, int] = defaultdict(int)
        for u in units:
            cap = (self._idf(u["stem"]) if u["stem"] is not None else 2.5) * (K1 + 1.0)
            direct: dict[int, float] = {}
            if u["stem"] is not None:
                idf = self._idf(u["stem"])
                for cid, wtf in self._postings.get(u["stem"], {}).items():
                    direct[cid] = idf * self._tf_norm(wtf, chunks[cid].length)
            syn: dict[int, float] = defaultdict(float)
            for term, w in u["alts"].items():
                idf = self._idf(term)
                for cid, wtf in self._postings.get(term, {}).items():
                    syn[cid] += w * idf * self._tf_norm(wtf, chunks[cid].length)
            for cid in set(direct) | set(syn):
                d = direct.get(cid, 0.0)
                s = syn.get(cid, 0.0)
                # synonym hits add, but bounded: a long synonym list cannot outweigh a perfect match on the word
                scores[cid] += d + min(s, cap)
                if not u.get("phrase"):
                    covered[cid] += 1

        q_terms = [u["stem"] for u in real_units]
        q_phrase = " " + " ".join(q_terms) + " " if len(q_terms) > 1 else ""
        q_set = set(q_terms)
        ranked: list[tuple[float, int]] = []
        for cid, sc in scores.items():
            ch = chunks[cid]
            if col is not None and ch.collection != col:
                continue
            cov = covered[cid] / n_real
            sc *= 0.45 + 0.55 * min(cov, 1.0)
            if _SOURCES_RE.match(ch.section):  # reference lists match everything and answer nothing
                sc *= 0.35
            if ch.head_terms:  # the section heading speaks about what was asked
                hit = sum(1 for u in real_units if u["stem"] in ch.head_terms or any(a in ch.head_terms for a in u["alts"]))
                sc *= 1.0 + 0.5 * hit / n_real
            if q_phrase and q_phrase in ch.haystack:
                sc *= 1.25
            for k in ch.kw_phrases:  # a whole keyword phrase contained in the query is a strong signal
                if k and (" " + k + " ") in (" " + " ".join(q_terms) + " ") and (len(k) >= 4):
                    sc *= 1.2
                    break
            if q_set and all(t in ch.haystack for t in (" " + t + " " for t in q_set)) and len(q_set) > 1:
                sc *= 1.05
            ranked.append((sc, cid))
        ranked.sort(key=lambda x: (-x[0], chunks[x[1]].collection, chunks[x[1]].file, x[1]))

        results: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for sc, cid in ranked:
            ch = chunks[cid]
            key = (ch.collection, ch.file, ch.section)
            if key in seen:
                continue
            seen.add(key)
            results.append({"collection": ch.collection, "file": ch.file, "title": ch.title,
                            "section": ch.section, "text": ch.text, "score": round(sc, 3)})
            if len(results) >= max(0, int(limit)):
                break
        return results


# --------------------------------------------------------------------------- chunk splitting
def _split_body(body: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split a long section into pieces <= limit characters at paragraph (blank line) / line boundaries."""
    if len(body) <= limit:
        return [body]
    blocks: list[str] = []
    cur: list[str] = []
    in_code = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
        if not line.strip() and not in_code:
            if cur:
                blocks.append("\n".join(cur))
                cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    pieces: list[str] = []
    buf = ""
    for block in blocks:
        parts = [block]
        if len(block) > limit:  # a huge paragraph/table/code block: split by lines
            parts, acc = [], ""
            for line in block.splitlines():
                if acc and len(acc) + len(line) + 1 > limit:
                    parts.append(acc)
                    acc = ""
                while len(line) > limit:  # pathological single line
                    parts.append(line[:limit])
                    line = line[limit:]
                acc = f"{acc}\n{line}" if acc else line
            if acc:
                parts.append(acc)
        for part in parts:
            if buf and len(buf) + len(part) + 2 > limit:
                pieces.append(buf)
                buf = part
            else:
                buf = f"{buf}\n\n{part}" if buf else part
    if buf:
        pieces.append(buf)
    return pieces
