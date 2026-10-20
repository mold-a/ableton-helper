"""Pure-python search over the Ableton knowledge base (docs/*.md, format: docs/INTERFACES.md §6)."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DOCS_DIR = Path(__file__).resolve().parent / "docs"

_WORD_RE = re.compile(r"[a-zа-я0-9]+(?:[-'][a-zа-я0-9]+)*", re.IGNORECASE)

STOPWORDS = frozenset("""
как что где это эти этот эта для при или про над под без как-то можно нужно надо хочу хотел хотела
сделать делать сделай сделайте использовать пользоваться
чтобы если когда какой какая какие какое мне меня мой моя мои есть быть будет там тут его ее
the and for how what where when why can could should would does with from into that this these those
are was were has have you your use using make get want need
""".split())


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def tokenize(text: str) -> list[str]:
    out = []
    for m in _WORD_RE.finditer(normalize(text)):
        w = m.group(0)
        out.append(w)
        if "-" in w:  # "time-stretch" is findable as "time" and "stretch" too
            out.extend(p for p in w.split("-") if p)
    return out


def _match_strength(q: str, d: str) -> float:
    """1.0 exact; ~0.5-0.6 for prefix/morphological match (both >= 4 chars)."""
    if q == d:
        return 1.0
    lq, ld = len(q), len(d)
    if min(lq, ld) < 4:
        return 0.0
    if d.startswith(q) or q.startswith(d):
        return 0.6
    # shared stem (handles Russian endings: растяжение/растяжения, дорожка/дорожки)
    common = 0
    for a, b in zip(q, d):
        if a != b:
            break
        common += 1
    if common >= max(4, min(lq, ld) - 2) and min(lq, ld) >= 5:
        return 0.5
    return 0.0


@dataclass
class _Section:
    file: str
    title: str
    section: str
    text: str
    keywords: list[str] = field(default_factory=list)
    kw_tokens: set[str] = field(default_factory=set)
    kw_phrases: list[str] = field(default_factory=list)
    title_tokens: set[str] = field(default_factory=set)
    head_tokens: set[str] = field(default_factory=set)
    body_counts: Counter = field(default_factory=Counter)
    haystack: str = ""


class KnowledgeBase:
    def __init__(self, docs_dir: str | Path | None = None):
        self.docs_dir = Path(docs_dir) if docs_dir is not None else DEFAULT_DOCS_DIR
        self.sections: list[_Section] = []
        self.reload()

    # ------------------------------------------------------------------ loading
    def reload(self) -> None:
        self.sections = []
        if not self.docs_dir.is_dir():
            return
        for path in sorted(self.docs_dir.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                log.warning("knowledge: cannot read %s: %s", path, e)
                continue
            self.sections.extend(self._parse(path.name, text))

    @staticmethod
    def _parse(filename: str, text: str) -> list[_Section]:
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

        out: list[_Section] = []
        for heading, lines in sections:
            body = "\n".join(lines).strip()
            if not body:
                continue
            sec = _Section(file=filename, title=title, section=heading, text=body, keywords=list(keywords))
            sec.kw_phrases = [" ".join(tokenize(k)) for k in keywords]
            sec.kw_tokens = {t for k in keywords for t in tokenize(k)}
            sec.title_tokens = set(tokenize(title))
            sec.head_tokens = set(tokenize(heading))
            sec.body_counts = Counter(tokenize(body))
            sec.haystack = normalize(" ".join([title, heading, " ".join(keywords), body]))
            out.append(sec)
        return out

    # ------------------------------------------------------------------ search
    def search(self, query: str, limit: int = 4) -> list[dict]:
        q_tokens = [t for t in dict.fromkeys(tokenize(query)) if t not in STOPWORDS and len(t) >= 2]
        if not q_tokens or not self.sections:
            return []
        q_phrase = normalize(" ".join(tokenize(query)))
        scored: list[tuple[float, _Section]] = []
        for sec in self.sections:
            score = self._score(sec, q_tokens, q_phrase)
            if score > 0:
                scored.append((score, sec))
        scored.sort(key=lambda x: (-x[0], x[1].file, x[1].section))
        return [
            {"file": s.file, "title": s.title, "section": s.section, "text": s.text, "score": round(score, 3)}
            for score, s in scored[: max(0, int(limit))]
        ]

    @staticmethod
    def _best(token: str, pool) -> float:
        best = 0.0
        for d in pool:
            m = _match_strength(token, d)
            if m > best:
                best = m
                if best == 1.0:
                    break
        return best

    def _score(self, sec: _Section, q_tokens: list[str], q_phrase: str) -> float:
        total = 0.0
        matched = 0
        for t in q_tokens:
            kw = self._best(t, sec.kw_tokens)
            ti = self._best(t, sec.title_tokens)
            hd = self._best(t, sec.head_tokens)
            body_m = 0.0
            tf = 0
            if t in sec.body_counts:
                body_m, tf = 1.0, sec.body_counts[t]
            else:
                for d, c in sec.body_counts.items():
                    m = _match_strength(t, d)
                    if m > body_m:
                        body_m, tf = m, c
            s = max(kw * 2.0, ti * 1.5, hd * 3.0) + body_m * (1.0 + 0.3 * math.log(max(tf, 1)))
            if s > 0:
                matched += 1
                total += s
        if matched == 0:
            return 0.0
        coverage = matched / len(q_tokens)
        total *= 0.4 + 0.6 * coverage
        if len(q_tokens) > 1 and q_phrase in sec.haystack:
            total += 2.0
        # a whole keyword phrase appearing in the query ("как включить warp") is a strong signal
        for k in sec.kw_phrases:
            if len(k) >= 4 and k in q_phrase:
                total += 1.5
                break
        return total
