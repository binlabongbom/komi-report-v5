# Dot-source this file before developing: . .\tools\activate-dev.ps1
$komiProjectRoot = Split-Path -Parent $PSScriptRoot
$komiNodeVersion = (Get-Content -LiteralPath (Join-Path $komiProjectRoot '.node-version') -Raw).Trim()
$komiNodeDirectory = Join-Path $komiProjectRoot ".tools/node-v$komiNodeVersion-win-x64"
$komiPythonDirectory = Join-Path $komiProjectRoot '.venv/Scripts'
$komiGitDirectory = Join-Path $komiProjectRoot '.tools/git-2.55.0.5/cmd'
if (-not (Test-Path -LiteralPath (Join-Path $komiNodeDirectory 'node.exe'))) {
    throw "Project Node runtime missing: $komiNodeDirectory"
}
if (-not (Test-Path -LiteralPath (Join-Path $komiPythonDirectory 'python.exe'))) {
    throw "Project Python environment missing: $komiPythonDirectory"
}
$env:PATH = "$komiPythonDirectory;$komiNodeDirectory;$komiGitDirectory;$env:PATH"
$env:VIRTUAL_ENV = Join-Path $komiProjectRoot '.venv'
$env:PYTHONUTF8 = '1'
$env:KOMI_PROJECT_ROOT = $komiProjectRoot
$env:KOMI_SOURCE_ROOT = Join-Path $komiProjectRoot 'source'
$env:PYTHONPATH = $env:KOMI_SOURCE_ROOT
