<#
====================================================================
 deploy-moba-windows.ps1
 --------------------------------------------------------------------
 One-shot Windows setup:
   1. Installs MobaXterm (winget, with direct-download fallback)
   2. Deploys ~/.ssh config + keys with correct Windows ACLs
   3. Imports the hosts into MobaXterm as saved SSH sessions

 SECURITY MODEL — READ THIS:
   This script contains NO private keys. It reads them at runtime from
   a sidecar file (default: .\bc_secrets.txt, the same format produced
   on the Linux box). You copy that sidecar over ONCE via a secure
   channel (USB / encrypted transfer), run the script, then DELETE the
   sidecar. Keep the script; never keep the sidecar.

 USAGE (from an elevated PowerShell prompt):
   Set-ExecutionPolicy -Scope Process Bypass -Force
   .\deploy-moba-windows.ps1 -SecretsFile .\bc_secrets.txt

   Optional flags:
     -SkipInstall     # don't install MobaXterm, only deploy SSH config
     -SkipSessions    # don't create MobaXterm sessions
     -WipeSecrets     # securely delete the sidecar file when done
====================================================================
#>

[CmdletBinding()]
param(
    [string]$SecretsFile = ".\bc_secrets.txt",
    [switch]$SkipInstall,
    [switch]$SkipSessions,
    [switch]$WipeSecrets
)

$ErrorActionPreference = "Stop"
function Info($m){ Write-Host "[*] $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[+] $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[!] $m" -ForegroundColor Yellow }
function Die($m){ Write-Host "[x] $m" -ForegroundColor Red; exit 1 }

# ------------------------------------------------------------------
# 1. Install MobaXterm
# ------------------------------------------------------------------
function Install-MobaXterm {
    if (Get-Command MobaXterm.exe -ErrorAction SilentlyContinue) { Ok "MobaXterm already on PATH."; return }
    $installed = Test-Path "$env:ProgramFiles\Mobatek\MobaXterm\MobaXterm.exe"
    if ($installed) { Ok "MobaXterm already installed."; return }

    # Preferred: winget (verifies publisher signature, official package)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Info "Installing MobaXterm via winget..."
        try {
            winget install --id Mobatek.MobaXterm --exact --silent `
                --accept-package-agreements --accept-source-agreements
            Ok "MobaXterm installed via winget."
            return
        } catch {
            Warn "winget install failed ($($_.Exception.Message)); falling back to direct download."
        }
    } else {
        Warn "winget not available; using direct download."
    }

    # Fallback: download the Installer edition zip from the official site.
    # NOTE: the version-numbered filename changes over time. We fetch the
    # download page and scrape the current MobaXterm_Installer link so the
    # script keeps working across releases.
    $base = "https://mobaxterm.mobatek.net"
    $page = "$base/download-home-edition.html"
    Info "Resolving current installer URL from $page ..."
    $html = (Invoke-WebRequest -Uri $page -UseBasicParsing).Content
    $m = [regex]::Match($html, 'href="([^"]*MobaXterm_Installer[^"]*\.zip)"')
    if (-not $m.Success) { Die "Could not find installer link on Mobatek download page. Install manually from $page." }
    $zipUrl = $m.Groups[1].Value
    if ($zipUrl -notmatch '^https?://') { $zipUrl = "$base/$($zipUrl.TrimStart('/'))" }

    $tmp = Join-Path $env:TEMP "MobaXterm_Installer.zip"
    $dir = Join-Path $env:TEMP "MobaXterm_Installer"
    Info "Downloading $zipUrl"
    Invoke-WebRequest -Uri $zipUrl -OutFile $tmp -UseBasicParsing
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    Expand-Archive -Path $tmp -DestinationPath $dir -Force

    $msi = Get-ChildItem $dir -Filter *.msi -Recurse | Select-Object -First 1
    if ($msi) {
        Info "Running silent MSI install..."
        Start-Process msiexec.exe -ArgumentList "/i `"$($msi.FullName)`" /qn /norestart" -Wait
        Ok "MobaXterm installed from MSI."
    } else {
        # Installer editions sometimes ship a portable .exe instead of an MSI.
        $exe = Get-ChildItem $dir -Filter *.exe -Recurse | Select-Object -First 1
        if (-not $exe) { Die "No MSI or EXE found in installer archive." }
        $dest = "$env:ProgramFiles\Mobatek\MobaXterm"
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Copy-Item $exe.FullName (Join-Path $dest "MobaXterm.exe") -Force
        Ok "MobaXterm (portable) placed in $dest."
    }
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}

# ------------------------------------------------------------------
# 2. Parse the sidecar secrets file for keys
#    Recognizes blocks of the form:
#      ### <keyname>            (e.g. ### id_ed25519)
#      -----BEGIN ... KEY-----
#      ...
#      -----END ... KEY-----
#    and the "# <name>.pub" + single ssh-* line public entries.
# ------------------------------------------------------------------
function Parse-Keys {
    param([string]$Path)
    if (-not (Test-Path $Path)) { Die "Secrets file not found: $Path (copy it over, then re-run)." }
    $lines = Get-Content -LiteralPath $Path
    $priv = @{}   # name -> text
    $pub  = @{}   # name -> text
    $curName = $null; $buf = New-Object System.Collections.Generic.List[string]; $inKey = $false
    for ($i=0; $i -lt $lines.Count; $i++) {
        $ln = $lines[$i]
        if ($ln -match '^\s*###\s+([A-Za-z0-9._-]+)') { $curName = $Matches[1]; continue }
        if ($ln -match '-----BEGIN .*PRIVATE KEY-----') { $inKey = $true; $buf.Clear(); $buf.Add($ln); continue }
        if ($inKey) {
            $buf.Add($ln)
            if ($ln -match '-----END .*PRIVATE KEY-----') {
                $inKey = $false
                $name = if ($curName) { $curName } else { "key_$i" }
                $priv[$name] = ($buf -join "`n") + "`n"
            }
            continue
        }
        # public keys: "# <name>.pub" followed by an ssh-* line
        if ($ln -match '^#\s*([A-Za-z0-9._-]+)\.pub\s*$') {
            $pn = $Matches[1]
            if ($i+1 -lt $lines.Count -and $lines[$i+1] -match '^(ssh-(rsa|ed25519)|ecdsa-)') {
                $pub[$pn] = $lines[$i+1].Trim()
            }
        }
    }
    return @{ Private = $priv; Public = $pub }
}

# ------------------------------------------------------------------
# 3. Deploy ~/.ssh with locked-down ACLs
# ------------------------------------------------------------------
function Deploy-Ssh {
    param($Keys)
    $sshDir = Join-Path $env:USERPROFILE ".ssh"
    New-Item -ItemType Directory -Force -Path $sshDir | Out-Null

    # Lock the .ssh dir to the current user only (OpenSSH refuses loose perms).
    $me = "$env:USERDOMAIN\$env:USERNAME"
    icacls $sshDir /inheritance:r /grant:r "${me}:(OI)(CI)F" | Out-Null

    # Map key file name -> on-disk filename. .id/OpenSSH keys keep their name.
    foreach ($name in $Keys.Private.Keys) {
        $file = Join-Path $sshDir $name
        # Write with Unix (LF) line endings and no BOM — required by OpenSSH.
        [IO.File]::WriteAllText($file, ($Keys.Private[$name] -replace "`r",""), (New-Object Text.UTF8Encoding($false)))
        icacls $file /inheritance:r /grant:r "${me}:F" | Out-Null
        Ok "Installed private key: $name"
    }
    foreach ($name in $Keys.Public.Keys) {
        $file = Join-Path $sshDir "$name.pub"
        [IO.File]::WriteAllText($file, $Keys.Public[$name] + "`n", (New-Object Text.UTF8Encoding($false)))
        Ok "Installed public key: $name.pub"
    }

    # SSH client config (topology — not secret). Windows OpenSSH understands
    # ProxyJump and ControlMaster (ControlMaster is a no-op on some builds; harmless).
    $config = @'
# ── ECB / ClubCEP infra ──────────────────────────────────
Host ecb.pm
    HostName 178.104.101.76
    User root
    IdentityFile ~/.ssh/id_ed25519

Host ecb-files
    HostName 178.104.101.76
    Port 2222
    User ecb
    IdentityFile ~/.ssh/id_ed25519

Host ecb-desktop
    HostName 178.104.101.76
    User ecb
    IdentityFile ~/.ssh/id_ed25519

Host ecb.pm-old
    HostName 178.104.123.117
    User root
    IdentityFile ~/.ssh/id_ed25519

Host test.clubcep.eu
    HostName test.clubcep.eu
    User root
    IdentityFile ~/.ssh/id_ed25519
    IdentityFile ~/.ssh/ecb.id

Host vps-jump
    HostName 178.104.101.76
    User revtunnel
    IdentityFile ~/.ssh/id_ed25519

Host fides janus
    HostName localhost
    Port 34925
    User root
    ProxyJump vps-jump
    IdentityFile ~/.ssh/id_ed25519
    HostKeyAlias fides-via-vps-tunnel

Host vesta
    HostName localhost
    Port 34924
    User root
    ProxyJump vps-jump
    IdentityFile ~/.ssh/id_ed25519
    HostKeyAlias vesta-via-vps-tunnel

# ── Personal VBox ─────────────────────────────────────────
Host collaed-sftp
    HostName collaed.duckdns.org
    Port 34321
    User collaed
    IdentityFile ~/.ssh/vbox.id

Host collaed-ssh
    HostName collaed.duckdns.org
    Port 34319
    User collaed
    IdentityFile ~/.ssh/vbox.id

# ── GitHub ────────────────────────────────────────────────
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519

Host *
    IdentitiesOnly yes
    ServerAliveInterval 60
'@
    $cfgFile = Join-Path $sshDir "config"
    [IO.File]::WriteAllText($cfgFile, ($config -replace "`r",""), (New-Object Text.UTF8Encoding($false)))
    icacls $cfgFile /inheritance:r /grant:r "${me}:F" | Out-Null
    Ok "Wrote ~/.ssh/config"
}

# ------------------------------------------------------------------
# 4. Create MobaXterm sessions (writes to MobaXterm.ini [Bookmarks])
#    Direct hosts only; ProxyJump hosts (fides/vesta) are best used from
#    the MobaXterm terminal via `ssh fides` since they need the config file.
# ------------------------------------------------------------------
function Add-MobaSessions {
    # MobaXterm stores sessions in MobaXterm.ini next to the exe (portable)
    # or in %APPDATA%\MobaXterm\MobaXterm.ini (installed).
    $candidates = @(
        (Join-Path $env:APPDATA "MobaXterm\MobaXterm.ini"),
        "$env:ProgramFiles\Mobatek\MobaXterm\MobaXterm.ini",
        (Join-Path (Split-Path $PSCommandPath) "MobaXterm.ini")
    )
    $ini = $candidates | Where-Object { Test-Path (Split-Path $_) } | Select-Object -First 1
    if (-not $ini) { $ini = $candidates[0]; New-Item -ItemType Directory -Force -Path (Split-Path $ini) | Out-Null }

    # SSH session line format (type 109):
    #   Name=#109#0%HostName%Port%User%...  (MobaXterm's encoded bookmark format)
    # We use the documented minimal form: it will read the ~/.ssh keys via the
    # "Use private key" left blank + rely on ssh-agent/config, so we point each
    # session at the host and username; MobaXterm picks up IdentityFile itself
    # when "Use SSH config" is enabled. Simpler + robust: create plain sessions.
    $sessions = @(
        @{ N="ecb.pm (root)";      H="178.104.101.76"; P=22;   U="root" }
        @{ N="ecb-files (sftp)";   H="178.104.101.76"; P=2222; U="ecb" }
        @{ N="ecb.pm-old";         H="178.104.123.117";P=22;   U="root" }
        @{ N="collaed-ssh";        H="collaed.duckdns.org"; P=34319; U="collaed" }
        @{ N="collaed-sftp";       H="collaed.duckdns.org"; P=34321; U="collaed" }
    )
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("[Bookmarks]")
    $lines.Add("SubRep=ECB Infra")
    $lines.Add("ImgNum=42")
    $idx = 0
    foreach ($s in $sessions) {
        # 109 = SSH. Fields: #109#0%host%port%user%%-1%-1%%%22%%0%0%0%...
        $lines.Add(("{0}=#109#0%{1}%{2}%{3}%%-1%-1%%%%%0%0%0%%%-1%0%0%0%%1080%%0%0%1#MobaFont%10%0%0%-1%15%236,236,236%30,30,30%180,180,192%0%-1%0%%xterm%-1%0%_Std_Colors_0_%80%24%0%1%-1%<none>%%0%0%-1" -f $s.N, $s.H, $s.P, $s.U))
        $idx++
    }
    Add-Content -LiteralPath $ini -Value ($lines -join "`r`n")
    Ok "Added $idx MobaXterm sessions to $ini (group 'ECB Infra')."
    Warn "For fides/vesta (ProxyJump), open MobaXterm's local terminal and run: ssh fides"
}

# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------
Info "MobaXterm + SSH deployment starting."
if (-not $SkipInstall) { Install-MobaXterm } else { Warn "Skipping MobaXterm install (-SkipInstall)." }

$Keys = Parse-Keys -Path $SecretsFile
if ($Keys.Private.Count -eq 0) { Warn "No private keys parsed from $SecretsFile — check the file format." }
Deploy-Ssh -Keys $Keys

if (-not $SkipSessions) { try { Add-MobaSessions } catch { Warn "Session import skipped: $($_.Exception.Message)" } }

if ($WipeSecrets) {
    Info "Wiping sidecar secrets file..."
    $len = (Get-Item $SecretsFile).Length
    $rng = New-Object byte[] $len
    (New-Object Random).NextBytes($rng)
    [IO.File]::WriteAllBytes($SecretsFile, $rng)
    Remove-Item $SecretsFile -Force
    Ok "Sidecar securely overwritten and deleted."
} else {
    Warn "Sidecar file left in place: $SecretsFile"
    Warn "DELETE IT NOW that keys are installed:  Remove-Item '$SecretsFile' -Force"
}

Ok "Done. Test with:  ssh ecb.pm hostname"
