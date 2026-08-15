<#
.SYNOPSIS
  Opponent-isolated orchestrator for the Orcai-MJ vs amireman match (Windows).

.DESCRIPTION
  A sibling of play_ahk_yosi.ps1, dedicated to Team amireman and the PUBLIC
  interop spec (NEXT_OPPONENT_INTEROP_GUIDE_PUBLIC.md). It NEVER touches the
  ahk-yosi constitution, gate, artifacts or private config.

  Differences from the ahk-yosi launcher:
    * Signs config/game.amireman.json (Haifa constitution, spec Appendix A),
      whose canonical SHA-256 is $AgreedSha below.
    * Runs the peer with --spec-profile amireman:
        sorted "-vs-" game_id, UUID game_uid over canonical(terms),
        capture_claim on every police turn, explicit series_consensus
        exchange and the Section 12 result report.
    * Writes to artifacts\interop-amireman-* and to a SEPARATE gate file
      (friendly_gate_amireman.json) so an ahk-yosi gate can never authorize a
      counted amireman match.

  Modes: local | friendly | counted  (identical control flow to the ahk-yosi
  launcher). Counted is triple-gated (passed amireman friendly gate,
  P2P_CONFIRM_COUNTED=YES, and a typed confirmation).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\play_amireman.ps1 local
  powershell -ExecutionPolicy Bypass -File scripts\play_amireman.ps1 friendly -Series thief -Games 1
  powershell -ExecutionPolicy Bypass -File scripts\play_amireman.ps1 friendly -Series both `
    -SkipTunnels -CopPort 18811 -ThiefPort 18812 `
    -CopMcpUrl https://<our-cop>.trycloudflare.com/mcp `
    -ThiefMcpUrl https://<our-thief>.trycloudflare.com/mcp `
    -CopOpponentUrl https://<amireman-thief>/mcp `
    -ThiefOpponentUrl https://<amireman-police>/mcp
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("local", "friendly", "counted")]
    [string]$Mode,

    [ValidateSet("cop", "thief", "both")]
    [string]$Series = "thief",

    [int]$Games = 6,

    # Our real 40-hex runtime commit(s) for the identity block (Section 3).
    [string]$CopGitCommit = "",
    [string]$ThiefGitCommit = "",

    [string]$OpponentUrl = "",
    [string]$CopOpponentUrl = "",
    [string]$ThiefOpponentUrl = "",

    [switch]$SkipTunnels,
    [int]$CopPort = 18811,
    [int]$ThiefPort = 18812,
    [string]$CopMcpUrl = "",
    [string]$ThiefMcpUrl = ""
)

$ErrorActionPreference = "Stop"
# Canonical SHA-256 of config/game.amireman.json (Haifa constitution, spec App. A).
$AgreedSha = "32e86f85c47920c4a567df403bd1f263f1bbea5f59c7db0b7aeb640f30d15812"
$SpecProfile = "amireman"
$SharedJson = "config/game.amireman.json"
$GateName = "friendly_gate_amireman.json"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Base = Split-Path -Parent $Root
$CopRepo = Join-Path $Base "orcai-mj-cop"
$ThiefRepo = Join-Path $Base "orcai-mj-thief"
$PrivateDir = Join-Path $env:USERPROFILE ".orcai-match"
$PrivateCfg = Join-Path $PrivateDir "amireman.json"
$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogDir = Join-Path $Base ("match-logs\amireman-" + $RunStamp)
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Log($msg) { Write-Host "[amireman-launcher] $msg" }

$UvCmd = Get-Command uv -ErrorAction SilentlyContinue
if ($UvCmd) { $UvExe = $UvCmd.Source; $UvPre = @() }
else { $UvExe = "python"; $UvPre = @("-m", "uv") }

function Assert-Repo($repo) {
    if (-not (Test-Path (Join-Path $repo $SharedJson))) {
        throw "repository missing ${SharedJson}: $repo"
    }
    Push-Location $repo
    try { $sha = (& $UvExe ($UvPre + @("run", "python", "scripts/config_sha_amireman.py")) | Select-Object -Last 1).Trim() }
    finally { Pop-Location }
    if ($sha -ne $AgreedSha) {
        throw "amireman constitution hash mismatch in ${repo}: $sha (agreed: $AgreedSha)"
    }
    Log "$(Split-Path -Leaf $repo): amireman constitution OK ($($sha.Substring(0,12))...)"
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

function Start-InteropPeer($repo, $role, [int]$port, $oppUrl, $mode, $outDir, $mcpUrl, $commit, $tag) {
    $log = Join-Path $LogDir "peer-$tag.log"
    $peerArgs = $UvPre + @(
        "run", "police-thief", "interop",
        "--role", $role, "--opponent-url", $oppUrl, "--my-port", "$port",
        "--games", "$Games", "--mode", $mode, "--out", $outDir,
        "--spec-profile", $SpecProfile, "--config-json", $SharedJson,
        "--turn-timeout", "180")
    if ($mcpUrl) { $peerArgs += @("--mcp-url", $mcpUrl) }
    if ($commit) { $peerArgs += @("--git-commit", $commit) }
    $proc = Start-Process -FilePath $UvExe -ArgumentList $peerArgs -WorkingDirectory $repo `
        -RedirectStandardOutput $log -RedirectStandardError (Join-Path $LogDir "peer-$tag.err") `
        -PassThru -NoNewWindow
    Log "$tag peer started (pid $($proc.Id), port $port) -> $log"
    return $proc
}

function Wait-Peers([hashtable[]]$peerList, [int]$timeoutMinutes) {
    $deadline = (Get-Date).AddMinutes($timeoutMinutes)
    foreach ($p in $peerList) {
        while (-not $p.Process.HasExited) {
            if ((Get-Date) -gt $deadline) { throw "peer $($p.Tag) did not finish within $timeoutMinutes minutes" }
            Start-Sleep -Seconds 5
        }
        Log "$($p.Tag) peer exited with code $($p.Process.ExitCode)"
    }
}

function Wait-FriendlyArtifacts([hashtable[]]$peerList, [string]$outDir, [int]$games, [int]$timeoutMinutes, [datetime]$runStart) {
    $deadline = (Get-Date).AddMinutes($timeoutMinutes)
    $done = @{}
    while ($done.Count -lt $peerList.Count) {
        if ((Get-Date) -gt $deadline) { throw "timeout waiting for amireman friendly artifacts after $timeoutMinutes minutes" }
        Start-Sleep -Seconds 10
        foreach ($p in $peerList) {
            if ($done.ContainsKey($p.Tag)) { continue }
            $dir = Join-Path $p.Repo $outDir
            $resultFile = Get-ChildItem $dir -Filter "result_*-vs-*.json" -ErrorAction SilentlyContinue |
                          Where-Object { $_.LastWriteTime -gt $runStart } |
                          Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if (-not $resultFile) { continue }
            try {
                $res = Get-Content $resultFile.FullName -Raw | ConvertFrom-Json
                if ($res -and ($res.num_sub_games -eq $games)) {
                    $done[$p.Tag] = $res
                    Log "$($p.Tag): artifact found - num_sub_games=$($res.num_sub_games)"
                }
            } catch { }
        }
    }
}

function Read-PeerResultAfter($repo, $outDir, [datetime]$after) {
    $dir = Join-Path $repo $outDir
    $resultFile = Get-ChildItem $dir -Filter "result_*-vs-*.json" -ErrorAction SilentlyContinue |
                  Where-Object { $_.LastWriteTime -gt $after } |
                  Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $resultFile) { return $null }
    return Get-Content $resultFile.FullName -Raw | ConvertFrom-Json
}

function Stop-Quiet($proc) {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
}

function Write-AmiremanGate($passed, $detail) {
    $gate = @{ passed = $passed; mode = "friendly"; opponent = "amireman"; at = (Get-Date -Format o); detail = $detail }
    $gateJson = $gate | ConvertTo-Json -Depth 5
    foreach ($p in $peers) {
        $repoArtifacts = Join-Path $p.Repo "artifacts"
        New-Item -ItemType Directory -Force $repoArtifacts | Out-Null
        $gatePath = Join-Path $repoArtifacts $GateName
        $gateJson | Out-File -Encoding utf8 $gatePath
        Log "amireman friendly gate written: $gatePath (passed=$passed)"
    }
}

function Assert-NoEmailArtifacts {
    $sent = @(Get-ChildItem -Recurse -Path $CopRepo, $ThiefRepo -Filter "*.eml" -ErrorAction SilentlyContinue |
              Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-2) })
    if ($sent.Count -gt 0) { throw "email artifacts appeared during an amireman friendly run: $($sent.FullName -join ', ')" }
    Log "zero email artifacts produced (amireman friendly verified)"
}

# ================================================================= modes
Assert-Repo $CopRepo
Assert-Repo $ThiefRepo

if ($Mode -eq "local") {
    $portCop = Get-FreePort
    $portThief = Get-FreePort
    $out = "artifacts\interop-amireman-local"
    $peers = @(
        @{ Tag = "cop";   Repo = $CopRepo;   Process = (Start-InteropPeer $CopRepo "police" $portCop "http://127.0.0.1:$portThief/mcp" "friendly" $out $null $CopGitCommit "cop") },
        @{ Tag = "thief"; Repo = $ThiefRepo; Process = (Start-InteropPeer $ThiefRepo "thief" $portThief "http://127.0.0.1:$portCop/mcp" "friendly" $out $null $ThiefGitCommit "thief") }
    )
    $runStart = Get-Date
    try { Wait-FriendlyArtifacts $peers $out $Games 30 $runStart } finally { $peers | ForEach-Object { Stop-Quiet $_.Process } }
    $copRes = Read-PeerResultAfter $CopRepo $out $runStart
    $thiefRes = Read-PeerResultAfter $ThiefRepo $out $runStart
    Assert-NoEmailArtifacts
    if ($copRes -and $thiefRes -and ($copRes.num_sub_games -eq $Games) -and ($thiefRes.num_sub_games -eq $Games) -and
        ($copRes.mutual_agreement.sha_match) -and ($thiefRes.mutual_agreement.sha_match)) {
        Log "LOCAL AMIREMAN FRIENDLY: PASS (consensus sha_match on both peers)"
        exit 0
    }
    Log "LOCAL AMIREMAN FRIENDLY: FAIL - inspect $LogDir and artifacts"
    exit 1
}

if ($Mode -eq "counted") {
    if ($env:P2P_CONFIRM_COUNTED -ne "YES") { throw "counted mode requires P2P_CONFIRM_COUNTED=YES" }
    $gateRepos = @()
    if ($Series -in @("cop", "both"))   { $gateRepos += $CopRepo }
    if ($Series -in @("thief", "both")) { $gateRepos += $ThiefRepo }
    foreach ($gateRepo in $gateRepos) {
        $gatePath = Join-Path (Join-Path $gateRepo "artifacts") $GateName
        if (-not (Test-Path $gatePath)) { throw "counted mode requires a PASSED amireman friendly gate ($gatePath missing)" }
        $gate = Get-Content $gatePath -Raw | ConvertFrom-Json
        if (-not $gate.passed) { throw "amireman friendly gate exists but did not pass ($gatePath)" }
    }
    $typed = Read-Host "Type START COUNTED MATCH to proceed"
    if ($typed -ne "START COUNTED MATCH") { throw "counted match not confirmed" }
}

$plan = @()
if ($Series -in @("cop", "both"))   { $plan += @{ Repo = $CopRepo;   Role = "police"; Tag = "cop";   Commit = $CopGitCommit } }
if ($Series -in @("thief", "both")) { $plan += @{ Repo = $ThiefRepo; Role = "thief";  Tag = "thief"; Commit = $ThiefGitCommit } }

$tunnels = @()
if ($SkipTunnels) {
    foreach ($entry in $plan) {
        if ($entry.Tag -eq "cop") { $entry.Port = $CopPort; $entry.Tunnel = @{ Process = $null; Url = $CopMcpUrl } }
        else { $entry.Port = $ThiefPort; $entry.Tunnel = @{ Process = $null; Url = $ThiefMcpUrl } }
        Log "$($entry.Tag) reusing existing tunnel on port $($entry.Port): $($entry.Tunnel.Url)"
    }
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
    Write-Host ("OUR ENDPOINT (send to amireman): " + $entry.Tunnel.Url + "   (our " + $entry.Tag + " peer)") -ForegroundColor Green
}
Write-Host ""

if ($CopOpponentUrl -or $ThiefOpponentUrl) {
    if ($CopOpponentUrl) {
        if ($CopOpponentUrl -notmatch '^https?://') { throw "invalid CopOpponentUrl: $CopOpponentUrl" }
        if ($CopOpponentUrl -notmatch '/mcp/?$') { $CopOpponentUrl = $CopOpponentUrl.TrimEnd('/') + "/mcp" }
    }
    if ($ThiefOpponentUrl) {
        if ($ThiefOpponentUrl -notmatch '^https?://') { throw "invalid ThiefOpponentUrl: $ThiefOpponentUrl" }
        if ($ThiefOpponentUrl -notmatch '/mcp/?$') { $ThiefOpponentUrl = $ThiefOpponentUrl.TrimEnd('/') + "/mcp" }
    }
} else {
    if (-not $OpponentUrl) {
        if (Test-Path $PrivateCfg) {
            $saved = Get-Content $PrivateCfg -Raw | ConvertFrom-Json
            if ($saved.opponent_url) { $OpponentUrl = $saved.opponent_url; Log "using saved opponent URL: $OpponentUrl" }
        }
    }
    if (-not $OpponentUrl) {
        Write-Host "WAITING FOR AMIREMAN MCP URL"
        $OpponentUrl = Read-Host "Paste amireman's live /mcp URL"
    }
    if ($OpponentUrl -notmatch '^https?://') { $tunnels | ForEach-Object { Stop-Quiet $_.Process }; throw "invalid opponent URL: $OpponentUrl" }
    if ($OpponentUrl -notmatch '/mcp/?$') { $OpponentUrl = $OpponentUrl.TrimEnd('/') + "/mcp" }
    New-Item -ItemType Directory -Force $PrivateDir | Out-Null
    @{ opponent_url = $OpponentUrl; saved_at = (Get-Date -Format o) } | ConvertTo-Json | Out-File -Encoding utf8 $PrivateCfg
    Log "opponent URL stored privately at $PrivateCfg (never committed)"
    $CopOpponentUrl = $OpponentUrl
    $ThiefOpponentUrl = $OpponentUrl
}

$out = if ($Mode -eq "counted") { "artifacts\interop-amireman-counted" } else { "artifacts\interop-amireman-friendly" }
$runStart = Get-Date
$peers = @()
foreach ($entry in $plan) {
    $oppUrl = if ($entry.Tag -eq "cop") { $CopOpponentUrl } else { $ThiefOpponentUrl }
    $peers += @{ Tag = $entry.Tag; Repo = $entry.Repo; Role = $entry.Role;
                 Process = (Start-InteropPeer $entry.Repo $entry.Role $entry.Port $oppUrl $Mode $out $entry.Tunnel.Url $entry.Commit $entry.Tag) }
}

try {
    if ($Mode -eq "friendly") { Wait-FriendlyArtifacts $peers $out $Games 90 $runStart }
    else { Wait-Peers $peers 90 }
} finally {
    $peers | ForEach-Object { Stop-Quiet $_.Process }
    Log "peer processes stopped; logs preserved in $LogDir"
}

if (-not $SkipTunnels) { $tunnels | ForEach-Object { Stop-Quiet $_.Process }; Log "tunnels stopped" }

$allPass = $true
foreach ($p in $peers) {
    $res = Read-PeerResultAfter $p.Repo $out $runStart
    $shaMatch = if ($res.mutual_agreement) { $res.mutual_agreement.sha_match } else { $false }
    if (-not ($res -and ($res.num_sub_games -eq $Games) -and $shaMatch)) { $allPass = $false }
    if ($res) { Log "$($p.Tag): winner_group=$($res.final_result.winner_group) sha_match=$shaMatch confirmed=$($res.mutual_agreement.confirmed)" }
    else { Log "$($p.Tag): no result artifact found" }
}

if ($Mode -eq "friendly") {
    Assert-NoEmailArtifacts
    Write-AmiremanGate $allPass "series=$Series games=$Games cop-opp=$CopOpponentUrl thief-opp=$ThiefOpponentUrl"
    if ($allPass) { Write-Host "AMIREMAN FRIENDLY PASS - READY FOR COUNTED MATCH" -ForegroundColor Green; exit 0 }
    Write-Host "AMIREMAN FRIENDLY FAIL - DO NOT RUN COUNTED MATCH (see $LogDir)" -ForegroundColor Red
    exit 1
}

if ($allPass) { Write-Host "AMIREMAN COUNTED MATCH COMPLETE - verify + send the official report" -ForegroundColor Green; exit 0 }
Write-Host "AMIREMAN COUNTED MATCH INCOMPLETE - inspect $LogDir before any report" -ForegroundColor Red
exit 1
