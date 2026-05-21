# PowerShell parity wrapper around check_regression.py.
$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
& python "$RepoRoot\scripts\harness\check_regression.py" $args
exit $LASTEXITCODE
