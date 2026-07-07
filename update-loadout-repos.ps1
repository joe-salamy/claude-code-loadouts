<#
.SYNOPSIS
    Reapply a loadout to every repository recorded for that loadout.
.DESCRIPTION
    By default, AGENTS.md is left unchanged. Pass -UpdateAgentsMd to include
    AGENTS.md when updating recorded repositories.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$Loadout,
    [switch]$UpdateAgentsMd
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LoadoutsDir = Join-Path $ScriptRoot "loadouts"
$LoadoutPath = Join-Path $LoadoutsDir $Loadout
$UsagePath = Join-Path $ScriptRoot "applied-repos.json"
$LegacyUsagePath = Join-Path $LoadoutPath ".harness-loadout/applied-repos.json"
$HarnessInit = Join-Path $ScriptRoot "harness-init.ps1"

function ConvertTo-Array {
    param($Value)
    if ($null -eq $Value) {
        return @()
    }
    if ($Value -is [System.Array]) {
        return @($Value)
    }
    return @($Value)
}

function Read-LoadoutUsage {
    param([string]$UsagePath, [string]$LegacyUsagePath, [string]$Loadout)

    if (Test-Path $UsagePath) {
        try {
            $registry = Get-Content -Raw $UsagePath | ConvertFrom-Json
        } catch {
            Write-Host "Error: Could not parse registry '$UsagePath'." -ForegroundColor Red
            exit 1
        }

        $version = if ($registry.PSObject.Properties["version"]) { $registry.version } else { 1 }
        if ($version -ne 1) {
            Write-Host "Error: Unsupported registry version in '$UsagePath'." -ForegroundColor Red
            exit 1
        }

        if ($registry.PSObject.Properties["loadouts"]) {
            $entryProperty = $registry.loadouts.PSObject.Properties[$Loadout]
            if ($entryProperty) {
                $entry = $entryProperty.Value
                if (-not $entry.PSObject.Properties["repos"]) {
                    Write-Host "Error: Registry '$UsagePath' is missing repos for loadout '$Loadout'." -ForegroundColor Red
                    exit 1
                }

                $usageLoadout = if ($entry.PSObject.Properties["loadout"]) { $entry.loadout } else { $Loadout }
                return [PSCustomObject]@{
                    version = 1
                    loadout = $usageLoadout
                    repos = @(ConvertTo-Array $entry.repos)
                }
            }
        }

        if ($registry.PSObject.Properties["repos"]) {
            $usageLoadout = if ($registry.PSObject.Properties["loadout"]) { $registry.loadout } else { $Loadout }
            return [PSCustomObject]@{
                version = 1
                loadout = $usageLoadout
                repos = @(ConvertTo-Array $registry.repos)
            }
        }

    }

    if (Test-Path $LegacyUsagePath) {
        try {
            $data = Get-Content -Raw $LegacyUsagePath | ConvertFrom-Json
        } catch {
            Write-Host "Error: Could not parse registry '$LegacyUsagePath'." -ForegroundColor Red
            exit 1
        }

        $version = if ($data.PSObject.Properties["version"]) { $data.version } else { 1 }
        if ($version -ne 1) {
            Write-Host "Error: Unsupported registry version in '$LegacyUsagePath'." -ForegroundColor Red
            exit 1
        }
        if (-not $data.PSObject.Properties["repos"]) {
            Write-Host "Error: Registry '$LegacyUsagePath' is missing repos." -ForegroundColor Red
            exit 1
        }

        $usageLoadout = if ($data.PSObject.Properties["loadout"]) { $data.loadout } else { $Loadout }
        return [PSCustomObject]@{
            version = 1
            loadout = $usageLoadout
            repos = @(ConvertTo-Array $data.repos)
        }
    }

    return $null
}

if (-not (Test-Path $LoadoutPath -PathType Container)) {
    Write-Host "Error: Loadout '$Loadout' not found." -ForegroundColor Red
    Write-Host "Available loadouts:"
    Get-ChildItem -Path $LoadoutsDir -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }
    exit 1
}

$data = Read-LoadoutUsage -UsagePath $UsagePath -LegacyUsagePath $LegacyUsagePath -Loadout $Loadout
if ($null -eq $data) {
    Write-Host "No repositories recorded for loadout '$Loadout'."
    exit 0
}

$Pwsh = (Get-Command pwsh -ErrorAction Stop).Source
$updated = 0
$planned = 0
$skipped = 0
$failed = 0

$baseHarnessArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $HarnessInit)
if (-not $UpdateAgentsMd) {
    $baseHarnessArgs += "-SkipInstructionFile"
}

foreach ($repo in @($data.repos)) {
    if ($null -eq $repo -or [string]::IsNullOrWhiteSpace([string]$repo.path) -or [string]::IsNullOrWhiteSpace([string]$repo.harness)) {
        Write-Warning "Skipping malformed registry entry in $UsagePath."
        $skipped++
        continue
    }

    if (-not (Test-Path $repo.path -PathType Container)) {
        Write-Warning "Skipping missing repo: $($repo.path)"
        $skipped++
        continue
    }

    if (-not $PSCmdlet.ShouldProcess($repo.path, "Apply loadout '$Loadout' for harness '$($repo.harness)'")) {
        Write-Host "Planned update for repo: $($repo.path)" -ForegroundColor Cyan
        & $Pwsh @baseHarnessArgs -Loadout $Loadout -Target $repo.path -Harness $repo.harness -Force -PlanChanges
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Failed to plan repo: $($repo.path)"
            $failed++
            continue
        }
        $planned++
        continue
    }

    & $Pwsh @baseHarnessArgs -Loadout $Loadout -Target $repo.path -Harness $repo.harness -Force
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to update repo: $($repo.path)"
        $failed++
        continue
    }

    $updated++
}

Write-Host "Updated: $updated; planned: $planned; skipped: $skipped; failed: $failed."
if ($failed -gt 0) {
    exit 1
}
exit 0
