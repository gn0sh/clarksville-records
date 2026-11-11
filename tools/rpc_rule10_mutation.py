"""Mutation run for RPC motion rule 10 (docs/architecture/rpc-motion-invariant.md, `tests-not-pinning`).

Usage: python3 tools/rpc_rule10_mutation.py <tree>   (a copy of the repo at the commit under test, e.g. from
`git archive HEAD | tar -x -C <tree>`; never the working tree: the file is rewritten per mutant, then restored)
Deletes each SHAPES entry, each 10b tail trigger, each MEMBER_VOTE alternative, and each 10a order/mover-clause check
and 10c/10d attribution branch, one at a time, and runs the RPC reader tests. Prints a markdown table: every mutant
must be killed (at least one test fails)."""
import re
import subprocess
import sys
from pathlib import Path

tree = Path(sys.argv[1])
path = tree / "collector" / "rpc_minutes.py"
src = path.read_text(encoding="utf-8")
TESTS = ["collector/tests/test_rpc_rule10.py", "collector/tests/test_rpc_minutes.py"]
muts: list[tuple[str, str, str]] = []

# 10a: each SHAPES entry
block = src[src.index("SHAPES = (\n"):src.index("\n)\n", src.index("SHAPES = (\n"))]
for entry in re.findall(r'\n    \("[^"]+", "[^"]+",.*?\),(?=\n    \(|$)', block, re.S):
    label = re.match(r'\n    \("([^"]+)", "([^"]+)"', entry).group(2)
    muts.append((f"10a shape: {label}", entry, ""))
# 10b: each tail trigger (the entries of the TAIL_OUTCOME tuple, one at a time)
tail = src[src.index("TAIL_OUTCOME = ("):src.index("))", src.index("TAIL_OUTCOME = (")) + 2]
for label, item in (("OUTCOME", "OUTCOME, "), ("FAVOUR", "FAVOUR, "), ("motion", 're.compile(r"\\bmotion\\b", re.I), '),
                    ("moved", 're.compile(r"\\bmoved\\b", re.I),'),
                    ("seconded", ',\n                re.compile(r"\\bseconded\\b", re.I)')):
    assert tail.count(item) == 1, (label, tail)
    new = tail.replace(item, "")
    muts.append((f"10b tail trigger: {label}", tail, new))
# rpc-votes/outcome-words-swallow, tail-second-motion, outcome-other-motion (review of d76f361)
muts += [
    ("outcome words: free text instead of the vocabulary",
     'OUTCOME_WORDS = rf"{_TERM}(?:\\s+(?:(?:of|via)\\s+)?{_TERM})?"', "OUTCOME_WORDS = _FREE_WORDS_LATE"),
    ("body runs to an outcome-shaped sentence", "        if shaped and (body_end is None",
     "        if False and (body_end is None"),
    ("rule 9: a vote word after the 'in favor' sentence in the body",
     "\n                                             or LEFTOVER_VOTE.search(window, fav.end(), len(para))):", "):"),
    ("polarity: table / postpone / continue", "        if re.search(word, t):\n            return polarity",
     "        if False:\n            return polarity"),
    # review of 33e13a2: the mover's polarity, the table kinds, a lack of a second in the mover clause
    ("polarity: a mover naming no kind passes", "            if b and a != b:", "            if a and b and a != b:"),
    ("kind: table", '"Motion to table"),', '"Motion"),'),
    ("kind: postpone", '"Motion to postpone"),', '"Motion"),'),
    ("kind: continue", '"Motion to continue"),', '"Motion"),'),
    ("kind: table needs the verb", 'r"\\bto\\s+table\\b|\\btabling\\b"', 'r"\\btabl"'),
    ("polarity: an election or adjournment passing for approval", "_polarity(kind) or ELECT_ADJOURN.get(kind),",
     "_polarity(kind),"),
    ("10a mover clause: lack of a second", "                or LACK_OF_SECOND.search(own)", ""),
    # delta review of 92a0c69..24422eb: two kinds in the mover's words; table, postpone and continue apart
    ("kind: two kinds in the mover's words", "        if len(kinds) > 1:", "        if False:"),
    ("kind: two kinds shown under the first", "kind = kinds[0] if len(kinds) == 1 else MOTION_DEFAULT",
     "kind = next(iter(kinds), MOTION_DEFAULT)"),
    ("kind: recommend before another kind", "label for pattern, label in MOTION_KINDS if",
     "label for pattern, label in MOTION_KINDS + (RECOMMEND,) if"),
    ("kind: recommend alone", "return [RECOMMEND[1]] if re.search(RECOMMEND[0], words, re.I) else []", "return []"),
    ("kind holds: consent agenda", '"Motion to approve the consent agenda": frozenset({"Motion for approval"}),',
     '"Motion to approve the consent agenda": frozenset(),'),
    ("kind holds: minutes", '"Motion to approve the minutes": frozenset({"Motion for approval"}),',
     '"Motion to approve the minutes": frozenset(),'),
    ("kind holds: deferrals hold defer", 'frozenset({"Motion to defer", "Motion to withdraw",',
     'frozenset({"Motion to withdraw",'),
    ("kind holds: deferrals hold withdraw", 'frozenset({"Motion to defer", "Motion to withdraw",',
     'frozenset({"Motion to defer",'),
    ("kind holds: deferrals hold approval", '"Motion to withdraw",\n' + " " * 59 + '"Motion for approval"})}',
     '"Motion to withdraw"})}'),
    ("polarity: postpone is its own", '(r"\\bpostpon", "postpone")', '(r"\\bpostpon", "table")'),
    ("polarity: continue is its own", '(r"\\bcontinu", "continue")', '(r"\\bcontinu", "table")'),
]
# 10c: each MEMBER_VOTE alternative
mv_line = src[src.index("MEMBER_VOTE = ("):src.index(")\n", src.index("MEMBER_VOTE = (")) + 1]
for alt in re.findall(r'r"([^"]+)"', mv_line):
    new = (mv_line.replace(f'r"{alt}", ', "", 1) if f'r"{alt}", ' in mv_line
           else re.sub(r",\s*r\"" + re.escape(alt) + r"\"", "", mv_line))
    assert new != mv_line, alt
    muts.append((f"10c MEMBER_VOTE: {alt}", mv_line, new))
# 10a order and mover-clause checks; 10c/10d attribution branches
muts += [
    ("10a mover clause: titled name", "if (TITLED.search(own) or LEFTOVER_VOTE", "if (False or LEFTOVER_VOTE"),
    ("10a mover clause: vote word", "or LEFTOVER_VOTE.search(own) or EXCEPTION_WORD", "or EXCEPTION_WORD"),
    ("10a mover clause: exception word", "or EXCEPTION_WORD.search(own)\n", "\n"),
    ("10a mover clause: member surname", 'or any(re.search(rf"\\b{re.escape(n)}\\b", own) for n in surnames)):',
     "):"),
    ("10a mover clause: election exception", "    if not ELECT_CLAUSE.match(own):", "    if True:"),
    ("10a order: one second", '(ph == "second" and (seconds or phase > PHASE["second"]))', "False"),
    ("10a order: no vote after the outcome", '(ph == "vote" and phase > PHASE["vote"])', "False"),
    ("10a order: one outcome", '(ph == "outcome" and outcomes)', "False"),
    ("10a order: 'with' only after the outcome", '(ph == "with" and phase != PHASE["outcome"])', "False"),
    ("10a an outcome clause is required", 'if not listed or not (any(ph == "outcome" for ph, _, _ in clauses) or '
     '(oc is not None and oc is fav)):', "if not listed:"),
    ("10c attribution: lead abstention attributed", "            if own and attribute:", "            if False:"),
    ("10c attribution: own case only",
     "(x.group(\"case\") is None or (own_case is not None and named == own_case))", '(x.group("case") is None or True)'),
    ("10c attribution: first motion only", "attribute = case is not None and k == 0 and",
     "attribute = case is not None and"),
    ("10c attribution: case section only", "attribute = case is not None and k == 0 and", "attribute = k == 0 and"),
    ("10c attribution: disposing motion only", "attribute = case is not None and k == 0 and kind not in MEETING_BUSINESS",
     "attribute = case is not None and k == 0"),
    ("10c heading line is a sentence of its own", "cut = max(0, min(head_end, len(lead))) if k == 0 else 0", "cut = 0"),
    ("10c list scope: motionless case sections", "        if mv.kind in LIST_KINDS:", "        if False:"),
    ("10d list part in the lead", "            elif x and list_motion and named and named != own_case and named in agenda:",
     "            elif False:"),
    ("10d body: own case is read", "                if named is not None and named == case:\n                    continue",
     "                pass"),
    ("10d body: another listed case", "                if list_motion and named and named in agenda:",
     "                if False:"),
    ("10d body: list-part member written nowhere", " and n not in list_part]", "]"),
    ("10d body: another case on a caseless motion", "        elif other_case and WHY_OTHER_CASE not in reasons:",
     "        elif False:"),
]

rows = []
FREE = '_FREE_WORDS_LATE = r"[a-z](?:[a-z -]|\\d{1,3}(?=[\\s-]*days?\\b)){0,60}?"\n'
for name, old, new in muts:
    assert src.count(old) == 1, (name, src.count(old))
    mutant = src.replace(old, new)
    if "_FREE_WORDS_LATE" in new:
        mutant = mutant.replace("OUTCOME_WORDS = _FREE_WORDS_LATE", FREE + "OUTCOME_WORDS = _FREE_WORDS_LATE")
    path.write_text(mutant, encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
                       cwd=tree, capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or ["?"])[-1]
    failed = re.search(r"FAILED (\S+)", r.stdout)
    killer = failed.group(1).split("::")[-1] if failed else ("(error) " + last if r.returncode else "")
    if r.returncode and not failed:      # an import or syntax error is not a kill: the mutant is broken
        rows.append((name, "BROKEN", killer[:90]))
        continue
    rows.append((name, "killed" if r.returncode else "SURVIVED", killer[:90]))
path.write_text(src, encoding="utf-8")
print("| mutant | result | first failing test |\n|---|---|---|")
for row in rows:
    print("| " + " | ".join(row) + " |")
print(f"\n{sum(r[1] == 'killed' for r in rows)} of {len(rows)} killed")
