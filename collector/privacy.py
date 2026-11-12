"""Private details in meeting transcript text (security review M1, privacy/transcript-private-addresses).

Residents give their home address (and now and then a phone number) at the start of public comment. The transcript
has no speaker tags, so these are found by pattern in the TEXT, everywhere in every transcript, and replaced before
anything is shown, quoted or matched (sitegen/transcripts.py load): the transcript page, the call-on excerpts on member
pages, and every other copy. The video still has them, so the placeholder tells the reader to hear it there; the line
keeps its time link.

What is masked (rules, each with the false positives it avoids):
- A street address: a house number, one to four street-name words, and a street suffix ("418 Example Court",
  "312 J.Q. Sample Boulevard", "205 47th Street", "1100 and 1110 Sample Road"). The house number is digits (at most
  five, Whisper may split it: "10 42 fixture drive", "nine 14 Example street") or two or more spelled-out number words
  ("four oh eight Example Court", "six or six sample street"). Never a dollar amount, a decimal, a number with a comma,
  a part of a hyphenated number (ordinance 17-2025-26) or an ordinal ("14th"); never a number after a word that
  names something else (ordinance, resolution, highway, ward, district, item, phase, "the" ...). A street-name word is
  never a function word, a unit or a number word ("90 cars to that road", "18 foot wide road", "the 2045 Example Creek
  Parkway", "9 Mile Example Road", "ordinance 37 fails councilman street").
- A house number someone says they live at, with no suffix: "I live at 640 samplewood since 2003", "my address is 515",
  up to the first function word or punctuation.
- A phone number: ten digits in 3-3-4 groups (any of space, ".", "-", "()" between them), seven digits as 3-4 joined by
  "-" or ".", or seven or more spelled-out digits in a row. Every phone number, official lines included: a list of
  "official" numbers would need checking against each body, and the video has them all.
Every example in this module is synthetic (invented names and streets, 555-01xx numbers), never a real transcript line.
Each rule errs toward masking: a street named in a zoning item read aloud is masked too (it is on the item's own pages).
"""
from __future__ import annotations

import re

ADDRESS_MASK = "[address omitted; hear it in the video at this time]"
PHONE_MASK = "[phone number omitted; hear it in the video at this time]"

_DIGIT_WORDS = "zero oh one two three four five six seven eight nine".split()
_NUMBER_WORDS = _DIGIT_WORDS + ("ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen "
                                "twenty thirty forty fifty sixty seventy eighty ninety hundred").split()
SUFFIXES = ("street", "st", "avenue", "ave", "road", "rd", "drive", "dr", "court", "ct", "lane", "ln", "boulevard",
            "blvd", "way", "place", "pl", "circle", "cir", "trail", "trl", "pike", "parkway", "pkwy", "highway", "hwy",
            "terrace", "cove", "alley", "square", "loop", "bend", "hollow", "ridge", "crossing")
# Words that are never part of a street's name: function words, units and counted things, number words, titles, and
# a few nouns that sit between a number and "road" / "street" / "way" in speech.
NOT_A_STREET_WORD = frozenset(_NUMBER_WORDS + """
a an the and or but nor so of to in on at by for from with without into onto off over under up down out about
around near past than then since until while because that this these those there here
it it's its is are was were be been being am
i i'm i've i'll i'd we we're we've you you're they're he she they them us our my your his her their me him
what which who whom whose when where why how if as also known like just only even still yet very really
not no yes do does did done have has had will would can could should may might must shall
each every other another more most less least many much few some any all both several different same whole
entire extra additional next last first second third half
foot feet mile miles acre acres inch inches yard yards meter meters percent per square
year years month months week weeks day days hour hours minute minutes second seconds time times
car cars truck trucks home homes house houses unit units lot lots people person kids children students
lane lanes way ways wheel wide long
k thousand million billion dollars dollar cents
ordinance ordinances resolution resolutions item items number numbers fails passes passed failed
council councilman councilwoman councilmember councilperson councillady mayor chair chairman chairwoman clerk
madam mister mr mrs ms dr sir
okay ok um uh yeah well
""".split())
# A number right after one of these words is not a house number.
NOT_AFTER = frozenset("""
ordinance ordinances resolution resolutions highway hwy route interstate us sr exit ward wards district districts
number no item items phase section chapter page pages case lot unit units the approximately about nearly almost
around over under than year years since
""".split())
CUES = r"(?:(?:live[sd]?|living|reside[sd]?|residing)\s+(?:at|on)|address\s+is)"

_NUM_WORD = r"(?:" + "|".join(_NUMBER_WORDS) + r")(?:-(?:" + "|".join(_DIGIT_WORDS[2:]) + r"))?"
_DIGITS = r"\d{1,5}(?![.,]\d)\b"
# One number token, atomic ((?>...), Python 3.11+): once a token has matched it is never re-split, so "twenty-two"
# is one token, not "twenty" + "-two" as well, and a long run of number words with no street after it fails in linear
# time instead of trying every split (privacy/mask-regex-redos). The word boundary is inside the group, so "sixteen"
# still matches as "sixteen" and not as "six".
_NUM_TOKEN = r"(?>" + _DIGITS + "|" + _NUM_WORD + r"\b)"
# a house number: number tokens (each atomic), Whisper may put "or" for "oh" between spelled ones ("five or five")
_NUM_SEQ = _NUM_TOKEN + r"(?:(?:[\s-]+|\s+or\s+)" + _NUM_TOKEN + r"){0,5}"
_NUMBERS = r"(?P<num>" + _NUM_SEQ + r"(?:\s*(?:,|and|&)\s*" + _NUM_SEQ + r")*)"
_WORD = (r"(?!(?:" + "|".join(sorted(NOT_A_STREET_WORD, key=len, reverse=True)).replace("'", "['’]")
         + r")\b(?!['’\w]))(?:(?:[A-Za-z]\.){1,3}(?!\w)|\d{1,3}(?:st|nd|rd|th)\b|[A-Za-z][A-Za-z'’-]*)")
_START = r"(?<![\w$#/.,'’-])"
ADDRESS = re.compile(_START + _NUMBERS + r"(?:\s+" + _WORD + r"){1,4}\s+(?:" + "|".join(SUFFIXES) + r")\b\.?", re.I)
_SUFFIX = r"(?:" + "|".join(SUFFIXES) + r")\b"
CUED = re.compile(r"\b" + CUES + r"\b[\s.,:]*" + _START + _NUMBERS + r"(?:\s+(?!" + _SUFFIX + r")" + _WORD + r"){0,3}"
                  + r"(?:\s+" + _SUFFIX + r")?", re.I)
_SEP = r"(?:\s*[.-]\s*|\s+)"
PHONE = re.compile(r"(?<![\w$.,-])(?:\(\s*\d{3}\s*\)\s*|\d{3}" + _SEP + r")\d{3}" + _SEP + r"\d{4}(?![\w-])(?!\s*[.,]?\s*\d)"
                   r"|(?<![\w$.,-])\d{3}[.-]\d{4}(?![\w-])(?![.,]\d)"
                   r"|\b(?:(?:" + "|".join(_DIGIT_WORDS) + r")[\s,-]+){6,}(?:" + "|".join(_DIGIT_WORDS) + r")\b", re.I)


def _house_number_ok(text: str, m: re.Match) -> bool:
    num = m.group("num")
    if not re.search(r"\d", num) and len(re.findall(_NUM_TOKEN, num, re.I)) < 2:
        return False      # one spelled-out word ("the four city court") is not a house number
    before = re.findall(r"[A-Za-z]+", text[max(0, m.start("num") - 30):m.start("num")])
    return not (before and before[-1].lower() in NOT_AFTER)


def spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, mask) of every address and phone number in the text, in order, never overlapping."""
    found = []
    for rx, mask in ((PHONE, PHONE_MASK), (ADDRESS, ADDRESS_MASK), (CUED, ADDRESS_MASK)):
        pos = 0
        while (m := rx.search(text, pos)) is not None:
            if mask == ADDRESS_MASK and not _house_number_ok(text, m):
                pos = m.start() + 1     # a later start inside the rejected match may still be an address
                continue
            a = m.start("num") if mask == ADDRESS_MASK else m.start()
            b = m.end()
            while b > a and text[b - 1] in " ,.":   # keep the sentence's own punctuation
                b -= 1
            kind = mask
            if mask == PHONE_MASK and not re.search(r"\d", m.group(0)) and re.search(r"\b(?:at|on)\W*$", text[:a], re.I):
                kind = ADDRESS_MASK     # "located at one two three four five six seven": a spelled-out house number
            found.append((a, b, kind))
            pos = m.end()
    found.sort()
    out: list[tuple[int, int, str]] = []
    for a, b, mask in found:
        if out and a < out[-1][1]:
            pa, pb, pm = out[-1]
            out[-1] = (pa, max(pb, b), pm)
        else:
            out.append((a, b, mask))
    return out


def mask(text: str) -> str:
    for a, b, m in reversed(spans(text)):
        text = text[:a] + m + text[b:]
    return text


def mask_segments(segments: list) -> tuple[list, list[int]]:
    """The transcript's segments [start, end, text] with every address and phone number masked, and the indexes of
    the segments that changed. The segments' texts are read joined by single spaces, so an address split over two
    lines ("My address is 418" / "Example Court") is found; each line it touches shows the placeholder for its part."""
    texts = [s[2] for s in segments]
    joined = " ".join(texts)
    found = spans(joined)
    if not found:
        return list(segments), []
    out, changed, pos = [], [], 0
    for i, (s, t) in enumerate(zip(segments, texts)):
        a0, b0 = pos, pos + len(t)
        pos = b0 + 1
        new, cur = [], a0
        for a, b, m in found:
            if b <= a0 or a >= b0:
                continue
            new.append(joined[cur:max(a, a0)])
            new.append(m)
            cur = min(b, b0)
        if not new:
            out.append(s)
            continue
        new.append(joined[cur:b0])
        out.append([s[0], s[1], "".join(new)])
        changed.append(i)
    return out, changed
