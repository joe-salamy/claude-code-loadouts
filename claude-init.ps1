<#
.SYNOPSIS
    Apply a Claude Code loadout to a target repository.
.DESCRIPTION
    Copies CLAUDE.md, skills, hooks, and other files from a loadout template
    into a target repo. See README.md for details.
.EXAMPLE
    .\claude-init.ps1 -Loadout python -Target C:\path\to\repo
.EXAMPLE
    .\claude-init.ps1 -List
#>
param(
    [string]$Loadout,
    [string]$Target = ".",
    [switch]$List
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LoadoutsDir = Join-Path $ScriptRoot "loadouts"

# --- List mode ---
if ($List) {
    Write-Host "Available loadouts:"
    Get-ChildItem -Path $LoadoutsDir -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }
    exit 0
}

# --- Validate inputs ---
if (-not $Loadout) {
    Write-Host "Error: -Loadout is required. Use -List to see available loadouts." -ForegroundColor Red
    exit 1
}

$LoadoutPath = Join-Path $LoadoutsDir $Loadout
if (-not (Test-Path $LoadoutPath)) {
    Write-Host "Error: Loadout '$Loadout' not found." -ForegroundColor Red
    Write-Host "Available loadouts:"
    Get-ChildItem -Path $LoadoutsDir -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }
    exit 1
}

$Target = Resolve-Path $Target
if (-not (Test-Path $Target -PathType Container)) {
    Write-Host "Error: Target '$Target' is not a directory." -ForegroundColor Red
    exit 1
}

Write-Host "Applying loadout '$Loadout' to: $Target" -ForegroundColor Cyan

# --- 1. CLAUDE.md ---
$LoadoutClaude = Join-Path $LoadoutPath "CLAUDE.md"
$TargetClaude = Join-Path $Target "CLAUDE.md"

if (Test-Path $LoadoutClaude) {
    $loadoutContent = [System.IO.File]::ReadAllText($LoadoutClaude)
    if (Test-Path $TargetClaude) {
        $date = Get-Date -Format "yyyy-MM-dd"
        $separator = "`n`n---`n`n<!-- Loadout: $Loadout (applied $date) -->`n`n"
        $existing = [System.IO.File]::ReadAllText($TargetClaude)
        [System.IO.File]::WriteAllText($TargetClaude, $existing + $separator + $loadoutContent)
        Write-Host "  [APPENDED] CLAUDE.md" -ForegroundColor Yellow
    } else {
        [System.IO.File]::WriteAllText($TargetClaude, $loadoutContent)
        Write-Host "  [COPIED]   CLAUDE.md" -ForegroundColor Green
    }
}

# --- 2. Skills ---
$LoadoutSkills = Join-Path $LoadoutPath ".claude" "skills"
$TargetSkills = Join-Path $Target ".claude" "skills"

if (Test-Path $LoadoutSkills) {
    New-Item -ItemType Directory -Force -Path $TargetSkills | Out-Null
    Copy-Item -Path (Join-Path $LoadoutSkills "*") -Destination $TargetSkills -Recurse -Force
    $skillCount = (Get-ChildItem -Path $LoadoutSkills -Directory).Count
    Write-Host "  [COPIED]   .claude/skills/ ($skillCount skill(s))" -ForegroundColor Green
}

# --- 3. Hooks (merge into settings.local.json) ---
# Support both: .claude/settings.local.json (preferred) or .claude/hooks.json (legacy)
$LoadoutSettingsFile = Join-Path $LoadoutPath ".claude" "settings.local.json"
$LoadoutHooksFile = Join-Path $LoadoutPath ".claude" "hooks.json"
$TargetSettings = Join-Path $Target ".claude" "settings.local.json"

$hooksSource = $null
if (Test-Path $LoadoutSettingsFile) {
    $hooksSource = $LoadoutSettingsFile
} elseif (Test-Path $LoadoutHooksFile) {
    $hooksSource = $LoadoutHooksFile
}

if ($hooksSource) {
    $hooksData = Get-Content -Raw $hooksSource | ConvertFrom-Json

    if (Test-Path $TargetSettings) {
        $settings = Get-Content -Raw $TargetSettings | ConvertFrom-Json
    } else {
        New-Item -ItemType Directory -Force -Path (Join-Path $Target ".claude") | Out-Null
        $settings = [PSCustomObject]@{}
    }

    # Replace or add the hooks key
    if ($hooksData.PSObject.Properties["hooks"]) {
        if ($settings.PSObject.Properties["hooks"]) {
            $settings.hooks = $hooksData.hooks
        } else {
            $settings | Add-Member -NotePropertyName "hooks" -NotePropertyValue $hooksData.hooks
        }
    }

    $settingsJson = $settings | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($TargetSettings, $settingsJson)
    Write-Host "  [MERGED]   hooks into .claude/settings.local.json" -ForegroundColor Green
}

# --- 4. Copy everything else ---
$exclude = @("CLAUDE.md", ".claude")
$extraFiles = Get-ChildItem -Path $LoadoutPath -Exclude $exclude

foreach ($item in $extraFiles) {
    $destPath = Join-Path $Target $item.Name
    if ($item.PSIsContainer) {
        # If target dir exists, copy contents into it (avoids nesting .git inside .git)
        if (Test-Path $destPath) {
            Copy-Item -Path (Join-Path $item.FullName "*") -Destination $destPath -Recurse -Force
        } else {
            Copy-Item -Path $item.FullName -Destination $destPath -Recurse -Force
        }
    } else {
        Copy-Item -Path $item.FullName -Destination $destPath -Force
    }
    Write-Host "  [COPIED]   $($item.Name)" -ForegroundColor Green
}

Write-Host "`nDone!" -ForegroundColor Cyan
