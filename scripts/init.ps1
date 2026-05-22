#Requires -Version 5.1
<#
.SYNOPSIS
    Copy the dev-on-leash project-agnostic layer into a target repo.

.DESCRIPTION
    Usage: .\scripts\init.ps1 <target-repo-path>

    Copies:
      scripts/harness/           -> <target>/scripts/harness/   (skipped if already exists)
      templates/task-schema.md   -> <target>/docs/task-schema.md
      templates/plan-template.md -> <target>/docs/plan-template.md
      Creates empty               <target>/docs/plans/

    Does NOT touch CLAUDE.md or AGENTS.md -- those are bootstrap-skill's job.
    Idempotent: re-running on an already-initialized repo prints warnings and
    skips, never clobbers existing files.

.PARAMETER TargetPath
    Path to the target repository root.
#>
param(
    [Parameter(Position=0, Mandatory=$false)]
    [string]$TargetPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Validate argument
# ---------------------------------------------------------------------------
if (-not $TargetPath -or $TargetPath.Trim() -eq '') {
    Write-Host 'ERROR: missing required argument <target-repo-path>' -ForegroundColor Red
    Write-Host "Usage: .\scripts\init.ps1 <target-repo-path>"
    exit 1
}

if (-not (Test-Path -LiteralPath $TargetPath -PathType Container)) {
    Write-Host "ERROR: target path does not exist or is not a directory: $TargetPath" -ForegroundColor Red
    exit 1
}

# Resolve to absolute path
$Target = (Resolve-Path -LiteralPath $TargetPath).Path

# ---------------------------------------------------------------------------
# Resolve plugin root: parent of the directory that contains this script.
# $PSScriptRoot is always the directory containing init.ps1 (i.e. scripts/).
# ---------------------------------------------------------------------------
$PluginRoot = Split-Path -Parent $PSScriptRoot

# ---------------------------------------------------------------------------
# Source paths
# ---------------------------------------------------------------------------
$SrcHarness = Join-Path $PluginRoot 'scripts\harness'
$SrcSchema  = Join-Path $PluginRoot 'templates\task-schema.md'
$SrcPlan    = Join-Path $PluginRoot 'templates\plan-template.md'

# ---------------------------------------------------------------------------
# Destination paths
# ---------------------------------------------------------------------------
$DstHarness  = Join-Path $Target 'scripts\harness'
$DstDocs     = Join-Path $Target 'docs'
$DstSchema   = Join-Path $DstDocs 'task-schema.md'
$DstPlan     = Join-Path $DstDocs 'plan-template.md'
$DstPlansDir = Join-Path $DstDocs 'plans'

$Copied  = [System.Collections.Generic.List[string]]::new()
$Skipped = [System.Collections.Generic.List[string]]::new()
$Created = [System.Collections.Generic.List[string]]::new()

# ---------------------------------------------------------------------------
# 1. Copy scripts/harness/ -- skip (do not clobber) if already present
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $DstHarness) {
    Write-Warning "scripts/harness/ already exists at '$DstHarness' -- skipping to avoid clobbering."
    $Skipped.Add('scripts/harness/')
} else {
    $DstScriptsDir = Join-Path $Target 'scripts'
    if (-not (Test-Path -LiteralPath $DstScriptsDir -PathType Container)) {
        New-Item -ItemType Directory -Path $DstScriptsDir | Out-Null
    }
    Copy-Item -Path $SrcHarness -Destination $DstScriptsDir -Recurse
    # Remove Python bytecode caches that may have been copied from the source.
    Get-ChildItem -LiteralPath $DstHarness -Recurse -Filter '__pycache__' -Directory |
        Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath $DstHarness -Recurse -Filter '*.pyc' -File |
        Remove-Item -Force
    Write-Host 'Copied:  scripts/harness/'
    $Copied.Add('scripts/harness/')
}

# ---------------------------------------------------------------------------
# 1b. Ensure scripts/__init__.py -- the harness does `from scripts.harness...`,
#     which needs scripts/ to resolve as a package root.
# ---------------------------------------------------------------------------
$DstScriptsInit = Join-Path $Target 'scripts\__init__.py'
if (-not (Test-Path -LiteralPath $DstScriptsInit)) {
    $DstScriptsDir = Join-Path $Target 'scripts'
    if (-not (Test-Path -LiteralPath $DstScriptsDir -PathType Container)) {
        New-Item -ItemType Directory -Path $DstScriptsDir | Out-Null
    }
    New-Item -ItemType File -Path $DstScriptsInit | Out-Null
    Write-Host 'Created: scripts/__init__.py'
    $Created.Add('scripts/__init__.py')
}

# ---------------------------------------------------------------------------
# 2. Ensure docs/ exists
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $DstDocs -PathType Container)) {
    New-Item -ItemType Directory -Path $DstDocs | Out-Null
}

# ---------------------------------------------------------------------------
# 3. Copy task-schema.md
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $DstSchema) {
    Write-Host 'Skipped: docs/task-schema.md (already exists)'
    $Skipped.Add('docs/task-schema.md')
} else {
    Copy-Item -Path $SrcSchema -Destination $DstSchema
    Write-Host 'Copied:  docs/task-schema.md'
    $Copied.Add('docs/task-schema.md')
}

# ---------------------------------------------------------------------------
# 4. Copy plan-template.md
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $DstPlan) {
    Write-Host 'Skipped: docs/plan-template.md (already exists)'
    $Skipped.Add('docs/plan-template.md')
} else {
    Copy-Item -Path $SrcPlan -Destination $DstPlan
    Write-Host 'Copied:  docs/plan-template.md'
    $Copied.Add('docs/plan-template.md')
}

# ---------------------------------------------------------------------------
# 5. Create docs/plans/ directory
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $DstPlansDir -PathType Container) {
    Write-Host 'Skipped: docs/plans/ (already exists)'
    $Skipped.Add('docs/plans/')
} else {
    New-Item -ItemType Directory -Path $DstPlansDir | Out-Null
    Write-Host 'Created: docs/plans/'
    $Created.Add('docs/plans/')
}

# ---------------------------------------------------------------------------
# 6. Copy the opt-in pre-commit hook into .harness/hooks/ (NOT activated)
# ---------------------------------------------------------------------------
$SrcHook     = Join-Path $PluginRoot 'templates\hooks\pre-commit'
$DstHooksDir = Join-Path $Target '.harness\hooks'
$DstHook     = Join-Path $DstHooksDir 'pre-commit'
if (Test-Path -LiteralPath $DstHook) {
    Write-Host 'Skipped: .harness/hooks/pre-commit (already exists)'
    $Skipped.Add('.harness/hooks/pre-commit')
} else {
    if (-not (Test-Path -LiteralPath $DstHooksDir -PathType Container)) {
        New-Item -ItemType Directory -Path $DstHooksDir -Force | Out-Null
    }
    Copy-Item -Path $SrcHook -Destination $DstHook
    Write-Host 'Copied:  .harness/hooks/pre-commit'
    $Copied.Add('.harness/hooks/pre-commit')
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '--- dev-on-leash init summary ---'
Write-Host "Target: $Target"
if ($Copied.Count -gt 0)  { Write-Host ('Copied:  ' + ($Copied  -join ', ')) }
if ($Created.Count -gt 0) { Write-Host ('Created: ' + ($Created -join ', ')) }
if ($Skipped.Count -gt 0) { Write-Host ('Skipped: ' + ($Skipped -join ', ')) }
Write-Host '--- done ---'
