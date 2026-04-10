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
        $existing = [System.IO.File]::ReadAllText($TargetClaude)
        # Check if this loadout content was already appended
        if ($existing.Contains($loadoutContent.Trim())) {
            Write-Host "  [SKIPPED]  CLAUDE.md (loadout content already present)" -ForegroundColor DarkYellow
        } else {
            $date = Get-Date -Format "yyyy-MM-dd"
            $separator = "`n`n---`n`n<!-- Loadout: $Loadout (applied $date) -->`n`n"
            [System.IO.File]::WriteAllText($TargetClaude, $existing + $separator + $loadoutContent)
            Write-Host "  [APPENDED] CLAUDE.md" -ForegroundColor Yellow
        }
    } else {
        [System.IO.File]::WriteAllText($TargetClaude, $loadoutContent)
        Write-Host "  [COPIED]   CLAUDE.md" -ForegroundColor Green
    }
}

# --- 2. Skills ---
$LoadoutSkills = Join-Path (Join-Path $LoadoutPath ".claude") "skills"
$TargetSkills = Join-Path (Join-Path $Target ".claude") "skills"

if (Test-Path $LoadoutSkills) {
    New-Item -ItemType Directory -Force -Path $TargetSkills | Out-Null
    $skillItems = Get-ChildItem -Path $LoadoutSkills
    $copiedCount = 0
    $skippedCount = 0
    foreach ($skill in $skillItems) {
        $targetSkillPath = Join-Path $TargetSkills $skill.Name
        if (Test-Path $targetSkillPath) {
            Write-Host "  [EXISTS]   Skill '$($skill.Name)' already exists in target." -ForegroundColor DarkYellow
            $overwrite = Read-Host "           Overwrite? (y/N)"
            if ($overwrite -eq 'y' -or $overwrite -eq 'Y') {
                Copy-Item -Path $skill.FullName -Destination $TargetSkills -Recurse -Force
                $copiedCount++
                Write-Host "           Overwritten." -ForegroundColor Yellow
            } else {
                $skippedCount++
                Write-Host "           Skipped." -ForegroundColor DarkYellow
            }
        } else {
            Copy-Item -Path $skill.FullName -Destination $TargetSkills -Recurse -Force
            $copiedCount++
        }
    }
    Write-Host "  [SKILLS]   $copiedCount copied, $skippedCount skipped" -ForegroundColor Green
}

# --- 3. Hooks (merge into settings.local.json) ---
# Support both: .claude/settings.local.json (preferred) or .claude/hooks.json (legacy)
$LoadoutSettingsFile = Join-Path (Join-Path $LoadoutPath ".claude") "settings.local.json"
$LoadoutHooksFile = Join-Path (Join-Path $LoadoutPath ".claude") "hooks.json"
$TargetSettings = Join-Path (Join-Path $Target ".claude") "settings.local.json"

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

    # Merge hooks per-event, avoiding duplicates
    if ($hooksData.PSObject.Properties["hooks"]) {
        if (-not $settings.PSObject.Properties["hooks"]) {
            $settings | Add-Member -NotePropertyName "hooks" -NotePropertyValue ([PSCustomObject]@{})
        }
        $newHooks = $hooksData.hooks
        foreach ($event in $newHooks.PSObject.Properties) {
            $eventName = $event.Name
            $newEntries = @($event.Value)
            if ($settings.hooks.PSObject.Properties[$eventName]) {
                $existingEntries = @($settings.hooks.$eventName)
                $addedCount = 0
                foreach ($newEntry in $newEntries) {
                    $newCmd = $newEntry.command
                    $isDuplicate = $false
                    foreach ($existing in $existingEntries) {
                        if ($existing.command -eq $newCmd) {
                            $isDuplicate = $true
                            break
                        }
                    }
                    if (-not $isDuplicate) {
                        $existingEntries += $newEntry
                        $addedCount++
                    }
                }
                $settings.hooks.$eventName = $existingEntries
                if ($addedCount -gt 0) {
                    Write-Host "  [MERGED]   $addedCount new hook(s) into '$eventName'" -ForegroundColor Green
                } else {
                    Write-Host "  [SKIPPED]  '$eventName' hooks already present" -ForegroundColor DarkYellow
                }
            } else {
                $settings.hooks | Add-Member -NotePropertyName $eventName -NotePropertyValue $newEntries
                Write-Host "  [ADDED]    '$eventName' hooks ($($newEntries.Count) entry/entries)" -ForegroundColor Green
            }
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
