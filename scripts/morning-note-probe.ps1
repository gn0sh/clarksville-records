# Morning note: the T4.0 provider probe (docs/ops/morning-note.md section 3; docs/tasks/morning-note.md T4.0, T4.4).
#
# Brian runs this once, on his Windows PC, against the TEST Buttondown newsletter only, with team addresses only.
# Double-click scripts\morning-note-probe.cmd (or: powershell -NoProfile -ExecutionPolicy Bypass -File morning-note-probe.ps1).
#
# What it does: asks for the test newsletter's API key without showing it, makes the calls the sender makes
# (subscribers, metadata, draft / scheduled / filtered emails, send-draft, the public sign-up form), asks a few
# yes/no questions about what arrived in the team inboxes, then writes the answers to a results file in
#   Documents\App Development\ (OneDrive > Documents > App Development; the Desktop if that folder is not there).
# The results hold answers only: yes/no, HTTP status codes, field names, counts. Never the key, an address or an id.
# The key is never printed, logged or written anywhere; it is only sent to https://api.buttondown.com.
# It sends at most 2 emails, to the two team addresses you type (one each). Takes about 12 minutes.
# Guard: before any write it lists the newsletter's subscribers and stops if anyone but the typed team addresses is
# on it (so it cannot run on a newsletter with real subscribers). The comparison is in memory only.
#
# Windows PowerShell 5.1 compatible (no ?? or ternary, no -AsHashtable). Untested against the live API (the team's
# sandbox cannot reach buttondown.com): every check that cannot run says so in the results instead of guessing.

param([string]$OutDir = '')

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.Net.Http

$Api = 'https://api.buttondown.com/v1'
$FormBase = 'https://buttondown.com/api/emails/embed-subscribe/'
$IdRe = '^[A-Za-z0-9_-]{1,64}$'
$StampField = 'subscriber.metadata.note_edition'   # sender/deliver.py STAMP_FIELD

$R = [ordered]@{}          # the results file: answers only
$Secrets = New-Object System.Collections.Generic.List[string]   # every value that must never reach the results
$Created = New-Object System.Collections.Generic.List[string]   # probe emails to delete at the end
$Seen = [ordered]@{ ctypes = @{}; max_bytes = 0; ids_ok = $true; ids_seen = 0; retry_after = @(); paid = @() }
$script:key = $null

function Say($text) { Write-Host $text }
function Step($text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }

function Clean([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s -replace '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+', '<address>'
    $s = $s -replace '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', '<id>'
    $s = $s -replace '[A-Za-z0-9_\-]{24,}', '<token>'
    foreach ($x in $Secrets) { if ($x) { $s = $s.Replace($x, '<hidden>') } }
    if ($s.Length -gt 200) { $s = $s.Substring(0, 200) + '...' }
    return $s
}

function Has($o, [string]$name) {
    return ($null -ne $o) -and ($o.PSObject.Properties.Name -contains $name)
}

function Canon($o) {
    # One canonical JSON text, keys sorted, so "what was sent" and "what came back" compare exactly.
    if ($null -eq $o) { return 'null' }
    if ($o -is [string]) { return (ConvertTo-Json -InputObject $o -Compress) }
    if ($o -is [bool]) { if ($o) { return 'true' } else { return 'false' } }
    if ($o -is [int] -or $o -is [long] -or $o -is [double] -or $o -is [decimal]) { return [string]$o }
    if ($o -is [System.Collections.IDictionary]) {
        $parts = @()
        foreach ($k in ($o.Keys | Sort-Object)) { $parts += ((ConvertTo-Json -InputObject ([string]$k) -Compress) + ':' + (Canon $o[$k])) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($o.GetType().Name -eq 'PSCustomObject') {
        $parts = @()
        foreach ($k in ($o.PSObject.Properties.Name | Sort-Object)) { $parts += ((ConvertTo-Json -InputObject ([string]$k) -Compress) + ':' + (Canon $o.$k)) }
        return '{' + ($parts -join ',') + '}'
    }
    if ($o -is [System.Collections.IEnumerable]) {
        $parts = @()
        foreach ($i in $o) { $parts += (Canon $i) }
        return '[' + ($parts -join ',') + ']'
    }
    return (ConvertTo-Json -InputObject $o -Compress)
}

function Note-Id($id) {
    if ($null -eq $id) { return }
    $s = [string]$id
    $Secrets.Add($s) | Out-Null
    $Seen.ids_seen++
    if ($s -notmatch $IdRe) { $Seen.ids_ok = $false }
}

$handler = New-Object System.Net.Http.HttpClientHandler
$handler.AllowAutoRedirect = $false            # the sender follows no redirect; the form check reads the Location
$client = New-Object System.Net.Http.HttpClient($handler)
$client.Timeout = [TimeSpan]::FromSeconds(30)

function Send-Raw([string]$Method, [string]$Url, $Content, [hashtable]$Headers) {
    Start-Sleep -Milliseconds 1100             # polite: about one request a second
    $req = New-Object System.Net.Http.HttpRequestMessage((New-Object System.Net.Http.HttpMethod($Method)), $Url)
    if ($Headers) { foreach ($h in $Headers.Keys) { [void]$req.Headers.TryAddWithoutValidation($h, $Headers[$h]) } }
    if ($null -ne $Content) { $req.Content = $Content }
    try {
        $resp = $client.SendAsync($req).GetAwaiter().GetResult()
    } catch {
        return [pscustomobject]@{ Status = 0; CType = ''; Data = $null; Text = ''; Location = ''; RetryAfter = $null }
    }
    $status = [int]$resp.StatusCode
    $ctype = ''
    if ($resp.Content -and $resp.Content.Headers.ContentType) { $ctype = [string]$resp.Content.Headers.ContentType.MediaType }
    $text = ''
    if ($resp.Content) { $text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult() }
    $loc = ''
    if ($resp.Headers.Location) { $loc = [string]$resp.Headers.Location }
    $ra = $null
    if ($resp.Headers.RetryAfter) {
        if ($resp.Headers.RetryAfter.Delta) { $ra = 'seconds' } elseif ($resp.Headers.RetryAfter.Date) { $ra = 'http-date' } else { $ra = 'other' }
    }
    $data = $null
    if ($text -and $ctype -eq 'application/json') { try { $data = $text | ConvertFrom-Json } catch { $data = $null } }
    return [pscustomobject]@{ Status = $status; CType = $ctype; Data = $data; Text = $text; Location = $loc; RetryAfter = $ra }
}

function Bd([string]$Method, [string]$Path, $Body = $null, [string]$Idem = '', [string]$Label = '') {
    # One API call with the key. $Path starts with /. $Label names the call in the results (never an id).
    $url = $Api + $Path
    if ($Path -match '^https://') { $url = $Path }
    $h = @{ 'Authorization' = "Token $script:key"; 'Accept' = 'application/json'; 'User-Agent' = 'daylight-probe/1' }
    if ($Idem) { $h['X-Idempotency-Key'] = $Idem }
    $content = $null
    if ($null -ne $Body) {
        $json = ConvertTo-Json -InputObject $Body -Depth 10 -Compress
        $content = New-Object System.Net.Http.StringContent($json, [System.Text.Encoding]::UTF8, 'application/json')
    }
    $r = Send-Raw $Method $url $content $h
    if ($r.Status -eq 429) {
        $Seen.retry_after += [string]$r.RetryAfter
        Start-Sleep -Seconds 20
        $r = Send-Raw $Method $url $content $h
    }
    if ($r.Text) {
        $ct = $r.CType; if (-not $ct) { $ct = '(none)' }
        $Seen.ctypes[$ct] = 1 + [int]$Seen.ctypes[$ct]
        if ($r.Text.Length -gt $Seen.max_bytes) { $Seen.max_bytes = $r.Text.Length }
    }
    if ($r.Status -eq 402 -or (($r.Status -eq 403) -and ($r.Text -match '(?i)upgrade|plan|paid|billing|subscription|premium'))) {
        $Seen.paid += ("$Label -> HTTP $($r.Status): " + (Clean $r.Text))
    }
    return $r
}

function Ask-YesNo([string]$q) {
    while ($true) {
        $a = (Read-Host "$q  (y = yes, n = no, s = skip / not sure)").Trim().ToLower()
        if ($a -in @('y', 'yes')) { return 'yes' }
        if ($a -in @('n', 'no')) { return 'no' }
        if ($a -in @('s', 'skip', '')) { return 'not answered' }
    }
}

function Listing([string]$Path, [string]$Label) {
    # Every page of a listing, with the shape checks of T4.4 items 1-2. Returns rows and facts.
    $rows = @(); $url = $Api + $Path; $pages = 0; $count = $null; $shape = $true; $sameCount = $true; $nextAbs = 'no next link seen'
    while ($url -and $pages -lt 20) {
        $r = Bd 'GET' $url $null '' $Label
        $pages++
        if ($r.Status -ne 200 -or -not (Has $r.Data 'results')) {
            return [pscustomobject]@{ Ok = $false; Status = $r.Status; Rows = $rows; Pages = $pages; Count = $count; Shape = $false; SameCount = $sameCount; NextAbsolute = $nextAbs }
        }
        if (-not (Has $r.Data 'count') -or -not (Has $r.Data 'next')) { $shape = $false }
        $c = $null; if (Has $r.Data 'count') { $c = $r.Data.count }
        if ($null -ne $count -and $c -ne $count) { $sameCount = $false }
        $count = $c
        $rows += @($r.Data.results)
        $nxt = $null; if (Has $r.Data 'next') { $nxt = $r.Data.next }
        if ($nxt) {
            if ([string]$nxt -match '^https://api\.buttondown\.com/v1/') { $nextAbs = 'yes' } else { $nextAbs = 'no (' + (Clean ([string]$nxt -replace '\?.*$', '')) + ')'; break }
            $url = [string]$nxt
        } else { $url = $null }
    }
    return [pscustomobject]@{ Ok = $true; Status = 200; Rows = $rows; Pages = $pages; Count = $count; Shape = $shape; SameCount = $sameCount; NextAbsolute = $nextAbs }
}

function Find-Subscriber([string]$address) {
    # By address in the path first; if the API does not take an address there, from the full listing.
    $r = Bd 'GET' ('/subscribers/' + [Uri]::EscapeDataString($address)) $null '' 'GET /subscribers/{address}'
    if ($r.Status -eq 200 -and (Has $r.Data 'id')) { return $r.Data }
    $l = Listing '/subscribers' 'GET /subscribers'
    foreach ($row in $l.Rows) {
        $e = ''
        if (Has $row 'email_address') { $e = [string]$row.email_address } elseif (Has $row 'email') { $e = [string]$row.email }
        if ($e -and $e.ToLower() -eq $address.ToLower()) { return $row }
    }
    return $null
}

function Ensure-Subscriber([string]$address, [string]$which) {
    $r = Bd 'POST' '/subscribers' @{ email_address = $address; type = 'regular' } '' 'POST /subscribers'
    $R["create_subscriber_$which"] = "HTTP $($r.Status)"
    if (($r.Status -eq 400 -or $r.Status -eq 422) -and ($r.Text -match '(?i)email_address') -and ($r.Text -notmatch '(?i)already|exist')) {
        $r = Bd 'POST' '/subscribers' @{ email = $address; type = 'regular' } '' 'POST /subscribers (email field)'
        $R["create_subscriber_$which"] += " then HTTP $($r.Status) with field 'email'"
    }
    $row = $null
    if (($r.Status -eq 200 -or $r.Status -eq 201) -and (Has $r.Data 'id')) { $row = $r.Data } else { $row = Find-Subscriber $address }
    if ($null -eq $row) { return $null }
    Note-Id $row.id
    if ((Has $row 'type') -and $row.type -ne 'regular') {
        Say "The $which address is '$($row.type)', not confirmed yet. Open that inbox, click the confirm link in the email from Buttondown, then come back."
        [void](Read-Host 'Press Enter when it is confirmed')
        $again = Bd 'GET' ('/subscribers/' + $row.id) $null '' 'GET /subscribers/{id}'
        if ($again.Status -eq 200) { $row = $again.Data }
    }
    $t = '(no type field)'; if (Has $row 'type') { $t = [string]$row.type }
    $R["subscriber_${which}_type"] = $t
    return $row
}

function Email-Payload([string]$subject, [string]$body, [string]$status, $meta, $filters, [string]$publish) {
    $p = [ordered]@{ subject = $subject; body = $body; status = $status; archival_mode = 'disabled'; metadata = $meta }
    if ($null -ne $filters) { $p['filters'] = $filters }
    if ($publish) { $p['publish_date'] = $publish }
    return $p
}

function Echo-Check($sent, $resp, [bool]$wantFilters) {
    # T4.4 item 7: 200/201 with id, status, metadata and filters as sent; an ids draft has no filters (or null).
    if (-not ($resp.Status -eq 200 -or $resp.Status -eq 201)) { return "no: HTTP $($resp.Status) " + (Clean $resp.Text) }
    $d = $resp.Data
    $miss = @(); foreach ($k in @('id', 'status', 'metadata')) { if (-not (Has $d $k)) { $miss += $k } }
    if ($miss.Count) { return 'no: missing ' + ($miss -join ', ') }
    $out = @()
    if ($d.status -ne $sent.status) { $out += "status came back '$($d.status)' for '$($sent.status)'" }
    if ((Canon $d.metadata) -ne (Canon $sent.metadata)) { $out += 'metadata differs' }
    if ($wantFilters) {
        if (-not (Has $d 'filters')) { $out += 'no filters key' }
        elseif ((Canon $d.filters) -ne (Canon $sent.filters)) { $out += 'filters differ (shape seen: ' + (Clean ((Canon $d.filters) -replace '"value":"[^"]*"', '"value":"..."')) + ')' }
    } elseif ((Has $d 'filters') -and $null -ne $d.filters) {
        $out += 'an ids draft came back with filters: ' + (Clean ((Canon $d.filters) -replace '"value":"[^"]*"', '"value":"..."'))
    }
    if ($out.Count) { return "HTTP $($resp.Status), no: " + ($out -join '; ') }
    return "yes (HTTP $($resp.Status))"
}

function Count-Fields($d) {
    # Numeric fields of an email whose names say recipients or deliveries: who a filtered email reached.
    $o = [ordered]@{}
    if ($null -eq $d) { return $o }
    foreach ($p in $d.PSObject.Properties) {
        if ($p.Name -match '(?i)recipient|deliver|count|sent') {
            if ($p.Value -is [int] -or $p.Value -is [long] -or $p.Value -is [double]) { $o[$p.Name] = $p.Value }
        }
    }
    return $o
}

function Write-Results {
    $R['manual_items_not_automated'] = @(
        'Which status sends at once (the sender never uses one; not tested so no extra email is sent)',
        'Which features need a paid plan: anything Buttondown showed you is in manual_paid_screens; API refusals are in paid_feature_refusals'
    )
    $R['content_types_seen'] = $Seen.ctypes
    $R['largest_answer_bytes'] = $Seen.max_bytes
    $R['T4.4-12 ids fit [A-Za-z0-9_-]{1,64}'] = $(if ($Seen.ids_seen -eq 0) { 'no ids seen' } elseif ($Seen.ids_ok) { "yes ($($Seen.ids_seen) seen)" } else { 'no' })
    $R['T4.4-10 Retry-After forms seen'] = $(if ($Seen.retry_after.Count) { $Seen.retry_after -join ', ' } else { 'no 429 seen' })
    $R['paid_feature_refusals'] = $Seen.paid
    $dir = $OutDir
    if (-not $dir) { $dir = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'App Development' }
    if (-not (Test-Path -LiteralPath $dir)) { $dir = [Environment]::GetFolderPath('Desktop') }
    $file = Join-Path $dir ('morning-note-probe-results-' + (Get-Date -Format 'yyyyMMdd-HHmm') + '.json')
    $text = ConvertTo-Json -InputObject $R -Depth 8
    foreach ($x in $Secrets) { if ($x) { $text = $text.Replace($x, '<hidden>') } }     # last guard: nothing personal
    if ($script:key) { $text = $text.Replace($script:key, '<hidden>') }
    [IO.File]::WriteAllText($file, $text, (New-Object System.Text.UTF8Encoding($false)))
    return $file
}

# ------------------------------------------------------------------------------------------------ start
Say 'Morning note probe: TEST newsletter only. Use the test newsletter''s key; the probe stops if the list holds anyone but your team addresses.'
Say 'You will need: the TEST newsletter API key, two team email addresses you can open now, and about 12 minutes.'
$R['probe_version'] = 1
$R['run_at_utc'] = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')

$sec = Read-Host -AsSecureString 'Paste the TEST newsletter API key (nothing will show as you paste), then press Enter'
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
try { $script:key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
$script:key = $script:key.Trim()
$Secrets.Add($script:key) | Out-Null

$addrA = (Read-Host 'First team address (gets ONE email, "probe 4")').Trim()
$addrB = (Read-Host 'Second team address (gets ONE email, "probe 1")').Trim()
$addrC = (Read-Host 'Third team address that is NOT signed up to the test newsletter (for the sign-up form test; stamp mode needs it)').Trim()
$testUser = (Read-Host 'The TEST newsletter username (the name after buttondown.com/ for the test newsletter)').Trim()
$liveUser = (Read-Host 'The LIVE newsletter username (the name after buttondown.com/ for Daylight)').Trim()
foreach ($x in @($addrA, $addrB, $addrC)) { if ($x) { $Secrets.Add($x) | Out-Null } }
$R['live_username'] = $liveUser        # public: it goes in the site's sign-up form address (form_action)
$EmailRe = '^[^@\s]+@[^@\s]+\.[^@\s]+$'
$bad = $false
foreach ($x in @($addrA, $addrB)) { if ($x -notmatch $EmailRe) { $bad = $true } }
if ($addrC -and $addrC -notmatch $EmailRe) { $bad = $true }
if ($bad -or $addrA -eq $addrB -or ($addrC -and ($addrC -eq $addrA -or $addrC -eq $addrB))) {
    Say 'Each address must look like name@example.com, and they must all differ. Nothing was done.'; [void](Read-Host 'Press Enter to close'); exit 1
}

$rand = -join ((48..57) + (97..102) | Get-Random -Count 8 | ForEach-Object { [char]$_ })
$day = (Get-Date).ToString('yyyy-MM-dd')

try {
    Step '1/9 The key'
    $k = $script:key
    $R['T4.4-13 key printable ASCII, no space, 32+ bytes'] = $(if ($k -match '^[\x21-\x7E]{32,}$') { 'yes' } elseif ($k -match '^[\x21-\x7E]+$') { "no: printable but only $($k.Length) characters" } else { 'no: has spaces or other characters' })
    $first = Bd 'GET' '/emails' $null '' 'GET /emails'
    $R['key_works'] = $(if ($first.Status -eq 200) { 'yes' } else { "no: HTTP $($first.Status)" })
    if ($first.Status -eq 401 -or $first.Status -eq 403) { throw 'The key was refused. Check you copied the TEST newsletter key, then run again.' }
    $tags = Bd 'GET' '/tags' $null '' 'GET /tags'
    $nl = Bd 'GET' '/newsletters' $null '' 'GET /newsletters'
    $R['scoped_key_refuses_other_areas'] = "GET /tags HTTP $($tags.Status); GET /newsletters HTTP $($nl.Status) (401/403 = refused, as wanted)"

    Step '2/9 Guard: the list holds only your team addresses'
    $guard = Listing '/subscribers' 'GET /subscribers (guard)'
    if (-not $guard.Ok) { $R['newsletter_guard'] = "stopped: could not list subscribers (HTTP $($guard.Status))"; throw 'Could not list the subscribers, so nothing was changed.' }
    $mineSet = @($addrA.ToLower(), $addrB.ToLower()); if ($addrC) { $mineSet += $addrC.ToLower() }
    $others = 0
    foreach ($row in $guard.Rows) {
        $e = ''
        if (Has $row 'email_address') { $e = [string]$row.email_address } elseif (Has $row 'email') { $e = [string]$row.email }
        if (-not $e -or ($mineSet -notcontains $e.ToLower())) { $others++ }
    }
    if ($others -gt 0) {
        $R['newsletter_guard'] = "stopped: $others subscriber(s) other than the typed team addresses"
        throw "This newsletter has $others subscriber(s) besides your team addresses. Is this the TEST newsletter's key? Nothing was changed."
    }
    $R['newsletter_guard'] = 'passed: only team addresses on the list'

    Step 'Team subscribers'
    $subA = Ensure-Subscriber $addrA 'first'
    $subB = Ensure-Subscriber $addrB 'second'
    if ($null -eq $subA -or $null -eq $subB) { throw 'Could not create or find the two team subscribers.' }
    $idA = [string]$subA.id; $idB = [string]$subB.id
    $R['api_create_type_regular_skips_double_opt_in'] = "first: $($R['subscriber_first_type']); second: $($R['subscriber_second_type'])"

    Step '3/9 Reading one subscriber (T4.4 item 5)'
    $one = Bd 'GET' ('/subscribers/' + $idA) $null '' 'GET /subscribers/{id}'
    $none = Bd 'GET' ('/subscribers/' + [guid]::NewGuid().ToString()) $null '' 'GET /subscribers/{unknown id}'
    $R['T4.4-5 GET subscriber by id; 404 for none'] = "by id HTTP $($one.Status); unknown id HTTP $($none.Status) (want 200 and 404)"

    Step '4/9 Metadata: merge or replace, echo, idempotency (runbook 4; T4.4 items 6, 14)'
    $p1 = Bd 'PATCH' ('/subscribers/' + $idA) @{ metadata = @{ probe_m1 = '1' } } ('probe-m1-' + $rand) 'PATCH /subscribers/{id}'
    $p2 = Bd 'PATCH' ('/subscribers/' + $idA) @{ metadata = @{ probe_m2 = '2' } } ('probe-m2-' + $rand) 'PATCH /subscribers/{id}'
    $g = Bd 'GET' ('/subscribers/' + $idA) $null '' 'GET /subscribers/{id}'
    $stored = $null; if (Has $g.Data 'metadata') { $stored = $g.Data.metadata }
    $merge = (Has $stored 'probe_m1') -and (Has $stored 'probe_m2')
    $replace = (-not (Has $stored 'probe_m1')) -and (Has $stored 'probe_m2')
    $R['T4.4-6 PATCH metadata status'] = "HTTP $($p1.Status), HTTP $($p2.Status)"
    $R['runbook-4 PATCH metadata merges or replaces'] = $(if ($merge) { 'merges' } elseif ($replace) { 'replaces' } else { 'neither seen: ' + (Clean (Canon $stored)) })
    $echo = 'no metadata in the answer'
    if (Has $p2.Data 'metadata') { $echo = $(if ((Canon $p2.Data.metadata) -eq (Canon $stored)) { 'yes: the answer holds exactly the stored metadata' } else { 'no: the answer differs from what is stored' }) }
    $R['T4.4-6 PATCH answer echoes the stored metadata'] = $echo
    $k14 = 'probe-idem-' + $rand
    [void](Bd 'PATCH' ('/subscribers/' + $idA) @{ metadata = @{ probe_idem = 'x' } } $k14 'PATCH /subscribers/{id}')
    [void](Bd 'PATCH' ('/subscribers/' + $idA) @{ metadata = @{ probe_idem = 'y' } } $k14 'PATCH /subscribers/{id}')
    $g2 = Bd 'GET' ('/subscribers/' + $idA) $null '' 'GET /subscribers/{id}'
    $iv = $null; if ((Has $g2.Data 'metadata') -and (Has $g2.Data.metadata 'probe_idem')) { $iv = $g2.Data.metadata.probe_idem }
    $R['T4.4-14 X-Idempotency-Key honoured on PATCH'] = $(if ($iv -eq 'x') { 'yes (the repeat with the same key was not applied)' } elseif ($iv -eq 'y') { 'no (the repeat was applied)' } else { 'unclear' })

    Step '5/9 Emails: drafts, echo, idempotency on POST (T4.4 items 7, 14; runbook 2)'
    $metaIds = [ordered]@{ note_date = $day; note_edition = "$day.probe-ids"; note_sha256 = ('0' * 64) }
    $never = Email-Payload "Daylight probe 2: should never arrive (draft)" 'If you got this, write NO in the probe: a draft was sent.' 'draft' $metaIds $null ''
    $d1 = Bd 'POST' '/emails' $never ('probe-draft-' + $rand) 'POST /emails (draft)'
    if (Has $d1.Data 'id') { Note-Id $d1.Data.id; $Created.Add([string]$d1.Data.id) }
    $R['T4.4-7 ids draft echo (no filters back)'] = Echo-Check $never $d1 $false
    $d1b = Bd 'POST' '/emails' $never ('probe-draft-' + $rand) 'POST /emails (same key again)'
    if (Has $d1b.Data 'id') { Note-Id $d1b.Data.id; if (-not $Created.Contains([string]$d1b.Data.id)) { $Created.Add([string]$d1b.Data.id) } }
    $R['T4.4-14 X-Idempotency-Key honoured on POST'] = $(if ((Has $d1.Data 'id') -and (Has $d1b.Data 'id')) { if ($d1.Data.id -eq $d1b.Data.id) { 'yes (same email back)' } else { 'no (a second email was made)' } } else { "unclear: HTTP $($d1.Status), $($d1b.Status)" })

    Step '6/9 The stamp email: filtered and scheduled (runbook 1, 2; T4.4 items 7, 8)'
    $stamp = "$day.probe.$rand"
    $sb = Bd 'PATCH' ('/subscribers/' + $idB) @{ metadata = @{ note_edition = $stamp } } ('probe-stamp-' + $rand) 'PATCH /subscribers/{id} (stamp)'
    $R['stamp_written_to_second'] = "HTTP $($sb.Status)"
    $publishAt = (Get-Date).ToUniversalTime().AddMinutes(6)
    $pub = $publishAt.ToString('yyyy-MM-ddTHH:mm:ssZ')
    $filters = [ordered]@{ filters = @([ordered]@{ field = $StampField; operator = 'equals'; value = $stamp }); groups = @(); predicate = 'and' }
    $metaS = [ordered]@{ note_date = $day; note_edition = $stamp; note_sha256 = ('1' * 64) }
    $stampMail = Email-Payload 'Daylight probe 1: only the SECOND address should get this' 'Probe 1. Only the second address should get this email.' 'scheduled' $metaS $filters $pub
    $s1 = Bd 'POST' '/emails' $stampMail ('probe-stamp-mail-' + $rand) 'POST /emails (scheduled, filtered)'
    $idS1 = $null; if (Has $s1.Data 'id') { $idS1 = [string]$s1.Data.id; Note-Id $idS1 }
    $R['T4.4-7 stamp email echo (status, metadata, filters exactly as sent)'] = Echo-Check $stampMail $s1 $true
    $nobody = Email-Payload 'Daylight probe 3: should never arrive (taken back to draft)' 'If you got this, write NO in the probe: an unscheduled email was sent.' 'scheduled' ([ordered]@{ note_date = $day; note_edition = "$day.nobody.$rand"; note_sha256 = ('2' * 64) }) ([ordered]@{ filters = @([ordered]@{ field = $StampField; operator = 'equals'; value = "$day.nobody.$rand" }); groups = @(); predicate = 'and' }) $pub
    $s2 = Bd 'POST' '/emails' $nobody ('probe-unsched-' + $rand) 'POST /emails (scheduled, to take back)'
    if (Has $s2.Data 'id') {
        Note-Id $s2.Data.id; $Created.Add([string]$s2.Data.id)
        $back = Bd 'PATCH' ('/emails/' + $s2.Data.id) @{ status = 'draft' } ('probe-unsched-back-' + $rand) 'PATCH /emails/{id} (to draft)'
        $st = '(none)'; if (Has $back.Data 'status') { $st = $back.Data.status }
        $R['T4.4-8 PATCH status draft takes a scheduled email back'] = "HTTP $($back.Status), status now '$st' (want draft)"
        if ($st -ne 'draft') {
            $del = Bd 'DELETE' ('/emails/' + $s2.Data.id) $null '' 'DELETE /emails/{id} (probe 3 at once)'
            $R['probe 3 deleted at once because it did not go back to draft'] = "HTTP $($del.Status)"
        }
    } else { $R['T4.4-8 PATCH status draft takes a scheduled email back'] = "could not create: HTTP $($s2.Status) " + (Clean $s2.Text) }

    Step '7/9 send-draft to the first address (runbook 3, 7; T4.4 item 9)'
    $sendMail = Email-Payload 'Daylight probe 4: send-draft to the FIRST address' ("Probe 4. Only the first address should get this.`n`nTemplate test: {{ subscriber.email }}`n`nEnd of template test.") 'draft' ([ordered]@{ note_date = $day; note_edition = "$day.probe-send"; note_sha256 = ('3' * 64) }) $null ''
    $s4 = Bd 'POST' '/emails' $sendMail ('probe-send-' + $rand) 'POST /emails (draft to send)'
    if (Has $s4.Data 'id') {
        Note-Id $s4.Data.id
        $sd = Bd 'POST' ('/emails/' + $s4.Data.id + '/send-draft') @{ subscribers = @($idA) } ('probe-send-draft-' + $rand) 'POST /emails/{id}/send-draft'
        $R['T4.4-9 send-draft answer'] = "HTTP $($sd.Status) " + $(if ($sd.Status -ge 400) { Clean $sd.Text } else { '' })
        $after = Bd 'GET' ('/emails/' + $s4.Data.id) $null '' 'GET /emails/{id}'
        $st = '(none)'; if (Has $after.Data 'status') { $st = $after.Data.status }
        $R['send-draft email status afterwards'] = $st
    } else { $R['T4.4-9 send-draft answer'] = "could not create the draft: HTTP $($s4.Status) " + (Clean $s4.Text) }

    Step '8/9 The public sign-up form (runbook 8, 9: must NOT accept note_edition or canary)'
    if ($testUser) {
        $formUrl = $FormBase + [Uri]::EscapeDataString($testUser)
        $formStamp = "$day.form.$rand"
        $pairs = New-Object 'System.Collections.Generic.List[System.Collections.Generic.KeyValuePair[string,string]]'
        foreach ($kv in @(@('email', $addrA), @('metadata__lists', 'budget'), @('metadata__note_edition', $formStamp), @('metadata__canary', 'yes'))) {
            $pairs.Add((New-Object 'System.Collections.Generic.KeyValuePair[string,string]' -ArgumentList $kv[0], $kv[1]))
        }
        $before = Bd 'GET' ('/subscribers/' + $idA) $null '' 'GET /subscribers/{id}'
        $fr = Send-Raw 'POST' $formUrl (New-Object System.Net.Http.FormUrlEncodedContent(, $pairs)) @{ 'User-Agent' = 'daylight-probe/1' }
        $lh = ''; if ($fr.Location) { try { $lh = ([Uri]$fr.Location).Host } catch { $lh = '(relative)' } }
        $R['form_endpoint_answer (existing subscriber)'] = "HTTP $($fr.Status); redirect host: " + $(if ($lh) { $lh } else { '(none)' })
        $afterA = Bd 'GET' ('/subscribers/' + $idA) $null '' 'GET /subscribers/{id}'
        $mA = $null; if (Has $afterA.Data 'metadata') { $mA = $afterA.Data.metadata }
        $mB4 = $null; if (Has $before.Data 'metadata') { $mB4 = $before.Data.metadata }
        $R['runbook-8 form sets note_edition on an existing subscriber'] = $(if ((Has $mA 'note_edition') -and $mA.note_edition -eq $formStamp) { 'YES (stamp mode unsafe)' } else { 'no' })
        $R['runbook-8 form sets canary on an existing subscriber'] = $(if (Has $mA 'canary') { 'YES' } else { 'no' })
        $R['runbook-9 re-submit changes a confirmed subscriber''s metadata'] = $(if ((Canon $mA) -eq (Canon $mB4)) { 'no (unchanged)' } else { 'YES (changed)' })
        if ($addrC) {
            $Secrets.Add($addrC) | Out-Null
            $formStampC = "$day.formc.$rand"
            $pc = New-Object 'System.Collections.Generic.List[System.Collections.Generic.KeyValuePair[string,string]]'
            foreach ($kv in @(@('email', $addrC), @('metadata__lists', 'zoning'), @('metadata__lists', 'budget'), @('metadata__district', '5'), @('metadata__ward', '3'), @('metadata__note_edition', $formStampC), @('metadata__canary', 'yes'))) {
                $pc.Add((New-Object 'System.Collections.Generic.KeyValuePair[string,string]' -ArgumentList $kv[0], $kv[1]))
            }
            $fc = Send-Raw 'POST' $formUrl (New-Object System.Net.Http.FormUrlEncodedContent(, $pc)) @{ 'User-Agent' = 'daylight-probe/1' }
            $lh = ''; if ($fc.Location) { try { $lh = ([Uri]$fc.Location).Host } catch { $lh = '(relative)' } }
            $R['form_endpoint_answer (new address)'] = "HTTP $($fc.Status); redirect host: " + $(if ($lh) { $lh } else { '(none)' })
            $subC = Find-Subscriber $addrC
            if ($null -ne $subC) {
                Note-Id $subC.id
                $mC = $null; if (Has $subC 'metadata') { $mC = $subC.metadata }
                $t = '(no type)'; if (Has $subC 'type') { $t = [string]$subC.type }
                $R['runbook-9 double opt-in on form sign-ups (new subscriber type)'] = "$t (want unactivated)"
                $R['runbook-8 form sets note_edition on a new subscriber'] = $(if (Has $mC 'note_edition') { 'YES (stamp mode unsafe)' } else { 'no' })
                $R['runbook-8 form sets canary on a new subscriber'] = $(if (Has $mC 'canary') { 'YES' } else { 'no' })
                $lists = 'not stored'
                if (Has $mC 'lists') { $v = $mC.lists; if ($v -is [System.Array]) { $lists = "a list of $($v.Count): " + ($v -join ',') } else { $lists = 'one text value: ' + (Clean ([string]$v)) } }
                $R['form metadata__lists (two boxes ticked: zoning, budget)'] = $lists
                $R['form metadata__district and metadata__ward stored'] = $(if ((Has $mC 'district') -and (Has $mC 'ward')) { "yes (district '$($mC.district)', ward '$($mC.ward)')" } else { 'no' })
            } else { $R['runbook-9 double opt-in on form sign-ups (new subscriber type)'] = 'the new address was not found after the form post' }

            Step 'Subscriber types in the listing (runbook 6; T4.4 item 3)'
            $all = Listing '/subscribers' 'GET /subscribers'
            $inAll = $false; foreach ($row in $all.Rows) { if ((Has $row 'id') -and $subC -and $row.id -eq $subC.id) { $inAll = $true } }
            $types = @{}; foreach ($row in $all.Rows) { if (Has $row 'type') { $types[[string]$row.type] = 1 + [int]$types[[string]$row.type] } }
            $R['T4.4-3 default listing types and counts'] = $types
            $R['T4.4-3 default listing includes the unconfirmed form sign-up'] = $(if ($inAll) { 'yes' } else { 'no (the adapter must ask for each type)' })
        } else { $R['form test with a new address'] = 'skipped (no third address given)' }
    } else { $R['form tests'] = 'skipped (no test username given)' }

    Step 'Listings (T4.4 items 1, 2, 4; runbook 5)'
    $ls = Listing '/subscribers' 'GET /subscribers'
    $R['T4.4-1 subscriber listing shape {results, next, count}'] = $(if ($ls.Ok -and $ls.Shape) { 'yes' } else { "no: HTTP $($ls.Status)" })
    $R['T4.4-2 count equals rows (subscribers)'] = $(if ($ls.Ok -and $ls.Count -eq @($ls.Rows).Count -and $ls.SameCount) { 'yes' } else { "no: count $($ls.Count), rows $(@($ls.Rows).Count)" })
    $pg = Listing '/subscribers?page_size=1' 'GET /subscribers?page_size=1'
    $R['T4.4-1 next link is an absolute https://api.buttondown.com/v1/ URL'] = "$($pg.NextAbsolute) (pages read with page_size=1: $($pg.Pages); rows add up: $(if ($pg.Count -eq @($pg.Rows).Count) { 'yes' } else { 'no' }))"
    $le = Listing '/emails' 'GET /emails'
    $R['T4.4-1 email listing shape'] = $(if ($le.Ok -and $le.Shape) { 'yes' } else { "no: HTTP $($le.Status)" })
    $R['T4.4-2 count equals rows (emails)'] = $(if ($le.Ok -and $le.Count -eq @($le.Rows).Count -and $le.SameCount) { 'yes' } else { "no: count $($le.Count), rows $(@($le.Rows).Count)" })
    $pos = @{}; $i = 0; $withMeta = $true
    foreach ($row in $le.Rows) { if (Has $row 'id') { $pos[[string]$row.id] = $i }; $i++ }
    $mine = @(); foreach ($e in @($d1, $s1, $s2, $s4)) { if ($e -and (Has $e.Data 'id')) { $mine += [string]$e.Data.id } }
    $listed = 0; foreach ($m in $mine) { if ($pos.ContainsKey($m)) { $listed++; $row = $le.Rows[$pos[$m]]; if (-not (Has $row 'metadata') -or $null -eq $row.metadata) { $withMeta = $false } } }
    $R['runbook-5 / T4.4-4 listing holds the probe drafts and scheduled emails'] = "$listed of $($mine.Count)"
    $R['runbook-5 / T4.4-4 every row carries metadata'] = $(if ($withMeta) { 'yes' } else { 'no' })
    $order = 'unclear'
    if ($pos.ContainsKey([string]$d1.Data.id) -and $idS1 -and $pos.ContainsKey($idS1)) { $order = $(if ($pos[$idS1] -lt $pos[[string]$d1.Data.id]) { 'newest first' } else { 'oldest first' }) }
    $R['runbook-5 listing order'] = $order
    $lf = Bd 'GET' ('/emails?creation_date__start=' + $day) $null '' 'GET /emails?creation_date__start'
    $R['T4.4-4 a date filter can shorten the email listing'] = "HTTP $($lf.Status)" + $(if (Has $lf.Data 'count') { ", count $($lf.Data.count) of $($le.Count)" } else { '' })

    Step '9/9 Waiting for the scheduled time (about 6 minutes after step 6), checking it held'
    if ($idS1) {
        $hold = Bd 'GET' ('/emails/' + $idS1) $null '' 'GET /emails/{id}'
        $h1 = '(none)'; if (Has $hold.Data 'status') { $h1 = $hold.Data.status }
        $left = [int]($publishAt - (Get-Date).ToUniversalTime()).TotalSeconds
        $R['runbook-2 scheduled email holds before publish_date'] = "status '$h1' with $left s to go (want scheduled)"
        if ($left -gt 0) { Say "Waiting $left seconds..."; Start-Sleep -Seconds $left }
        $final = '(none)'; $tries = 0
        do {
            Start-Sleep -Seconds 30; $tries++
            $done = Bd 'GET' ('/emails/' + $idS1) $null '' 'GET /emails/{id}'
            if (Has $done.Data 'status') { $final = [string]$done.Data.status }
        } while ($final -eq 'scheduled' -and $tries -lt 10)
        $R['runbook-2 status after publish_date'] = $final
        $R['stamp email recipient counts from the API'] = Count-Fields $done.Data
        $an = Bd 'GET' ('/emails/' + $idS1 + '/analytics') $null '' 'GET /emails/{id}/analytics'
        $R['stamp email analytics counts'] = $(if ($an.Status -eq 200) { Count-Fields $an.Data } else { "HTTP $($an.Status)" })
    }

    Step 'Your inbox checks (one answer each)'
    $R['MANUAL runbook-1 only the SECOND address got "probe 1"'] = Ask-YesNo 'Did the SECOND address get "Daylight probe 1", and the FIRST address NOT get it?'
    $R['MANUAL runbook-3 FIRST address got "probe 4" (send-draft is a real send)'] = Ask-YesNo 'Did the FIRST address get "Daylight probe 4"?'
    $R['MANUAL runbook-3 "probe 4" has an unsubscribe link'] = Ask-YesNo 'Does "Daylight probe 4" have an unsubscribe link at the bottom?'
    $tpl = (Read-Host 'In "probe 4", what does the Template test line show? 1 = the text {{ subscriber.email }} exactly, 2 = your email address, 3 = something else').Trim()
    $R['MANUAL runbook-7 {{ subscriber.email }} in a body'] = $(switch ($tpl) { '1' { 'renders literally' } '2' { 'is evaluated' } '3' { 'something else' } default { 'not answered' } })
    $R['MANUAL runbook-2 a draft or taken-back email arrived ("probe 2" or "probe 3")'] = Ask-YesNo 'Did "Daylight probe 2" or "Daylight probe 3" arrive anywhere? (They should NOT.)'
    $R['MANUAL runbook-9 a preferences page lets a subscriber edit fields'] = Ask-YesNo 'Open the unsubscribe link in "probe 4" but do NOT unsubscribe. Does that page let you change anything besides unsubscribing (lists, district, ward or other fields)?'
    $R['MANUAL paid screens seen'] = Ask-YesNo 'Did Buttondown show an "upgrade" or "paid plan" message on any step you did today?'
} catch {
    $R['stopped_early'] = Clean ($_.Exception.Message)
    Say ('Stopped: ' + $R['stopped_early'])
} finally {
    Step 'Cleaning up the probe drafts'
    $deleted = 0
    foreach ($id in $Created) { $d = Bd 'DELETE' ('/emails/' + $id) $null '' 'DELETE /emails/{id}'; if ($d.Status -ge 200 -and $d.Status -lt 300) { $deleted++ } }
    $R['probe drafts deleted'] = "$deleted of $($Created.Count)"

    # The provisional mode (the team confirms it from the file): stamp needs every stamp check, ids every ids check.
    $y = { param($k) ([string]$R[$k]) -like 'yes*' }
    $stampOk = (& $y 'T4.4-7 stamp email echo (status, metadata, filters exactly as sent)') -and
        (([string]$R['runbook-2 scheduled email holds before publish_date']) -like "*'scheduled'*") -and
        ($R['MANUAL runbook-1 only the SECOND address got "probe 1"'] -eq 'yes') -and
        (& $y 'T4.4-6 PATCH answer echoes the stored metadata') -and
        (& $y 'T4.4-13 key printable ASCII, no space, 32+ bytes') -and
        ($R['runbook-8 form sets note_edition on an existing subscriber'] -eq 'no') -and
        ($R['runbook-8 form sets note_edition on a new subscriber'] -eq 'no')
    $idsOk = (& $y 'T4.4-7 ids draft echo (no filters back)') -and
        ($R['MANUAL runbook-3 FIRST address got "probe 4" (send-draft is a real send)'] -eq 'yes') -and
        ($R['MANUAL runbook-3 "probe 4" has an unsubscribe link'] -eq 'yes') -and
        ($R['MANUAL runbook-2 a draft or taken-back email arrived ("probe 2" or "probe 3")'] -eq 'no')
    $mode = 'none'; if ($stampOk) { $mode = 'stamp' } elseif ($idsOk) { $mode = 'ids' }
    $R['provisional_mode'] = $mode
    $R['stamp_checks_pass'] = $stampOk
    $R['ids_checks_pass'] = $idsOk

    $file = Write-Results
    $script:key = $null; $k = $null; [GC]::Collect()
    $client.Dispose()

    Write-Host ''
    Write-Host "Results saved to: $file" -ForegroundColor Green
    Write-Host 'They hold answers only: no key, no address, no id.'
    Write-Host ''
    if ($mode -eq 'stamp') {
        Write-Host 'For the LIVE key (next step on your list): Emails = Write, Sending = Write, Subscribers = WRITE, everything else = None.' -ForegroundColor Yellow
    } elseif ($mode -eq 'ids') {
        Write-Host 'For the LIVE key (next step on your list): Emails = Write, Sending = Write, Subscribers = READ, everything else = None.' -ForegroundColor Yellow
    } else {
        Write-Host 'Neither sending mode passed. Do NOT make the live key yet; the team will read the results and tell you what is next.' -ForegroundColor Yellow
    }
    Write-Host 'Now delete the TEST key: test newsletter > Settings > API > delete the key you made for this probe.'
    [void](Read-Host 'Press Enter to close')
}
