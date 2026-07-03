<#
.SYNOPSIS
    Apply an agent harness loadout to a target repository.
.DESCRIPTION
    Copies instructions, skills, hooks, agents, commands, and other files from
    a harness-agnostic loadout template into a target repo. Templates use
    AGENTS.md and .harness/; the required -Harness flag controls the target
    config directory.
.EXAMPLE
    .\harness-init.ps1 -Loadout python -Target C:\path\to\repo -Harness codex
.EXAMPLE
    .\harness-init.ps1 -List
#>
param(
    [string]$Loadout,
    [string]$Target = ".",
    [ValidateSet("opencode", "codex", "gemini", "claude", "claude-code", "omp")]
    [string]$Harness,
    [switch]$List,
    [switch]$Force,
    [switch]$PlanChanges,
    [switch]$SkipInstructionFile,
    [string]$InitPrompt,
    [switch]$Headless,
    [string]$Model
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LoadoutsDir = Join-Path $ScriptRoot "loadouts"
$InitPromptsDir = Join-Path $ScriptRoot "init-prompts"

function Join-RepoPath {
    param([string]$Root, [string]$RelativePath)
    $parts = $RelativePath -split "[/\\]" | Where-Object { $_ }
    $path = $Root
    foreach ($part in $parts) {
        $path = Join-Path $path $part
    }
    return $path
}

function Get-HarnessProfile {
    param([string]$Name)

    $normalizedName = if ($Name -eq "claude-code") { "claude" } else { $Name }
    $configDir = ".$normalizedName"
    $hookConfigPath = $null
    $hookSourcePaths = @(".harness/hooks.json")

    switch ($normalizedName) {
        "codex" {
            $hookConfigPath = ".codex/hooks.json"
            $hookSourcePaths += @(".codex/hooks.json")
        }
        "gemini" {
            $hookConfigPath = ".gemini/settings.json"
            $hookSourcePaths += @(".gemini/settings.json")
        }
        "claude" {
            $hookConfigPath = ".claude/settings.local.json"
            $hookSourcePaths += @(".claude/settings.local.json", ".claude/hooks.json")
        }
    }

    return [PSCustomObject]@{
        Name = $normalizedName
        InstructionFile = "AGENTS.md"
        InstructionAliases = @("CLAUDE.md", "GEMINI.md")
        TemplateConfigDir = ".harness"
        ConfigDir = $configDir
        ConfigDirs = @($configDir)
        SkillsPath = "$configDir/skills"
        SkillSourcePaths = @(".harness/skills", "$configDir/skills", ".opencode/skills", ".codex/skills", ".agents/skills", ".claude/skills")
        HookConfigPath = $hookConfigPath
        HookSourcePaths = $hookSourcePaths
    }
}

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

function Get-HookEntryKey {
    param($Entry)

    if ($null -eq $Entry) {
        return ""
    }
    return ($Entry | ConvertTo-Json -Depth 20 -Compress)
}

function Merge-HooksObject {
    param($Existing, $Incoming)

    if ($null -eq $Existing) {
        $Existing = [PSCustomObject]@{}
    }
    if ($null -eq $Incoming) {
        return $Existing
    }

    foreach ($event in $Incoming.PSObject.Properties) {
        $eventName = $event.Name
        $incomingEntries = @(ConvertTo-Array $event.Value)

        if ($Existing.PSObject.Properties[$eventName]) {
            $existingEntries = @(ConvertTo-Array $Existing.$eventName)
            $existingKeys = @{}
            foreach ($entry in $existingEntries) {
                $existingKeys[(Get-HookEntryKey $entry)] = $true
            }

            $addedCount = 0
            foreach ($entry in $incomingEntries) {
                $key = Get-HookEntryKey $entry
                if (-not $existingKeys.ContainsKey($key)) {
                    $existingEntries += $entry
                    $existingKeys[$key] = $true
                    $addedCount++
                }
            }

            $Existing.$eventName = [object[]]$existingEntries
            if ($addedCount -gt 0) {
                Write-Host "  [MERGED]   $addedCount new hook(s) into '$eventName'" -ForegroundColor Green
            } else {
                Write-Host "  [SKIPPED]  '$eventName' hooks already present" -ForegroundColor DarkYellow
            }
        } else {
            $Existing | Add-Member -NotePropertyName $eventName -NotePropertyValue ([object[]]$incomingEntries)
            Write-Host "  [ADDED]    '$eventName' hooks ($($incomingEntries.Count) entry/entries)" -ForegroundColor Green
        }
    }

    return $Existing
}

function Merge-HookConfig {
    param([string]$Source, [string]$Dest)

    if (-not (Test-Path $Source)) {
        return
    }

    $sourceData = Get-Content -Raw $Source | ConvertFrom-Json
    $destDir = Split-Path -Parent $Dest
    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    }

    if (Test-Path $Dest) {
        $destData = Get-Content -Raw $Dest | ConvertFrom-Json
    } else {
        $destData = [PSCustomObject]@{}
    }

    if ($sourceData.PSObject.Properties["hooks"]) {
        if (-not $destData.PSObject.Properties["hooks"]) {
            $destData | Add-Member -NotePropertyName "hooks" -NotePropertyValue ([PSCustomObject]@{})
        }
        $destData.hooks = Merge-HooksObject -Existing $destData.hooks -Incoming $sourceData.hooks
    }

    foreach ($property in $sourceData.PSObject.Properties) {
        if ($property.Name -eq "hooks") {
            continue
        }
        if (-not $destData.PSObject.Properties[$property.Name]) {
            $destData | Add-Member -NotePropertyName $property.Name -NotePropertyValue $property.Value
            Write-Host "  [ADDED]    '$($property.Name)' into $($Dest.Replace($Target, '').TrimStart('\', '/'))" -ForegroundColor Green
        }
    }

    $destJson = $destData | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText($Dest, $destJson)
    Write-Host "  [MERGED]   $($Dest.Replace($Target, '').TrimStart('\', '/'))" -ForegroundColor Green
}

function Copy-FileWithPrompt {
    param([string]$Source, [string]$Dest)

    if (Test-Path $Dest) {
        $relPath = $Dest.Replace($Target, "").TrimStart("\", "/")
        if ($Force) {
            Copy-Item -Path $Source -Destination $Dest -Force
            Write-Host "  [OVERWROTE] $relPath" -ForegroundColor Yellow
        } else {
            Write-Host "  [EXISTS]   '$relPath' already exists in target." -ForegroundColor DarkYellow
            $overwrite = Read-Host "           Overwrite? (y/N)"
            if ($overwrite -eq "y" -or $overwrite -eq "Y") {
                Copy-Item -Path $Source -Destination $Dest -Force
                Write-Host "           Overwritten." -ForegroundColor Yellow
            } else {
                Write-Host "           Skipped." -ForegroundColor DarkYellow
            }
        }
    } else {
        $destDir = Split-Path -Parent $Dest
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        }
        Copy-Item -Path $Source -Destination $Dest -Force
        $relPath = $Dest.Replace($Target, "").TrimStart("\", "/")
        Write-Host "  [COPIED]   $relPath" -ForegroundColor Green
    }
}

function Test-SkipGeneratedPythonCache {
    param([System.IO.FileSystemInfo]$Item, [string]$RelativePath = "")

    if ($Item.Name -eq "__pycache__") {
        return $true
    }

    if (-not $Item.PSIsContainer -and ($Item.Extension -in @(".pyc", ".pyo"))) {
        return $true
    }

    $normalized = $RelativePath.Replace("\", "/")
    return (($normalized -split "/") -contains "__pycache__")
}

function Copy-ItemWithoutGeneratedPythonCache {
    param([string]$Source, [string]$Dest)

    $item = Get-Item -LiteralPath $Source -Force
    if (Test-SkipGeneratedPythonCache -Item $item -RelativePath $item.Name) {
        return $false
    }

    if ($item.PSIsContainer) {
        if (-not (Test-Path $Dest)) {
            New-Item -ItemType Directory -Force -Path $Dest | Out-Null
        }

        foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Force) {
            $childDest = Join-Path $Dest $child.Name
            Copy-ItemWithoutGeneratedPythonCache -Source $child.FullName -Dest $childDest | Out-Null
        }
    } else {
        $destDir = Split-Path -Parent $Dest
        if (-not (Test-Path $destDir)) {
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        }
        Copy-Item -LiteralPath $item.FullName -Destination $Dest -Force
    }

    return $true
}


function Copy-DirectoryWithPrompt {
    param([string]$Source, [string]$Dest, [string[]]$SkipRelativePaths = @(), [string]$Base = $Source)

    if (-not (Test-Path $Dest)) {
        New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    }

    foreach ($child in Get-ChildItem -Path $Source -Force) {
        $relative = $child.FullName.Substring($Base.Length).TrimStart("\", "/")
        $normalized = $relative.Replace("\", "/")
        if (($SkipRelativePaths -contains $normalized) -or (Test-SkipGeneratedPythonCache -Item $child -RelativePath $normalized)) {
            continue
        }


        $childDest = Join-Path $Dest $child.Name
        if ($child.PSIsContainer) {
            Copy-DirectoryWithPrompt -Source $child.FullName -Dest $childDest -SkipRelativePaths $SkipRelativePaths -Base $Base
        } else {
            Copy-FileWithPrompt -Source $child.FullName -Dest $childDest
        }
    }
}

function Copy-Skills {
    param([string]$Source, [string]$Dest)

    if (-not $Source -or -not (Test-Path $Source)) {
        return
    }

    New-Item -ItemType Directory -Force -Path $Dest | Out-Null
    $copiedCount = 0
    $skippedCount = 0

    foreach ($skill in Get-ChildItem -Path $Source -Force) {
        if (Test-SkipGeneratedPythonCache -Item $skill -RelativePath $skill.Name) {
            continue
        }

        $targetSkillPath = Join-Path $Dest $skill.Name
        if (Test-Path $targetSkillPath) {
            if ($Force) {
                Copy-ItemWithoutGeneratedPythonCache -Source $skill.FullName -Dest $targetSkillPath | Out-Null
                $copiedCount++
                Write-Host "  [OVERWROTE] Skill '$($skill.Name)'" -ForegroundColor Yellow
            } else {
                Write-Host "  [EXISTS]   Skill '$($skill.Name)' already exists in target." -ForegroundColor DarkYellow
                $overwrite = Read-Host "           Overwrite? (y/N)"
                if ($overwrite -eq "y" -or $overwrite -eq "Y") {
                    Copy-ItemWithoutGeneratedPythonCache -Source $skill.FullName -Dest $targetSkillPath | Out-Null
                    $copiedCount++
                    Write-Host "           Overwritten." -ForegroundColor Yellow
                } else {
                    $skippedCount++
                    Write-Host "           Skipped." -ForegroundColor DarkYellow
                }
            }
        } else {
            Copy-ItemWithoutGeneratedPythonCache -Source $skill.FullName -Dest $targetSkillPath | Out-Null
            $copiedCount++
        }
    }

    Write-Host "  [SKILLS]   $copiedCount copied, $skippedCount skipped" -ForegroundColor Green
}

function Copy-InstructionFile {
    param([object]$Profile, [string]$LoadoutPath, [string]$Target)

    $sourceFile = Join-RepoPath $LoadoutPath $Profile.InstructionFile
    foreach ($alias in $Profile.InstructionAliases) {
        if (-not (Test-Path $sourceFile)) {
            $sourceFile = Join-RepoPath $LoadoutPath $alias
        }
    }

    if (-not (Test-Path $sourceFile)) {
        return
    }

    $targetFile = Join-RepoPath $Target $Profile.InstructionFile
    $loadoutContent = [System.IO.File]::ReadAllText($sourceFile)

    if (Test-Path $targetFile) {
        $existing = [System.IO.File]::ReadAllText($targetFile)
        if ($existing.Contains($loadoutContent.Trim())) {
            Write-Host "  [SKIPPED]  $($Profile.InstructionFile) (loadout content already present)" -ForegroundColor DarkYellow
        } else {
            $date = Get-Date -Format "yyyy-MM-dd"
            $separator = "`n`n---`n`n<!-- Loadout: $Loadout; harness: $($Profile.Name); applied $date -->`n`n"
            [System.IO.File]::WriteAllText($targetFile, $existing + $separator + $loadoutContent)
            Write-Host "  [APPENDED] $($Profile.InstructionFile)" -ForegroundColor Yellow
        }
    } else {
        [System.IO.File]::WriteAllText($targetFile, $loadoutContent)
        Write-Host "  [COPIED]   $($Profile.InstructionFile)" -ForegroundColor Green
    }
}

function Get-RepoRelativePath {
    param([string]$Path)
    return $Path.Replace($Target, "").TrimStart("\", "/").Replace("\", "/")
}

function Test-FileContentMatches {
    param([string]$Source, [string]$Dest)

    if (-not (Test-Path $Dest -PathType Leaf)) {
        return $false
    }

    $sourceInfo = Get-Item -LiteralPath $Source
    $destInfo = Get-Item -LiteralPath $Dest
    if ($sourceInfo.Length -ne $destInfo.Length) {
        return $false
    }

    $sourceBytes = [System.IO.File]::ReadAllBytes($Source)
    $destBytes = [System.IO.File]::ReadAllBytes($Dest)
    for ($index = 0; $index -lt $sourceBytes.Length; $index++) {
        if ($sourceBytes[$index] -ne $destBytes[$index]) {
            return $false
        }
    }

    return $true
}

function Add-PlannedChange {
    param([System.Collections.Generic.List[string]]$Changes, [string]$Dest)

    $relative = Get-RepoRelativePath -Path $Dest
    if (-not $Changes.Contains($relative)) {
        [void]$Changes.Add($relative)
    }
}

function Add-PlannedFileChange {
    param([System.Collections.Generic.List[string]]$Changes, [string]$Source, [string]$Dest)

    if (-not (Test-FileContentMatches -Source $Source -Dest $Dest)) {
        Add-PlannedChange -Changes $Changes -Dest $Dest
    }
}

function Add-PlannedItemChanges {
    param([System.Collections.Generic.List[string]]$Changes, [string]$Source, [string]$Dest, [string]$RelativePath = "")

    $item = Get-Item -LiteralPath $Source -Force
    $relative = if ([string]::IsNullOrWhiteSpace($RelativePath)) { $item.Name } else { $RelativePath }
    if (Test-SkipGeneratedPythonCache -Item $item -RelativePath $relative) {
        return
    }

    if ($item.PSIsContainer) {
        foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Force) {
            $childRelative = if ([string]::IsNullOrWhiteSpace($relative)) { $child.Name } else { "$relative/$($child.Name)" }
            Add-PlannedItemChanges -Changes $Changes -Source $child.FullName -Dest (Join-Path $Dest $child.Name) -RelativePath $childRelative
        }
    } else {
        Add-PlannedFileChange -Changes $Changes -Source $item.FullName -Dest $Dest
    }
}

function Add-PlannedDirectoryChanges {
    param([System.Collections.Generic.List[string]]$Changes, [string]$Source, [string]$Dest, [string[]]$SkipRelativePaths = @(), [string]$Base = $Source)

    foreach ($child in Get-ChildItem -Path $Source -Force) {
        $relative = $child.FullName.Substring($Base.Length).TrimStart("\", "/")
        $normalized = $relative.Replace("\", "/")
        if (($SkipRelativePaths -contains $normalized) -or (Test-SkipGeneratedPythonCache -Item $child -RelativePath $normalized)) {
            continue
        }

        $childDest = Join-Path $Dest $child.Name
        if ($child.PSIsContainer) {
            Add-PlannedDirectoryChanges -Changes $Changes -Source $child.FullName -Dest $childDest -SkipRelativePaths $SkipRelativePaths -Base $Base
        } else {
            Add-PlannedFileChange -Changes $Changes -Source $child.FullName -Dest $childDest
        }
    }
}

function Add-PlannedSkillsChanges {
    param([System.Collections.Generic.List[string]]$Changes, [string]$Source, [string]$Dest)

    if (-not $Source -or -not (Test-Path $Source)) {
        return
    }

    foreach ($skill in Get-ChildItem -Path $Source -Force) {
        if (Test-SkipGeneratedPythonCache -Item $skill -RelativePath $skill.Name) {
            continue
        }

        Add-PlannedItemChanges -Changes $Changes -Source $skill.FullName -Dest (Join-Path $Dest $skill.Name) -RelativePath $skill.Name
    }
}

function Add-PlannedInstructionChange {
    param([System.Collections.Generic.List[string]]$Changes, [object]$Profile, [string]$LoadoutPath)

    $sourceFile = Join-RepoPath $LoadoutPath $Profile.InstructionFile
    foreach ($alias in $Profile.InstructionAliases) {
        if (-not (Test-Path $sourceFile)) {
            $sourceFile = Join-RepoPath $LoadoutPath $alias
        }
    }

    if (-not (Test-Path $sourceFile)) {
        return
    }

    $targetFile = Join-RepoPath $Target $Profile.InstructionFile
    $loadoutContent = [System.IO.File]::ReadAllText($sourceFile)
    if (-not (Test-Path $targetFile)) {
        Add-PlannedChange -Changes $Changes -Dest $targetFile
        return
    }

    $existing = [System.IO.File]::ReadAllText($targetFile)
    if (-not $existing.Contains($loadoutContent.Trim())) {
        Add-PlannedChange -Changes $Changes -Dest $targetFile
    }
}

function Test-HookConfigWouldChange {
    param([string]$Source, [string]$Dest)

    if (-not (Test-Path $Source)) {
        return $false
    }

    $sourceData = Get-Content -Raw $Source | ConvertFrom-Json
    if (-not (Test-Path $Dest)) {
        return $true
    }

    $destData = Get-Content -Raw $Dest | ConvertFrom-Json
    if ($sourceData.PSObject.Properties["hooks"]) {
        if (-not $destData.PSObject.Properties["hooks"]) {
            return $true
        }

        foreach ($event in $sourceData.hooks.PSObject.Properties) {
            if (-not $destData.hooks.PSObject.Properties[$event.Name]) {
                return $true
            }

            $existingKeys = @{}
            foreach ($entry in @(ConvertTo-Array $destData.hooks.$($event.Name))) {
                $existingKeys[(Get-HookEntryKey $entry)] = $true
            }
            foreach ($entry in @(ConvertTo-Array $event.Value)) {
                if (-not $existingKeys.ContainsKey((Get-HookEntryKey $entry))) {
                    return $true
                }
            }
        }
    }

    foreach ($property in $sourceData.PSObject.Properties) {
        if ($property.Name -eq "hooks") {
            continue
        }
        if (-not $destData.PSObject.Properties[$property.Name]) {
            return $true
        }
    }

    return $false
}

function Get-PlannedLoadoutChanges {
    param([object]$Profile, [string]$LoadoutPath, [bool]$SkipInstructionFile = $false)

    $changes = [System.Collections.Generic.List[string]]::new()

    if (-not $SkipInstructionFile) {
        Add-PlannedInstructionChange -Changes $changes -Profile $Profile -LoadoutPath $LoadoutPath
    }

    $skipTopLevel = @($Profile.InstructionFile) + $Profile.InstructionAliases
    $skipByConfigDir = @{}

    if ($Profile.SkillsPath) {
        $sourceSkills = $null
        foreach ($skillSourcePath in $Profile.SkillSourcePaths) {
            $candidate = Join-RepoPath $LoadoutPath $skillSourcePath
            if (Test-Path $candidate) {
                $sourceSkills = $candidate
                break
            }
        }
        Add-PlannedSkillsChanges -Changes $changes -Source $sourceSkills -Dest (Join-RepoPath $Target $Profile.SkillsPath)

        $skillsParts = $Profile.SkillsPath -split "[/\\]"
        $configDir = $skillsParts[0]
        $skipRel = ($skillsParts[1..($skillsParts.Length - 1)] -join "/")
        $skipByConfigDir[$configDir] = @($skipByConfigDir[$configDir]) + $skipRel
    }

    if ($Profile.HookConfigPath) {
        $sourceHookConfig = Join-RepoPath $LoadoutPath $Profile.HookConfigPath
        if ($Profile.PSObject.Properties["HookSourcePaths"]) {
            foreach ($hookSourcePath in $Profile.HookSourcePaths) {
                $candidate = Join-RepoPath $LoadoutPath $hookSourcePath
                if (Test-Path $candidate) {
                    $sourceHookConfig = $candidate
                    break
                }
            }
        }
        $targetHookConfig = Join-RepoPath $Target $Profile.HookConfigPath
        if (Test-HookConfigWouldChange -Source $sourceHookConfig -Dest $targetHookConfig) {
            Add-PlannedChange -Changes $changes -Dest $targetHookConfig
        }

        $hookParts = $Profile.HookConfigPath -split "[/\\]"
        $configDir = $hookParts[0]
        $skipRel = ($hookParts[1..($hookParts.Length - 1)] -join "/")
        $skipByConfigDir[$configDir] = @($skipByConfigDir[$configDir]) + $skipRel
        if ($Profile.PSObject.Properties["HookSourcePaths"]) {
            foreach ($hookSourcePath in $Profile.HookSourcePaths) {
                $sourceParts = $hookSourcePath -split "[/\\]"
                if ($sourceParts[0] -eq $configDir -or $sourceParts[0] -eq $Profile.TemplateConfigDir) {
                    $sourceSkipRel = ($sourceParts[1..($sourceParts.Length - 1)] -join "/")
                    $skipByConfigDir[$configDir] = @($skipByConfigDir[$configDir]) + $sourceSkipRel
                }
            }
        }
    }

    $knownHarnessDirs = @(".harness", ".claude", ".opencode", ".codex", ".agents", ".gemini", ".omp")
    foreach ($item in Get-ChildItem -Path $LoadoutPath -Force) {
        if ((Test-SkipGeneratedPythonCache -Item $item -RelativePath $item.Name) -or ($skipTopLevel -contains $item.Name) -or ($item.Name -eq ".harness-loadout")) {
            continue
        }
        if ($item.PSIsContainer -and ($knownHarnessDirs -contains $item.Name) -and ($item.Name -ne $Profile.TemplateConfigDir) -and -not ($Profile.ConfigDirs -contains $item.Name)) {
            continue
        }

        $destName = if ($item.PSIsContainer -and $item.Name -eq $Profile.TemplateConfigDir) { $Profile.ConfigDir } else { $item.Name }
        $destPath = Join-Path $Target $destName
        if ($item.PSIsContainer) {
            $skipRelativePaths = @()
            if ($skipByConfigDir.ContainsKey($destName)) {
                $skipRelativePaths = @($skipByConfigDir[$destName])
            }
            Add-PlannedDirectoryChanges -Changes $changes -Source $item.FullName -Dest $destPath -SkipRelativePaths $skipRelativePaths
        } else {
            Add-PlannedFileChange -Changes $changes -Source $item.FullName -Dest $destPath
        }
    }

    return @($changes | Sort-Object -Unique)
}

function Get-LoadoutUsagePath {
    param([string]$HarnessRoot)
    return Join-Path $HarnessRoot "applied-repos.json"
}

function Get-LegacyLoadoutUsagePath {
    param([string]$LoadoutPath)
    return Join-RepoPath $LoadoutPath ".harness-loadout/applied-repos.json"
}

function Read-LoadoutUsage {
    param([string]$UsagePath, [string]$LegacyUsagePath, [string]$Loadout)

    if (Test-Path $UsagePath) {
        $registry = Get-Content -Raw $UsagePath | ConvertFrom-Json
        if ($registry.PSObject.Properties["loadouts"]) {
            $entryProperty = $registry.loadouts.PSObject.Properties[$Loadout]
            if ($entryProperty) {
                $entry = $entryProperty.Value
                $usageLoadout = if ($entry.PSObject.Properties["loadout"]) { $entry.loadout } else { $Loadout }
                $repos = if ($entry.PSObject.Properties["repos"]) { @(ConvertTo-Array $entry.repos) } else { @() }
                return [PSCustomObject]@{
                    version = 1
                    loadout = $usageLoadout
                    repos = $repos
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
        $data = Get-Content -Raw $LegacyUsagePath | ConvertFrom-Json
        $usageLoadout = if ($data.PSObject.Properties["loadout"]) { $data.loadout } else { $Loadout }
        $repos = if ($data.PSObject.Properties["repos"]) { @(ConvertTo-Array $data.repos) } else { @() }

        return [PSCustomObject]@{
            version = 1
            loadout = $usageLoadout
            repos = $repos
        }
    }

    return [PSCustomObject]@{
        version = 1
        loadout = $Loadout
        repos = @()
    }
}

function Read-LoadoutUsageRegistry {
    param([string]$UsagePath)

    if (Test-Path $UsagePath) {
        $registry = Get-Content -Raw $UsagePath | ConvertFrom-Json
        $version = if ($registry.PSObject.Properties["version"]) { $registry.version } else { 1 }
        $loadouts = if ($registry.PSObject.Properties["loadouts"] -and $null -ne $registry.loadouts) { $registry.loadouts } else { [PSCustomObject]@{} }
        return [PSCustomObject]@{
            version = $version
            loadouts = $loadouts
        }
    }

    return [PSCustomObject]@{
        version = 1
        loadouts = [PSCustomObject]@{}
    }
}

function Save-LoadoutUsage {
    param([string]$HarnessRoot, [string]$LoadoutPath, [string]$Loadout, [string]$Target, [string]$Harness)

    $usagePath = Get-LoadoutUsagePath -HarnessRoot $HarnessRoot
    $legacyUsagePath = Get-LegacyLoadoutUsagePath -LoadoutPath $LoadoutPath
    $metadataDir = Split-Path -Parent $usagePath
    if ((Test-Path $metadataDir) -and -not (Test-Path $metadataDir -PathType Container)) {
        throw "Harness metadata path '$metadataDir' exists but is not a directory."
    }
    New-Item -ItemType Directory -Force -Path $metadataDir | Out-Null

    $registry = Read-LoadoutUsageRegistry -UsagePath $usagePath
    $usage = Read-LoadoutUsage -UsagePath $usagePath -LegacyUsagePath $legacyUsagePath -Loadout $Loadout
    $repos = @()
    foreach ($repo in @(ConvertTo-Array $usage.repos)) {
        if ($null -eq $repo) {
            continue
        }
        $samePath = [string]::Equals([string]$repo.path, $Target, [System.StringComparison]::OrdinalIgnoreCase)
        $sameHarness = [string]::Equals([string]$repo.harness, $Harness, [System.StringComparison]::OrdinalIgnoreCase)
        if (-not ($samePath -and $sameHarness)) {
            $repos += $repo
        }
    }

    $repos += [PSCustomObject]@{
        path = $Target
        harness = $Harness
        lastAppliedAt = (Get-Date).ToUniversalTime().ToString("o")
    }

    $entry = [PSCustomObject]@{
        loadout = $usage.loadout
        repos = @($repos | Sort-Object -Property path, harness)
    }
    $registry.loadouts | Add-Member -NotePropertyName $Loadout -NotePropertyValue $entry -Force
    $json = $registry | ConvertTo-Json -Depth 10
    [System.IO.File]::WriteAllText($usagePath, $json, [System.Text.UTF8Encoding]::new($false))
}

function Resolve-InitPromptPath {
    param([string]$Name)

    if ([string]::IsNullOrWhiteSpace($Name)) {
        throw "Init prompt name is required."
    }
    if ($Name.Contains("/") -or $Name.Contains("\") -or $Name.Contains("..")) {
        throw "Init prompt name must be a file name under init-prompts."
    }

    $fileName = if ($Name.EndsWith(".md", [System.StringComparison]::OrdinalIgnoreCase)) { $Name } else { "$Name.md" }
    $candidate = Join-Path $InitPromptsDir $fileName
    if (-not (Test-Path $candidate -PathType Leaf)) {
        throw "Init prompt '$Name' not found in '$InitPromptsDir'."
    }
    return $candidate
}

function New-HeadlessInitPrompt {
    param([string]$PromptPath, [string]$Target)

    $prompt = [System.IO.File]::ReadAllText($PromptPath)
    $rules = @'
## Headless initialization execution rules

The repository may already satisfy some or all items in this initialization prompt. Treat the prompt as an end-state checklist: inspect first, skip work that is already complete, and make only the changes needed to ensure every requested item is complete by the end of the run.

Before your final response, create `.omp/init/reports/` in this repository if needed and write a timestamped Markdown report there named `yyyyMMdd-HHmmss-init-report.md`. The report must summarize what you changed, which verification commands ran, which checks could not run, and any follow-up needed. Keep the final chat response brief and mention the report path.
'@
    return "$prompt`n`n$rules"
}

function Invoke-OmpHeadlessInitPrompt {
    param([string]$Target, [string]$PromptPath, [string]$Model)

    $promptName = [System.IO.Path]::GetFileNameWithoutExtension($PromptPath)
    $initDir = Join-RepoPath $Target ".omp/init"
    New-Item -ItemType Directory -Force -Path $initDir | Out-Null

    $promptFile = Join-Path $initDir "$promptName-headless-prompt.md"
    $outputFile = Join-Path $initDir "$promptName-headless-output.md"
    $stderrFile = Join-Path $initDir "$promptName-headless-stderr.txt"
    $prompt = New-HeadlessInitPrompt -PromptPath $PromptPath -Target $Target
    [System.IO.File]::WriteAllText($promptFile, $prompt, [System.Text.UTF8Encoding]::new($false))

    $arguments = @(
        "-p",
        "--no-session",
        "--auto-approve",
        "--approval-mode",
        "yolo"
    )
    if (-not [string]::IsNullOrWhiteSpace($Model)) {
        $arguments += @("--model", $Model)
    }
    $arguments += "@$promptFile"

    $ompCommand = @(Get-Command -Name "omp" -CommandType Application -ErrorAction Stop)[0]
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $ompCommand.Source
    $startInfo.WorkingDirectory = $Target
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.UseShellExecute = $false
    foreach ($argument in $arguments) {
        [void]$startInfo.ArgumentList.Add($argument)
    }

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    [void]$process.Start()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    $exitCode = $process.ExitCode
    $process.Dispose()

    [System.IO.File]::WriteAllText($outputFile, $stdout, [System.Text.UTF8Encoding]::new($false))
    if (-not [string]::IsNullOrEmpty($stderr)) {
        [System.IO.File]::WriteAllText($stderrFile, $stderr, [System.Text.UTF8Encoding]::new($false))
    }

    if ($exitCode -ne 0) {
        [Console]::Out.Write($stdout)
        [Console]::Error.Write($stderr)
        Write-Host "Error: Headless init prompt '$promptName' failed with exit code $exitCode." -ForegroundColor Red
        exit $exitCode
    }

    Remove-Item -Path $promptFile -Force
    [Console]::Out.Write($stdout)
    Write-Host "Headless init prompt '$promptName' completed. Output: .omp/init/$promptName-headless-output.md" -ForegroundColor Cyan
}

if ($List) {
    Write-Host "Available loadouts:"
    Get-ChildItem -Path $LoadoutsDir -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }
    Write-Host ""
    Write-Host "Harnesses: opencode, codex, gemini, claude (alias: claude-code), omp"
    exit 0
}

if ($InitPrompt -and -not $Headless) {
    Write-Host "Error: -Headless is required when -InitPrompt is used." -ForegroundColor Red
    exit 1
}

if ($Headless -and -not $InitPrompt) {
    Write-Host "Error: -Headless requires -InitPrompt <name>." -ForegroundColor Red
    exit 1
}

if ($PlanChanges -and $InitPrompt) {
    Write-Host "Error: -PlanChanges cannot be used with -InitPrompt." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $Target -PathType Container)) {
    Write-Host "Error: Target '$Target' is not a directory." -ForegroundColor Red
    exit 1
}
$Target = (Resolve-Path $Target).Path

if ($InitPrompt) {
    try {
        $promptPath = Resolve-InitPromptPath -Name $InitPrompt
        Invoke-OmpHeadlessInitPrompt -Target $Target -PromptPath $promptPath -Model $Model
    } catch {
        Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
        exit 1
    }
    exit 0
}

if (-not $Loadout) {
    Write-Host "Error: -Loadout is required. Use -List to see available loadouts." -ForegroundColor Red
    exit 1
}

if (-not $Harness) {
    Write-Host "Error: -Harness is required. Supported values: opencode, codex, gemini, claude, claude-code, omp." -ForegroundColor Red
    exit 1
}

$LoadoutPath = Join-Path $LoadoutsDir $Loadout
if (-not (Test-Path $LoadoutPath)) {
    Write-Host "Error: Loadout '$Loadout' not found." -ForegroundColor Red
    Write-Host "Available loadouts:"
    Get-ChildItem -Path $LoadoutsDir -Directory | ForEach-Object { Write-Host "  - $($_.Name)" }
    exit 1
}

$profile = Get-HarnessProfile $Harness
if ($PlanChanges) {
    Write-Host "Planning loadout '$Loadout' for '$Harness' to: $Target" -ForegroundColor Cyan
    $plannedChanges = @(Get-PlannedLoadoutChanges -Profile $profile -LoadoutPath $LoadoutPath -SkipInstructionFile $SkipInstructionFile)
    if ($plannedChanges.Count -eq 0) {
        Write-Host "  [NO CHANGES] No file changes planned" -ForegroundColor DarkYellow
    } else {
        foreach ($plannedChange in $plannedChanges) {
            Write-Host "  [WOULD CHANGE] $plannedChange" -ForegroundColor Yellow
        }
    }
    exit 0
}
Write-Host "Applying loadout '$Loadout' for '$Harness' to: $Target" -ForegroundColor Cyan

if (-not $SkipInstructionFile) {
    Copy-InstructionFile -Profile $profile -LoadoutPath $LoadoutPath -Target $Target
}

if ($profile.SkillsPath) {
    $sourceSkills = $null
    foreach ($skillSourcePath in $profile.SkillSourcePaths) {
        $candidate = Join-RepoPath $LoadoutPath $skillSourcePath
        if (Test-Path $candidate) {
            $sourceSkills = $candidate
            break
        }
    }
    $targetSkills = Join-RepoPath $Target $profile.SkillsPath
    Copy-Skills -Source $sourceSkills -Dest $targetSkills
}

$skipTopLevel = @($profile.InstructionFile) + $profile.InstructionAliases
$skipByConfigDir = @{}

if ($profile.SkillsPath) {
    $skillsParts = $profile.SkillsPath -split "[/\\]"
    $configDir = $skillsParts[0]
    $skipRel = ($skillsParts[1..($skillsParts.Length - 1)] -join "/")
    $skipByConfigDir[$configDir] = @($skipByConfigDir[$configDir]) + $skipRel
}

if ($profile.HookConfigPath) {
    $sourceHookConfig = Join-RepoPath $LoadoutPath $profile.HookConfigPath
    if ($profile.PSObject.Properties["HookSourcePaths"]) {
        foreach ($hookSourcePath in $profile.HookSourcePaths) {
            $candidate = Join-RepoPath $LoadoutPath $hookSourcePath
            if (Test-Path $candidate) {
                $sourceHookConfig = $candidate
                break
            }
        }
    }
    $targetHookConfig = Join-RepoPath $Target $profile.HookConfigPath
    Merge-HookConfig -Source $sourceHookConfig -Dest $targetHookConfig

    $hookParts = $profile.HookConfigPath -split "[/\\]"
    $configDir = $hookParts[0]
    $skipRel = ($hookParts[1..($hookParts.Length - 1)] -join "/")
    $skipByConfigDir[$configDir] = @($skipByConfigDir[$configDir]) + $skipRel
    if ($profile.PSObject.Properties["HookSourcePaths"]) {
        foreach ($hookSourcePath in $profile.HookSourcePaths) {
            $sourceParts = $hookSourcePath -split "[/\\]"
            if ($sourceParts[0] -eq $configDir -or $sourceParts[0] -eq $profile.TemplateConfigDir) {
                $sourceSkipRel = ($sourceParts[1..($sourceParts.Length - 1)] -join "/")
                $skipByConfigDir[$configDir] = @($skipByConfigDir[$configDir]) + $sourceSkipRel
            }
        }
    }
}

$knownHarnessDirs = @(".harness", ".claude", ".opencode", ".codex", ".agents", ".gemini", ".omp")

foreach ($item in Get-ChildItem -Path $LoadoutPath -Force) {
    if ((Test-SkipGeneratedPythonCache -Item $item -RelativePath $item.Name) -or ($skipTopLevel -contains $item.Name) -or ($item.Name -eq ".harness-loadout")) {
        continue
    }
    if ($item.PSIsContainer -and ($knownHarnessDirs -contains $item.Name) -and ($item.Name -ne $profile.TemplateConfigDir) -and -not ($profile.ConfigDirs -contains $item.Name)) {
        continue
    }

    $destName = if ($item.PSIsContainer -and $item.Name -eq $profile.TemplateConfigDir) { $profile.ConfigDir } else { $item.Name }
    $destPath = Join-Path $Target $destName
    if ($item.PSIsContainer) {
        $skipRelativePaths = @()
        if ($skipByConfigDir.ContainsKey($destName)) {
            $skipRelativePaths = @($skipByConfigDir[$destName])
        }
        Copy-DirectoryWithPrompt -Source $item.FullName -Dest $destPath -SkipRelativePaths $skipRelativePaths
    } else {
        Copy-FileWithPrompt -Source $item.FullName -Dest $destPath
    }
}

Save-LoadoutUsage -HarnessRoot $ScriptRoot -LoadoutPath $LoadoutPath -Loadout $Loadout -Target $Target -Harness $profile.Name

Write-Host "`nDone!" -ForegroundColor Cyan
