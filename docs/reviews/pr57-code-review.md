# PR #57 code review (4d954c8b): REQUEST CHANGES
must-fix v1-probe/u3-false-pass-on-pr-eval-pass: PASS accepted suite bypass + pull_request pass (= FAIL-RULE shape); fixture built that way. Fix: PASS only suite bypass + pull_request fail + active.
should: v1-probe/ps1-never-executed (rehearse mode or Windows job); v1-probe/doc-pass-row-contradicts (u3 doc :48, arch :166); main-protect/window-over-20-min (wall clock, refuse if start+30 overlaps 08:00-10:30).
nits: main-protect/r1pp-not-monotone (doc caveat); sh TSV IFS collapse; grep -m1 SIGPIPE; BACKUP line not printed.
Sound: restore on every exit after first write (both scripts); backup == R1'; whitelist exact; R1'' == ADR decision 5; PS 5.1 basics; jq twins match; 63 tests pass.

## Delta (191ef247): APPROVE WITH NITS. All 8 closed; verdict logic agreed (eval pass = FAIL-RULE either suite). Nit doc 07:30 window: fixed in 6b0c95d.
