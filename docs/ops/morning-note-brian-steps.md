# Morning note: Brian's steps to the first send

The runbook with every reason is `docs/ops/morning-note.md`. This page is only your clicks, in order. It costs
nothing: Buttondown's free plan, no custom sending domain (the note goes out from Buttondown's own address for now).

Rules for every step:
- **The keys go in only two places:** the probe window (step 13) and the GitHub secret box (step 22). Never in chat,
  email, a file or a note.
- Buttondown's menu names here come from its documentation. The team has not seen your screens. If a name differs,
  pick the closest one and carry on.
- If a Buttondown screen asks you to **pay or upgrade**, stop at that step and tell the team which step. Do not pay.

## Session 1 (about 45 minutes, today): 24 steps

### A. The Daylight newsletter (the live one; nobody can sign up yet)
1. Open https://buttondown.com/register. Sign up with **brian@gnoshcodes.com**. Username: **daylight** (if taken,
   **daylightnews**). Write down the username you got: the probe asks for it.
   You should see: the Buttondown dashboard.
2. If it asks for a plan, pick **Free**.
   You should see: the dashboard, no payment form.
3. Settings > **Basics** (or **Newsletter**): Name **Daylight**. Nothing else in the name (no "City", "County" or "official"). **Save**.
4. Settings > **Subscribing**: turn **Double opt-in** on. **Save**.
5. Settings > **Tracking**: turn **Open tracking** off and **Click tracking** off. **Save**.
6. Settings > **Email** (or **Sending**): **Reply-to** = **brian@gnoshcodes.com**. **Save**.
7. Settings > **Metadata** (or **Subscriber fields** / **Custom fields**): add three fields, `lists`
   (multi-select, choices `zoning`, `seats`, `budget`, `contracts`), `district`, `ward`. **Save**.
   If there is no such page, skip this step. The probe checks whether the form saves these fields anyway.
   (No longer needed, 2026-11-17: the free plan refused these fields on a new sign-up, so the form posts tags.)

### B. A test newsletter for the probe
8. Open the newsletter menu (your newsletter's name, top left) > **Create a new newsletter**. Name **Daylight test**,
   username **daylight-test** (or anything free; write it down).
   You should see: the empty dashboard of **Daylight test**.
   If this asks you to pay: don't. Do only steps 16 to 21 (GitHub), then tell the team "test newsletter costs money".
   The probe never runs on the Daylight newsletter.
9. In **Daylight test**: Settings > **Subscribing** > **Double opt-in** on. **Save**.
10. In **Daylight test**: Settings > **Tracking** > both off. **Save**.
11. In **Daylight test**: Settings > **API** > **New API key** (or **Create key**). Name `probe`. Permissions:
    **Emails: Write**, **Sending: Write**, **Subscribers: Write**, every other area **None**. **Create**. Keep this
    page open: you copy the key in step 13.
    If there are no permission choices (only one key for everything), carry on, and tell the team "no scoped keys".

### C. Run the probe (about 15 minutes; you need three team addresses whose inboxes you can open now)
Three addresses, for example `brian+probe1@gnoshcodes.com`, `brian+probe2@gnoshcodes.com`,
`brian+probe3@gnoshcodes.com` (if your mail ignores the `+...` part, use any three team addresses you can read).
12. Download both files into your **Downloads** folder: open each link, click the **Download raw file** button
    (the down-arrow icon at the top right of the file).
    - https://github.com/gn0sh/clarksville-records/blob/49a45fe2f5d2b73a1870ba7d6a6b074ad7f5248a/scripts/morning-note-probe.cmd
    - https://github.com/gn0sh/clarksville-records/blob/49a45fe2f5d2b73a1870ba7d6a6b074ad7f5248a/scripts/morning-note-probe.ps1
13. In **Downloads**, double-click **morning-note-probe.cmd**. If Windows shows "Windows protected your PC", click
    **More info** > **Run anyway**. When it asks for the key: copy the key from the Buttondown page (step 11), click
    the black window, press **Ctrl+V**, then **Enter** (nothing shows; that is right). Then type what it asks: the
    three addresses, the **test** username, the **Daylight** username.
    It runs about 12 minutes by itself. It asks you once to click a confirm link if a test address needs it, and at
    the end asks 7 yes/no questions about which "Daylight probe" emails arrived.
    You should see: "Results saved to: ...\Documents\App Development\morning-note-probe-results-....json" (that is
    OneDrive > Documents > App Development).
    and a yellow line telling you the **Subscribers** setting for the live key. Write that word down (WRITE or READ).
    If the yellow line says "Neither sending mode passed": stop here and tell the team; skip to step 16.
14. In **Daylight test**: Settings > **API** > delete the `probe` key.
    You should see: no key listed.

### D. The live key (Daylight newsletter)
15. Switch to **Daylight** (newsletter menu, top left) > Settings > **API** > **New API key**. Name `github-morning-note`.
    Permissions: **Emails: Write**, **Sending: Write**, **Subscribers:** the word from step 13 (Write or Read), every
    other area **None**. **Create**. Keep this page open for step 22. Do not copy it anywhere else.

### E. GitHub: protect `main` (web clicks)
16. Open https://github.com/gn0sh/clarksville-records/settings/rules > **New ruleset** > **New branch ruleset**.
17. **Ruleset name**: `main: pull request required`. **Enforcement status**: **Active**.
18. **Bypass list** > **Add bypass**. If **GitHub Actions** is in the list: tick it, pick **Always**, **Add selected**.
    If it is **not** in the list: click **Cancel** at the top, do not create the ruleset, tell the team
    "no Actions bypass", and go to step 20. (Without that bypass the daily update could not save its data.)
19. **Target branches** > **Add target** > **Include default branch**. Under **Rules** tick **Restrict deletions**,
    **Block force pushes** and **Require a pull request before merging** (Required approvals: **0**). Leave the rest.
    Click **Create**.
    You should see: the ruleset listed as **Active**.

### F. GitHub: the morning-note environment and its key
20. Open https://github.com/gn0sh/clarksville-records/settings/environments > **New environment** > name
    `morning-note` > **Configure environment**.
21. **Deployment branches and tags** > **Selected branches and tags** > **Add deployment branch or tag rule** >
    type `main` > **Add rule**.
22. **Environment secrets** > **Add environment secret**. Name `BUTTONDOWN_API_KEY`. Value: copy the live key from
    the Buttondown page (step 15) and paste it here. **Add secret**.
    You should see: `BUTTONDOWN_API_KEY` listed, updated "now". Close the Buttondown key page.
23. Press **Win+V** > **Clear all** (empties the clipboard history, which may still hold both keys).
    You should see: "Nothing here" (or the clipboard panel empty). Do **not** add `MORNING_NOTE_SEND` yet (Session 2).
24. Tell the team in one line: "probe done" (plus any of: "no scoped keys", "no Actions bypass", or the step where
    Buttondown asked to pay). The results file is already in OneDrive > Documents > App Development.

## Waits for the team (no action from you)
- The team reads the probe results and merges its pull requests: the sending mode, the site's own address in the
  email link list, the sign-up form switched on (posting Buttondown tags; no canary week, Brian 2026-11-16: the note
  goes to every confirmed subscriber), and last the `MAIN_PR_BASELINE` pull request.
- The team sends you one sample note to approve (`morning-note-sample/` in the project files).
- Tomorrow's 3:07 AM daily update proves the ruleset still lets it save data (step 18).

## Session 2 (about 10 minutes, after the team says "ready for Session 2"; Tuesday Nov 17)
25. Open https://daylight.gnoshcodes.com/alerts.html#note. Tick all four lists, type **brian@gnoshcodes.com**, click
    **Send me the morning note**.
    You should see: a Buttondown page (address bar starts `https://buttondown.com/`). Tell the team if it is anything else.
26. Open the confirm email from Buttondown and click its link.
    You should see: Buttondown's "you're subscribed" page.
27. In Buttondown (**Daylight**) > **Subscribers** > click **brian@gnoshcodes.com**.
    You should see: tags `note-zoning`, `note-seats`, `note-budget` and `note-contracts` (and `note-district-<n>`,
    `note-ward-<n>` if your seats were saved on the site). Tell the team which tags you see, or "no tags".
28. (Removed 2026-11-16: no canary week, so no `MORNING_NOTE_CANARY_IDS` secret is needed.)
29. **This is the go-ahead to send to every confirmed subscriber** (hard stop 1; the team asks you for it at that
    time, after you approved the sample note and step 27 showed the tags). Open
    https://github.com/gn0sh/clarksville-records/settings/variables/actions > **New repository variable** > name
    `MORNING_NOTE_SEND`, value `true` > **Add variable**.
    You should see: `MORNING_NOTE_SEND` listed. The first note arrives by 7:00 AM the next morning on a day when
    something on your lists is new (nothing on a quiet day).

**To stop all sending at any time:** https://github.com/gn0sh/clarksville-records/settings/variables/actions >
`MORNING_NOTE_SEND` > **Delete**.
