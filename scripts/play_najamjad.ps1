<#
.SYNOPSIS
  Opponent-isolated orchestrator for the Orcai-MJ vs NajAmjad match (Windows).

.DESCRIPTION
  A sibling of play_ahk_yosi.ps1 / play_amireman.ps1, dedicated to Team
  NajAmjad (NAJAMJAD_MATCH_TERMS.md). It NEVER touches the ahk-yosi or
  amireman constitutions, gates, artifacts or private configs.

  NajAmjad-specific topology (their SS3): the series ALWAYS runs as TWO real
  processes out of two repositories —
      our COP  process (orcai-mj-cop,   police windows) -> THEIR THIEF door
      our THIEF process (orcai-mj-thief, thief windows) -> THEIR COP door
  Both processes share ONE artifacts directory (absolute path) so the two
  half-series merge into a single six-row report. Both stay up for the whole
  series; per-window handshakes and busy retries synchronise them.

  Defaults: their permanent named tunnels
      cop   https://cop.4laboratory.com/mcp
      thief https://thief.4laboratory.com/mcp
  and OUR team is police in window 1 (they open as thief, their SS1).

  Modes: local | friendly | counted. Counted is triple-gated (passed najamjad
  friendly gate, P2P_CONFIRM_COUNTED=YES, and a typed confirmation).
  local runs a loopback self-play of the FULL split topology with four peers
  (our two real peers + two "najamjad local sim" peers from the same repos).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\play_najamjad.ps1 local
  powershell -ExecutionPolicy Bypass -File scripts\play_najamjad.ps1 friendly `
    -SkipTunnels -CopPort 18821 -ThiefPort 18822 `
    -CopMcpUrl https://<our-cop>/mcp -ThiefMcpUrl https://<our-thief>/mcp
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("local", "friendly", "counted")]
    [string]$Mode,

    [int]$Games = 6,

    # OUR team's role in window 1. NajAmjad open as thief, so ours is police.
    [ValidateSet("police", "thief")]
    [string]$FirstWindowRole = "police",

    # Our real 40-hex runtime commits for the identity block (their SS7.3).
    [string]$CopGitCommit = "",
    [string]$ThiefGitCommit = "",

    # Their permanent doors (overridable for rehearsals only).
    [string]$CopOpponentUrl = "https://thief.4laboratory.com/mcp",
    [string]$ThiefOpponentUrl = "https://cop.4laboratory.com/mcp",

    [switch]$SkipTunnels,
    [int]$CopPort = 18821,
    [int]$ThiefPort = 18822,
    [string]$CopMcpUrl = "",
    [string]$ThiefMcpUrl = ""
)

$ErrorActionPreference = "Stop"
# Canonical SHA-256 of config/game.najamjad.json (OUR full-file lock) and the
# 14-key signed-terms digest (THEIR SS1 lock) — both re-checked per repo below.
$AgreedSha = "65c164a11b517f61036ffa2e65836a65bc17459c68fff3b9c38216e62b17bbb4"
$TermsSha  = "a284082dfb1572236f1b614d29295a99625539c7d33a096f7f8921bafbc3d08d"
$SpecProfile = "najamjad"
$SharedJson = "config/game.najamjad.json"
$GateName = "friendly_gate_najamjad.json"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Base = Split-Path -Parent $Root
$CopRepo = Join-Path $Base "orcai-mj-cop"
$ThiefRepo = Join-Path $Base "orcai-mj-thief"
$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogDir = Join-Path $Base ("match-logs\najamjad-" + $RunStamp)
# ONE shared artifacts directory (absolute) for BOTH processes — the row files
# row_<game_id>_gNN.json written here are how the two half-series merge.
$SharedOut = Join-Path $LogDir "artifacts"
New-Item -ItemType Directory -Force $LogDir | Out-Null
New-Item -ItemType Directory -Force $SharedOut | Out-Null

function Log($msg) { Write-Host "[najamjad-launcher] $msg" }

$UvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($UvCmd) { $UvExe = $UvCmd.Source; $UvPre = @() }
else { $UvExe = "python"; $UvPre = @("-m", "uv") }

function Assert-Repo($repo) {
    if (-not (Test-Path (Join-Path $repo $SharedJson))) {
        throw "repository missing ${SharedJson}: $repo"
    }
    Push-Location $repo
    try { $shas = & $UvExe ($UvPre + @("run", "python", "scripts/config_sha_najamjad.py")) | Select-Object -Last 2 }
    finally { Pop-Location }
    if ($shas[0].Trim() -ne $AgreedSha) {
        throw "najamjad constitution hash mismatch in ${repo}: $($shas[0]) (locked: $AgreedSha)"
    }
    if ($shas[1].Trim() -ne $TermsSha) {
        throw "najamjad 14-key TERMS digest mismatch in ${repo}: $($shas[1]) (signed: $TermsSha)"
    }
    Log "$(Split-Path -Leaf $repo): constitution + signed terms OK"
}

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start(); $port = $listener.LocalEndpoint.Port; $listener.Stop(); return $port
}

function Find-Tunneler {
    if (Get-Command cloudflared -ErrorAction SilentlyContinue) { return "cloudflared" }
    if (Get-Command ngrok -ErrorAction SilentlyContinue) { return "ngrok" }
    throw "BLOCKER: no tunnel tool. Install cloudflared (winget install Cloudflare.cloudflared) and re-run."
}

function Start-Tunnel($tool, [int]$port, [string]$tag) {
    $log = Join-Path $LogDir "tunnel-$tag.log"
    if ($tool -like "*ngrok*") {
        $proc = Start-Process -FilePath $tool -ArgumentList @("http", "$port", "--log", "stdout") `
            -RedirectStandardOutput $log -RedirectStandardError (Join-Path $LogDir "tunnel-$tag.err") -PassThru -NoNewWindow
        $pattern = 'url=(https://[^\s]+)'
    } else {
        $proc = Start-Process -FilePath $tool -ArgumentList @("tunnel", "--url", "http://localhost:$port", "--no-autoupdate") `
            -RedirectStandardOutput (Join-Path $LogDir "tunnel-$tag.out") -RedirectStandardError $log -PassThru -NoNewWindow
        $pattern = '(https://[a-z0-9-]+\.trycloudflare\.com)'
    }
    $url = $null
    foreach ($i in 1..60) {
        Start-Sleep -Seconds 2
        if (Test-Path $log) {
            $hit = Select-String -Path $log -Pattern $pattern -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($hit) { $url = $hit.Matches[0].Groups[1].Value; break }
        }
    }
    if (-not $url) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue; throw "tunnel for port $port never published a URL (see $log)" }
    return @{ Process = $proc; Url = ($url.TrimEnd('/') + "/mcp") }
}

function Start-NajamjadPeer($repo, $role, [int]$port, $oppUrl, $mode, $outDir, $mcpUrl, $commit, $firstWindowRole, $privateCfg, $tag) {
    $log = Join-Path $LogDir "peer-$tag.log"
    $peerArgs = $UvPre + @(
        "run", "police-thief", "interop",
        "--role", $role, "--opponent-url", $oppUrl, "--my-port", "$port",
        "--games", "$Games", "--mode", $mode, "--out", $outDir,
        "--spec-profile", $SpecProfile, "--config-json", $SharedJson,
        "--first-window-role", $firstWindowRole,
        "--turn-timeout", "60")
    if ($privateCfg) { $peerArgs += @("--config", $privateCfg) }
    if ($mcpUrl) { $peerArgs += @("--mcp-url", $mcpUrl) }
    if ($commit) { $peerArgs += @("--git-commit", $commit) }
    $proc = Start-Process -FilePath $UvExe -ArgumentList $peerArgs -WorkingDirectory $repo `
        -RedirectStandardOutput $log -RedirectStandardError (Join-Path $LogDir "peer-$tag.err") `
        -PassThru -NoNewWindow
    Log "$tag peer started (pid $($proc.Id), port $port, windows-first-role $firstWindowRole) -> $log"
    return $proc
}

function Stop-Quiet($proc) {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}

function Wait-ResultArtifacts([string]$outDir, [int]$games, [int]$timeoutMinutes, [datetime]$runStart, [int]$expected = 2) {
    $deadline = (Get-Date).AddMinutes($timeoutMinutes)
    while ($true) {
        if ((Get-Date) -gt $deadline) { throw "timeout waiting for najamjad result artifacts after $timeoutMinutes minutes" }
        Start-Sleep -Seconds 10
        $results = @(Get-ChildItem $outDir -Filter "result_*-vs-*_*.json" -ErrorAction SilentlyContinue |
                     Where-Object { $_.LastWriteTime -gt $runStart })
        if ($results.Count -ge $expected) {
            $ok = $true
            foreach ($f in $results) {
                try { $res = Get-Content $f.FullName -Raw | ConvertFrom-Json }
                catch { $ok = $false; break }
                if (-not ($res -and ($res.num_sub_games -eq $games))) { $ok = $false }
            }
            if ($ok) { return $results }
        }
    }
}

function Assert-NoEmailArtifacts {
    # Friendly may mail the TEAM address only; what must never exist here is a
    # drafted/queued message (.eml) aimed anywhere else. The lecturer wall is
    # enforced (and tested) in the peer's dispatch code.
    $sent = @(Get-ChildItem -Recurse -Path $CopRepo, $ThiefRepo, $SharedOut -Filter "*.eml" -ErrorAction SilentlyContinue |
              Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-2) })
    if ($sent.Count -gt 0) {
        throw "email draft artifacts appeared during a najamjad friendly/local run"
    }
    Log "zero email draft artifacts produced (verified)"
}

function Write-NajamjadGate($passed, $detail) {
    $gate = @{ passed = $passed; mode = "friendly"; opponent = "najamjad"; at = (Get-Date -Format o); detail = $detail }
    $gateJson = $gate | ConvertTo-Json -Depth 5
    foreach ($repo in @($CopRepo, $ThiefRepo)) {
        $repoArtifacts = Join-Path $repo "artifacts"
        New-Item -ItemType Directory -Force $repoArtifacts | Out-Null
        $gatePath = Join-Path $repoArtifacts $GateName
        $gateJson | Out-File -Encoding utf8 $gatePath
        Log "najamjad friendly gate written: $gatePath (passed=$passed)"
    }
    # The peer's counted gate check reads Split-Path(--out)\<gate>; the shared
    # out dir lives outside the repos, so mirror the gate beside it too.
    $gateJson | Out-File -Encoding utf8 (Join-Path (Split-Path -Parent $SharedOut) $GateName)
}

# ================================================================= modes
Assert-Repo $CopRepo
Assert-Repo $ThiefRepo

if ($Mode -eq "local") {
    # Rehearsal: no email of any kind, ever (inherited by all four peers).
    $env:P2P_EMAIL_DISABLE = "1"
    # Full split-topology rehearsal: four peers, two "teams", loopback only.
    #   Team A (real configs):  A-cop 1/3/5 police  |  A-thief 2/4/6 thief
    #   Team B (local sim):     B-thief 1/3/5 thief |  B-cop   2/4/6 police
    $pA_cop = Get-FreePort; $pA_thief = Get-FreePort
    $pB_cop = Get-FreePort; $pB_thief = Get-FreePort
    $outA = Join-Path $LogDir "artifacts-teamA"
    $outB = Join-Path $LogDir "artifacts-teamB"
    New-Item -ItemType Directory -Force $outA, $outB | Out-Null
    $peers = @(
        @{ Tag = "A-cop";   Out = $outA; Process = (Start-NajamjadPeer $CopRepo  "police" $pA_cop   "http://127.0.0.1:$pB_thief/mcp" "friendly" $outA $null $CopGitCommit  "police" $null "A-cop") },
        @{ Tag = "A-thief"; Out = $outA; Process = (Start-NajamjadPeer $ThiefRepo "thief"  $pA_thief "http://127.0.0.1:$pB_cop/mcp"   "friendly" $outA $null $ThiefGitCommit "police" $null "A-thief") },
        @{ Tag = "B-cop";   Out = $outB; Process = (Start-NajamjadPeer $CopRepo  "police" $pB_cop   "http://127.0.0.1:$pA_thief/mcp" "friendly" $outB $null $CopGitCommit  "thief" "config/najamjad/local_opponent_police.toml" "B-cop") },
        @{ Tag = "B-thief"; Out = $outB; Process = (Start-NajamjadPeer $ThiefRepo "thief"  $pB_thief "http://127.0.0.1:$pA_cop/mcp"   "friendly" $outB $null $ThiefGitCommit "thief" "config/najamjad/local_opponent_thief.toml" "B-thief") }
    )
    $runStart = Get-Date
    try {
        $resultsA = Wait-ResultArtifacts $outA $Games 45 $runStart 2
        $resultsB = Wait-ResultArtifacts $outB $Games 45 $runStart 2
    } finally { $peers | ForEach-Object { Stop-Quiet $_.Process } }
    Assert-NoEmailArtifacts
    $shas = @()
    foreach ($f in ($resultsA + $resultsB)) {
        $res = Get-Content $f.FullName -Raw | ConvertFrom-Json
        $shas += $res.mutual_agreement.sha256
        Log "$($f.Name): mutual sha $($res.mutual_agreement.sha256.Substring(0,12))... winner=$($res.series_winner)"
    }
    if (($shas | Select-Object -Unique).Count -eq 1) {
        Log "LOCAL NAJAMJAD SPLIT SERIES: PASS (all four peers agree on the mutual digest)"
        exit 0
    }
    Log "LOCAL NAJAMJAD SPLIT SERIES: FAIL - mutual digests differ, inspect $LogDir"
    exit 1
}

if ($Mode -eq "counted") {
    if ($env:P2P_CONFIRM_COUNTED -ne "YES") { throw "counted mode requires P2P_CONFIRM_COUNTED=YES" }
    foreach ($gateRepo in @($CopRepo, $ThiefRepo)) {
        $gatePath = Join-Path (Join-Path $gateRepo "artifacts") $GateName
        if (-not (Test-Path $gatePath)) { throw "counted mode requires a PASSED najamjad friendly gate ($gatePath missing)" }
        $gate = Get-Content $gatePath -Raw | ConvertFrom-Json
        if (-not $gate.passed) { throw "najamjad friendly gate exists but did not pass ($gatePath)" }
    }
    # The peer validates Split-Path(--out)\<gate>; this run's shared out dir is
    # freshly stamped, so mirror the (validated) gate beside it.
    Copy-Item (Join-Path (Join-Path $CopRepo "artifacts") $GateName) (Join-Path $LogDir $GateName) -Force
    $typed = Read-Host "Type START COUNTED MATCH to proceed"
    if ($typed -ne "START COUNTED MATCH") { throw "counted match not confirmed" }
}

# friendly / counted: TWO processes, one per repo, per-role opponent doors.
$plan = @(
    @{ Repo = $CopRepo;   Role = "police"; Tag = "cop";   Commit = $CopGitCommit;  Opp = $CopOpponentUrl },
    @{ Repo = $ThiefRepo; Role = "thief";  Tag = "thief"; Commit = $ThiefGitCommit; Opp = $ThiefOpponentUrl }
)
foreach ($entry in $plan) {
    if ($entry.Opp -notmatch '^https?://') { throw "invalid opponent URL for $($entry.Tag): $($entry.Opp)" }
    if ($entry.Opp -notmatch '/mcp/?$') { $entry.Opp = $entry.Opp.TrimEnd('/') + "/mcp" }
}

$tunnels = @()
if ($SkipTunnels) {
    $plan[0].Port = $CopPort;   $plan[0].Tunnel = @{ Process = $null; Url = $CopMcpUrl }
    $plan[1].Port = $ThiefPort; $plan[1].Tunnel = @{ Process = $null; Url = $ThiefMcpUrl }
    foreach ($entry in $plan) { Log "$($entry.Tag) reusing tunnel on port $($entry.Port): $($entry.Tunnel.Url)" }
} else {
    $tool = Find-Tunneler
    Log "tunnel tool: $tool"
    foreach ($entry in $plan) {
        $entry.Port = Get-FreePort
        $t = Start-Tunnel $tool $entry.Port $entry.Tag
        $entry.Tunnel = $t; $tunnels += $t
        Log "$($entry.Tag) public endpoint: $($t.Url)"
    }
}

Write-Host ""
foreach ($entry in $plan) {
    Write-Host ("OUR ENDPOINT (send to NajAmjad): " + $entry.Tunnel.Url + "   (our " + $entry.Tag + " process)") -ForegroundColor Green
}
Write-Host ""

$runStart = Get-Date
$peers = @()
foreach ($entry in $plan) {
    $peers += @{ Tag = $entry.Tag; Repo = $entry.Repo;
                 Process = (Start-NajamjadPeer $entry.Repo $entry.Role $entry.Port $entry.Opp $Mode $SharedOut $entry.Tunnel.Url $entry.Commit $FirstWindowRole $null $entry.Tag) }
}

try {
    $results = Wait-ResultArtifacts $SharedOut $Games 120 $runStart 2
} finally {
    $peers | ForEach-Object { Stop-Quiet $_.Process }
    Log "peer processes stopped; logs preserved in $LogDir"
    if (-not $SkipTunnels) { $tunnels | ForEach-Object { Stop-Quiet $_.Process }; Log "tunnels stopped" }
}

$allPass = $true
$shas = @()
foreach ($f in $results) {
    $res = Get-Content $f.FullName -Raw | ConvertFrom-Json
    $shas += $res.mutual_agreement.sha256
    if (-not ($res -and ($res.num_sub_games -eq $Games) -and $res.all_audits_verified)) { $allPass = $false }
    Log "$($f.Name): winner=$($res.series_winner) audits_ok=$($res.all_audits_verified) mutual=$($res.mutual_agreement.sha256.Substring(0,12))..."
}
if (($shas | Select-Object -Unique).Count -ne 1) { $allPass = $false; Log "OUR TWO PROCESSES DISAGREE on the mutual digest" }

if ($Mode -eq "friendly") {
    Assert-NoEmailArtifacts
    Write-NajamjadGate $allPass "games=$Games cop-opp=$($plan[0].Opp) thief-opp=$($plan[1].Opp) shared-out=$SharedOut"
    if ($allPass) { Write-Host "NAJAMJAD FRIENDLY PASS - READY FOR COUNTED MATCH" -ForegroundColor Green; exit 0 }
    Write-Host "NAJAMJAD FRIENDLY FAIL - DO NOT RUN COUNTED MATCH (see $LogDir)" -ForegroundColor Red
    exit 1
}

if ($allPass) { Write-Host "NAJAMJAD COUNTED MATCH COMPLETE - compare mutual_agreement.sha256 with NajAmjad BEFORE filing" -ForegroundColor Green; exit 0 }
Write-Host "NAJAMJAD COUNTED MATCH INCOMPLETE - inspect $LogDir before any report" -ForegroundColor Red
exit 1
