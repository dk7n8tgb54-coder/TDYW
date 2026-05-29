# Git Hooks Install Script for Windows
# Usage: .\scripts\install-hooks.ps1

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptDir
$HooksDir = Join-Path $ProjectRoot ".git\hooks"

Write-Host "=========================================="
Write-Host "       Installing Git Hooks"
Write-Host "=========================================="
Write-Host ""
Write-Host "Project Root: $ProjectRoot"
Write-Host ""

# Check if git repository
try {
    $GitRoot = git rev-parse --show-toplevel 2>$null
    if (-not $GitRoot) {
        Write-Host "Error: Not a git repository" -ForegroundColor Red
        exit 1
    }
    $ProjectRoot = $GitRoot
    $HooksDir = Join-Path $ProjectRoot ".git\hooks"
} catch {
    Write-Host "Error: Git command failed. Is git installed?" -ForegroundColor Red
    exit 1
}

# Create hooks directory
if (-not (Test-Path $HooksDir)) {
    New-Item -ItemType Directory -Path $HooksDir -Force | Out-Null
}

# Install pre-commit hook
$SourceHook = Join-Path $ScriptDir "hooks\pre-commit"
$TargetHook = Join-Path $HooksDir "pre-commit"

if (Test-Path $SourceHook) {
    Copy-Item $SourceHook $TargetHook -Force
    Write-Host "OK: pre-commit hook installed" -ForegroundColor Green
} else {
    Write-Host "Error: pre-commit hook not found" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=========================================="
Write-Host "  Git Hooks Installation Complete"
Write-Host "=========================================="
Write-Host ""
Write-Host "Enabled hooks:"
Write-Host "  - pre-commit: code quality check before commit"
Write-Host ""
Write-Host "To skip checks in emergency:"
Write-Host "  git commit --no-verify"
Write-Host ""
