<#
.SYNOPSIS
  One-command orchestrator for the Orcai-MJ vs ahk-yosi match (Windows).

.DESCRIPTION
  Modes:
    local     - full six-sub-game friendly between OUR two repos on loopback
                (the end-to-end proof; no tunnels, no email possible).
    friendly  - live friendly vs ahk-yosi: starts tunnels, prints the URL to
                send to Yosef, asks once for his /mcp URL, runs the series,
                audits, writes the friendly gate on PASS. ZERO email.
    counted   - the official match. Requires: the friendly gate to have
                passed, P2P_CONFIRM_COUNTED=YES in the environment, and a
                typed confirmation. Never run casually.

  -Series cop|thief|both selects which of our role repos plays the live
  series (our cop peer expects their thief agent, and vice versa).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\play_ahk_yosi.ps1 local
  powershell -ExecutionPolicy Bypass -File scripts\play_ahk_yosi.ps1 friendly -Series thief
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("local", "friendly", "counted")]
    [string]$Mode,

    [ValidateSet("cop", "thief", "both")]
    [string]$Series = "thief",

    [int]$Games = 6,

    [string]$OpponentUrl = ""
)

$ErrorActionPreference = "Stop"
$AgreedSha = "3835f6a137620d8d98ab3925b2d1ed397d2d20d23bb9ba857bcd104284aac443"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Base = Split-Path -Parent $Root
$CopRepo = Join-Path $Base "orcai-mj-cop"
$ThiefRepo = Join-Path $Base "orcai-mj-thief"
$PrivateDir = Join-Path $env:USERPROFILE ".orcai-match"
$PrivateCfg = Join-Path $PrivateDir "ahk-yosi.json"
$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogDir = Join-Path $Base ("match-logs\" + $RunStamp)
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Log($msg) { Write-Host "[launcher] $msg" }

$UvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($UvCmd) { $UvExe = $UvCmd.Source; $UvPre = @() }
else { $UvExe = "python"; $UvPre = @("-m", "uv") }

# ---------------------------------------------------------------- validation
function Assert-Repo($repo) {
    if (-not (Test-Path (Join-Path $repo "config\game.json"))) {
        throw "repository not found or missing config/game.json: $repo"
    }
    Push-Location $repo
    try { $sha = (& $UvExe ($UvPre + @("run", "python", "scripts/config_sha.py")) | Select-Object -Last 1).Trim() }
    finally { Pop-Location }
    if ($sha -ne $AgreedSha) {
        throw "constitution hash mismatch in ${repo}: $sha (agreed: $AgreedSha)"
    }
    Log "$(Split-Path -Leaf $repo): constitution OK ($($sha.Substring(0,12))...)"
}

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    return $port
}

# ---------------------------------------------------------------- tunnels
function Find-Tunneler {
    if (Get-Command cloudflared -ErrorAction SilentlyContinue) { return "cloudflared" }
    Log "cloudflared not found - attempting winget install (no account needed)"
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install --id Cloudflare.cloudflared --accept-source-agreements --accept-package-agreements --silent | Out-Null
        # winget puts it on PATH for new shells; probe common locations too
        $probe = @(
            (Get-Command cloudflared -ErrorAction SilentlyContinue),
            (Get-Item "$env:ProgramFiles\cloudflared\cloudflared.exe" -ErrorAction SilentlyContinue),
            (Get-Item "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe" -ErrorAction SilentlyContinue)
        ) | Where-Object { $_ } | Select-Object -First 1
        if ($probe) {
            if ($probe.Source) { return $probe.Source } else { return $probe.FullName }
        }
    }
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

# ---------------------------------------------------------------- peers
function Start-InteropPeer($repo, $role, [int]$port, $oppUrl, $mode, $outDir, $mcpUrl, $tag) {
    $log = Join-Path $LogDir "peer-$tag.log"
    $peerArgs = $UvPre + @(
        "run", "police-thief", "interop",
        "--role", $role, "--opponent-url", $oppUrl, "--my-port", "$port",
        "--games", "$Games", "--mode", $mode, "--out", $outDir,
        "--turn-timeout", "180")
    if ($mcpUrl) { $peerArgs += @("--mcp-url", $mcpUrl) }
    $proc = Start-Process -FilePath $UvExe -ArgumentList $peerArgs -WorkingDirectory $repo `
        -RedirectStandardOutput $log -RedirectStandardError (Join-Path $LogDir "peer-$tag.err") `
        -PassThru -NoNewWindow
    Log "$tag peer started (pid $($proc.Id), port $port) -> $log"
    return $proc
}

function Wait-Peers([hashtable[]]$peers, [int]$timeoutMinutes) {
    $deadline = (Get-Date).AddMinutes($timeoutMinutes)
    foreach ($p in $peers) {
        while (-not $p.Process.HasExited) {
            if ((Get-Date) -gt $deadline) { throw "peer $($p.Tag) did not finish within $timeoutMinutes minutes" }
            Start-Sleep -Seconds 5
        }
        Log "$($p.Tag) peer exited with code $($p.Process.ExitCode)"
    }
}

function Read-PeerResult($repo, $outDir, $role) {
    $path = Join-Path $repo (Join-Path $outDir "result_$role.json")
    if (-not (Test-Path $path)) { return $null }
    return Get-Content $path -Raw | ConvertFrom-Json
}

function Stop-Quiet($proc) {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}

# ---------------------------------------------------------------- gates
function Write-FriendlyGate($passed, $detail) {
    $gate = @{ passed = $passed; mode = "friendly"; at = (Get-Date -Format o); detail = $detail }
    $gatePath = Join-Path $Base "friendly_gate.json"
    $gate | ConvertTo-Json -Depth 5 | Out-File -Encoding utf8 $gatePath
    Log "friendly gate written: $gatePath (passed=$passed)"
}

function Assert-NoEmailArtifacts {
    $sent = @(Get-ChildItem -Recurse -Path $CopRepo, $ThiefRepo -Filter "*.eml" -ErrorAction SilentlyContinue |
              Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-2) })
    if ($sent.Count -gt 0) { throw "email artifacts appeared during a friendly run: $($sent.FullName -join ', ')" }
    Log "zero email artifacts produced (friendly verified)"
}

# ================================================================= modes
Assert-Repo $CopRepo
Assert-Repo $ThiefRepo

if ($Mode -eq "local") {
    $portCop = Get-FreePort
    $portThief = Get-FreePort
    $out = "artifacts\interop-launcher"
    $peers = @(
        @{ Tag = "cop";   Process = (Start-InteropPeer $CopRepo "police" $portCop "http://127.0.0.1:$portThief/mcp" "friendly" $out $null "cop") },
        @{ Tag = "thief"; Process = (Start-InteropPeer $ThiefRepo "thief" $portThief "http://127.0.0.1:$portCop/mcp" "friendly" $out $null "thief") }
    )
    try { Wait-Peers $peers 30 } finally { $peers | ForEach-Object { Stop-Quiet $_.Process } }
    $copRes = Read-PeerResult $CopRepo $out "police"
    $thiefRes = Read-PeerResult $ThiefRepo $out "thief"
    $pass = $copRes -and $thiefRes -and $copRes.all_audits_verified -and $thiefRes.all_audits_verified -and
            ($copRes.num_sub_games -eq $Games) -and ($thiefRes.num_sub_games -eq $Games)
    Assert-NoEmailArtifacts
    if ($pass) {
        Log "LOCAL SIX-SUB-GAME FRIENDLY: PASS (totals cop-side: $($copRes.totals | ConvertTo-Json -Compress))"
        exit 0
    }
    Log "LOCAL SIX-SUB-GAME FRIENDLY: FAIL - inspect $LogDir and artifacts"
    exit 1
}

# --- live modes (friendly / counted) ------------------------------------
if ($Mode -eq "counted") {
    if ($env:P2P_CONFIRM_COUNTED -ne "YES") { throw "counted mode requires P2P_CONFIRM_COUNTED=YES" }
    $gatePath = Join-Path $Base "friendly_gate.json"
    if (-not (Test-Path $gatePath)) { throw "counted mode requires a PASSED friendly gate ($gatePath missing)" }
    $gate = Get-Content $gatePath -Raw | ConvertFrom-Json
    if (-not $gate.passed) { throw "friendly gate exists but did not pass" }
    $typed = Read-Host "Type START COUNTED MATCH to proceed"
    if ($typed -ne "START COUNTED MATCH") { throw "counted match not confirmed" }
}

$tool = Find-Tunneler
Log "tunnel tool: $tool"

$plan = @()
if ($Series -in @("cop", "both"))   { $plan += @{ Repo = $CopRepo;   Role = "police"; Tag = "cop" } }
if ($Series -in @("thief", "both")) { $plan += @{ Repo = $ThiefRepo; Role = "thief";  Tag = "thief" } }

$tunnels = @()
foreach ($entry in $plan) {
    $entry.Port = Get-FreePort
    $t = Start-Tunnel $tool $entry.Port $entry.Tag
    $entry.Tunnel = $t
    $tunnels += $t
    Log "$($entry.Tag) public endpoint: $($t.Url)"
}

Write-Host ""
foreach ($entry in $plan) {
    Write-Host ("SEND THIS TO YOSEF: " + $entry.Tunnel.Url + "   (our " + $entry.Tag + " peer)") -ForegroundColor Green
}
Write-Host ""

# opponent URL: parameter > private config > single prompt
if (-not $OpponentUrl) {
    if (Test-Path $PrivateCfg) {
        $saved = Get-Content $PrivateCfg -Raw | ConvertFrom-Json
        if ($saved.opponent_url) { $OpponentUrl = $saved.opponent_url; Log "using saved opponent URL: $OpponentUrl" }
    }
}
if (-not $OpponentUrl) {
    Write-Host "WAITING FOR YOSEF MCP URL"
    $OpponentUrl = Read-Host "Paste Yosef's live /mcp URL"
}
if ($OpponentUrl -notmatch '^https?://') { $tunnels | ForEach-Object { Stop-Quiet $_.Process }; throw "invalid opponent URL: $OpponentUrl" }
if ($OpponentUrl -notmatch '/mcp/?$') { $OpponentUrl = $OpponentUrl.TrimEnd('/') + "/mcp" }
New-Item -ItemType Directory -Force $PrivateDir | Out-Null
@{ opponent_url = $OpponentUrl; saved_at = (Get-Date -Format o) } | ConvertTo-Json | Out-File -Encoding utf8 $PrivateCfg
Log "opponent URL stored privately at $PrivateCfg (never committed)"

$out = if ($Mode -eq "counted") { "artifacts\interop-counted" } else { "artifacts\interop-friendly" }
$peers = @()
foreach ($entry in $plan) {
    $peers += @{ Tag = $entry.Tag; Repo = $entry.Repo; Role = $entry.Role;
                 Process = (Start-InteropPeer $entry.Repo $entry.Role $entry.Port $OpponentUrl $Mode $out $entry.Tunnel.Url $entry.Tag) }
}

try {
    Wait-Peers $peers 90
} finally {
    $peers | ForEach-Object { Stop-Quiet $_.Process }
    Log "peer processes stopped; logs preserved in $LogDir"
}
# Tunnels are stopped here — AFTER peer exits — so they survive any peer crash
# and a peer can be restarted without losing the Cloudflare hostname.
$tunnels | ForEach-Object { Stop-Quiet $_.Process }
Log "tunnels stopped"

$allPass = $true
foreach ($p in $peers) {
    $res = Read-PeerResult $p.Repo $out $p.Role
    if (-not ($res -and $res.all_audits_verified -and $res.num_sub_games -eq $Games)) { $allPass = $false }
    if ($res) { Log "$($p.Tag): totals=$($res.totals | ConvertTo-Json -Compress) winner=$($res.series_winner) audits_ok=$($res.all_audits_verified)" }
    else { Log "$($p.Tag): no result artifact found" }
}

if ($Mode -eq "friendly") {
    Assert-NoEmailArtifacts
    Write-FriendlyGate $allPass "series=$Series games=$Games opponent=$OpponentUrl"
    if ($allPass) { Write-Host "FRIENDLY PASS - READY FOR COUNTED MATCH" -ForegroundColor Green; exit 0 }
    Write-Host "FRIENDLY FAIL - DO NOT RUN COUNTED MATCH (see $LogDir)" -ForegroundColor Red
    exit 1
}

if ($allPass) { Write-Host "COUNTED MATCH COMPLETE - verify + send the official report per RUNBOOK" -ForegroundColor Green; exit 0 }
Write-Host "COUNTED MATCH INCOMPLETE - inspect $LogDir before any report" -ForegroundColor Red
exit 1
