"""Which committee words may be published (docs/architecture/committee-words-invariant.md).

The invariant: every capitalised or single-letter token shown is on the roster, in `words`, or inside a `phrase`;
nothing else. (An allowed span counts as on the roster: a roster name, "<title> <roster name or surname>", an AYE/NAY
list of roster surnames, a date.)

The gate is an allow-list with one rule for every text from the minutes or the portal (a section heading, an item's
subject, a motion's words, an outcome sentence, an attendance note, a meeting title, a document name). Since the third
security review (`committees-privacy` hit 3) there is no separate rule for legislation: an ordinance or a resolution
passes the same rule as any other text. A text is published only when

1. it holds no format character, combining mark, private-use or unassigned character (a zero-width space could split
   a name into allowed pieces);
2. after the allowed spans and a leading upper-case Roman item number ("IV. ADOPTION OF MINUTES") are taken out, it
   holds no two single letters in a row with only spaces or periods between ("J. Q.", "J O H N D O E");
3. every token (a run of letters of any script; a possessive "'s" dropped) is
   - an allowed span or a phrase of `phrases`, or a word of `words` (any case), or
   - a Roman numeral right after Title, Chapter, Phase or Part ("Title VI"), or
   - when all lowercase: a word of `lowercase_only`, or
   - a lone single letter (any case);
   anything else, a capitalised word, an upper-case word or a word of a script without case above all, fails;
4. STRICT positions: the word after each preposition (to/for/of/with/by/from) and after each ":", "–", "—", " - "
   (a/an/the skipped) must be an allowed span or a word of `words`; a word of `lowercase_only` only when lowercase and
   an article came between; a lone letter never.

Everything else is withheld (None). The allow-list is config/localities/clarksville-tn/committee-words.yml.
qa/site_checks.py restates this rule on its own, more strictly (it must not import this module).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORDS_PATH = ROOT / "config" / "localities" / "clarksville-tn" / "committee-words.yml"
WORDS_NOTE = "Item words not shown (may name a private person); see the minutes"

PREPOSITIONS = {"to", "for", "of", "with", "by", "from"}
ARTICLES = {"a", "an", "the"}
MARKS = {":", ",", "–", "—", "-"}
STRICT_MARKS = {":", "–", "—", "-"}
ROMAN = re.compile(r"^(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii)$", re.I)
ROMAN_AFTER = {"title", "chapter", "phase", "part"}     # "Title VI", "Phase II": a Roman numeral only after these
# An agenda item number at the very start, upper case, with its period: "IV. ADOPTION OF MINUTES" (never "Vi.")
ITEM_NUMBER = re.compile(r"^(?:I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\.(?=\s)")
# A month is allowed only in a date ("May 26", "June 2nd", "June 2020") or naming a meeting ("the August meeting",
# "the April Finance Committee meeting"). March, April, May, June and August are names too, so they are not words
# (the other months are, in committee-words.yml).
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = (rf"(?:{MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?!\d)|(?:{MONTHS}),?\s+\d{{4}}|"
        rf"(?:{MONTHS})(?=(?:\s+[A-Za-z]+){{0,2}}\s+(?:meeting|mtg)\b)")
OK = "\x00"     # a span already allowed (a roster name, a phrase, an AYE list): one allowed token
L = r"[^\W\d_]"     # a letter, any script
TOKEN = re.compile(rf"\x00|{L}+(?:['’]{L}+)*|[:,–—]|(?<=\s)-(?=\s)")
# two or more single letters with only spaces or periods between ("J. Q.", "J O H N D O E", "Z.Q."), or any one or two
# other characters that are neither letters nor digits ("J/Q", "J-P", "J.-Q") (committees-privacy/lone-initial)
SINGLES = re.compile(rf"(?<!{L})(?<!['’]){L}(?:[\s.]+|[^\w\d]{{1,2}}|_{{1,2}}){L}(?!{L})(?!['’]{L})")
INITIAL_OK = {"A", "I"}     # a capital lone letter that is a word, not an initial
INITIAL = re.compile(rf"(?<![\w'’])(?P<i>{L})(?![\w'’])(?:[^\w{OK}]|_){{1,3}}(?P<w>{L}+)")
ODD = {"Cf", "Mn", "Mc", "Me", "Co", "Cn", "Cs"}     # format, combining, private-use, unassigned, surrogate


@dataclass(frozen=True)
class Allow:
    words: frozenset          # casefolded
    lowercase_only: frozenset
    phrases: tuple            # casefolded
    full_names: tuple         # casefolded roster names and aliases
    surnames: frozenset       # casefolded
    titles: tuple             # casefolded


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", s)).strip()


def parse_allow(raw: dict) -> Allow:
    full, sur = [], set()
    for o in raw["officials"]:
        for n in [o["name"], *(o.get("aliases") or [])]:
            full.append(_norm(n).casefold())
        sur.add(_norm(o["surname"]).casefold())
    low = {_norm(w).casefold() for w in raw.get("lowercase_only") or []}
    words = {_norm(w).casefold() for w in raw["words"]}
    clash = words & (low | sur)
    if clash:
        raise ValueError(f"committee-words.yml: in words and in lowercase_only/surnames: {sorted(clash)}")
    return Allow(words=frozenset(words), lowercase_only=frozenset(low),
                 phrases=tuple(sorted({_norm(p).casefold() for p in raw.get("phrases") or []}, key=len, reverse=True)),
                 full_names=tuple(sorted(set(full), key=len, reverse=True)), surnames=frozenset(sur),
                 titles=tuple(sorted({_norm(t).casefold() for t in raw["titles"]}, key=len, reverse=True)))


@lru_cache(maxsize=4)
def load_allow(path: Path = WORDS_PATH) -> Allow:
    return parse_allow(yaml.safe_load(path.read_text(encoding="utf-8")))


def _alt(items) -> str:
    return "|".join(re.escape(i).replace(r"\ ", r"\s+") for i in items)


@lru_cache(maxsize=4)
def _spans(allow: Allow) -> re.Pattern:
    """One pattern for every allowed span: a roster name, "<title> <roster name or surname>", an AYE/NAY list of
    surnames, a date, a phrase. Case-insensitive, whole words only (a letter of any script ends a word)."""
    sur = _alt(sorted(allow.surnames, key=len, reverse=True))
    parts = [rf"(?:{_alt(allow.full_names)})",
             rf"(?:{_alt(allow.titles)})\.?\s+(?:{_alt(allow.full_names)}|{sur})",
             rf"(?:AYES?|NAYS?)\s*:\s*(?:{sur})(?:\s*(?:,|\band\b)\s*(?:{sur}))*",
             DATE]
    if allow.phrases:
        parts.append(rf"(?:{_alt(allow.phrases)})")
    return re.compile(rf"(?i)(?<!{L})(?:" + "|".join(parts) + rf")(?:['’]s)?(?!{L})")


def _odd(text: str) -> bool:
    """A format character, combining mark, private-use or unassigned character: never published."""
    return any(unicodedata.category(c) in ODD for c in unicodedata.normalize("NFKC", text))


def _masked(text: str, allow: Allow) -> str:
    """The text with each allowed span, and a leading Roman item number, replaced by OK."""
    return _spans(allow).sub(f" {OK} ", ITEM_NUMBER.sub(OK, _norm(text)))


def _word(tok: str) -> str:
    return re.sub(r"['’]s$", "", tok).casefold()


def _walk(toks: list[str], allow: Allow) -> str | None:
    """Rules 3 and 4 above. Returns the first token that fails, None when all pass."""
    strict = after_article = False
    prev = None                  # the word before (casefolded), for "Title VI"
    for tok in toks:
        if tok in MARKS:
            strict, after_article, prev = tok in STRICT_MARKS, False, None
            continue
        w = _word(tok)
        if strict and w in ARTICLES:
            after_article, prev = True, w
            continue
        if tok == OK or w in allow.words or (ROMAN.match(w) and prev in ROMAN_AFTER):
            ok = True
        elif strict:
            ok = after_article and tok.islower() and w in allow.lowercase_only
        elif tok.islower():
            ok = w in allow.lowercase_only or len(w) == 1
        else:                       # capitalised, upper case, or a script without case
            ok = len(w) == 1
        if not ok:
            return tok
        strict, after_article, prev = tok != OK and w in PREPOSITIONS, False, (None if tok == OK else w)
    return None


def _initial(masked: str) -> str | None:
    """The first initial before a name: a capital lone letter other than A or I ("J. Bonds", "Settlement J. Bonds",
    "(J. East)"), then one to three characters that are neither letters, digits nor an allowed span, then a capitalised
    word that is not an allowed span. It fails whatever the words list holds (committees-privacy/lone-initial). A letter
    next to a digit ("E911", "K-9") is not one, nor a Roman numeral after Title, Chapter, Phase or Part."""
    for m in INITIAL.finditer(masked):
        i, w = m["i"], m["w"]
        if not i.isupper() or i in INITIAL_OK or not w[:1].isupper():
            continue
        before = re.search(rf"({L}+)[^\w{OK}]*$", masked[:m.start()])
        if ROMAN.match(i) and before and before[1].casefold() in ROMAN_AFTER:
            continue
        return i
    return None


def why_withheld(text: str | None, allow: Allow | None = None) -> str | None:
    """None when `text` may be published (the rule above; empty text too), else a short reason naming the rule that
    failed and the first word that failed it (for the build report only: it may quote a name, never committed)."""
    if not text or not text.strip():
        return None
    allow = allow or load_allow()
    if _odd(text):
        return "an invisible or combining character"
    masked = _masked(text, allow)
    if SINGLES.search(masked):
        return "single letters in a row"
    if _initial(masked):
        return "an initial before a name"
    bad = _walk(TOKEN.findall(masked), allow)
    return None if bad is None else f"not allow-listed: {bad!r}"


def publishable(text: str | None, allow: Allow | None = None) -> bool:
    """True when `text` may be published (the rule above). Empty text: True (nothing to withhold)."""
    return why_withheld(text, allow) is None


def roster_name(printed: str | None, allow: Allow | None = None) -> bool:
    """A printed name may be published: a roster name or alias, "<title> <roster surname>" or a roster surname."""
    if not printed:
        return True
    allow = allow or load_allow()
    if _odd(printed):
        return False
    n = _norm(printed)
    if _spans(allow).fullmatch(n):
        return True
    return n.casefold() in allow.surnames
