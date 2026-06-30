#requires -version 5.1
<#
.SYNOPSIS
  Build a standalone Windows VidComp.exe (console kept enabled for debugging).

.DESCRIPTION
  Wraps PyInstaller using `VidComp.spec`.  The produced binary keeps a console
  window so any startup error, traceback or `--debug` output is visible.

  If `ffmpeg.exe`, `ffprobe.exe` or `fpcalc.exe` are placed beside this script
  before building, they will be bundled into `dist\VidComp\` automatically.

.EXAMPLE
  .\build.ps1                # standard build, console kept on
  .\build.ps1 -Clean         # clean build/ and dist/ first
  .\build.ps1 -Debug         # also produce a launcher that forces --debug
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Debug
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Resolve-Python {
    if (Test-Path '.\.venv\Scripts\python.exe') {
        return (Resolve-Path '.\.venv\Scripts\python.exe').Path
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "No Python found. Create .venv or put python.exe on PATH."
}

$py = Resolve-Python
Write-Host "[VidComp] Using Python: $py"

if ($Clean) {
    Write-Host "[VidComp] Cleaning build/ and dist/ ..."
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist
}

Write-Host "[VidComp] Ensuring PyInstaller is installed..."
& $py -m pip install --quiet --upgrade pyinstaller

Write-Host "[VidComp] Running PyInstaller against VidComp.spec (console=True)..."
& $py -m PyInstaller --noconfirm VidComp.spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed (exit $LASTEXITCODE)"
}

if ($Debug) {
    $launcher = Join-Path (Resolve-Path .\dist\VidComp) 'VidComp-debug.cmd'
    Set-Content -Path $launcher -Encoding ASCII -Value @'
@echo off
REM Force DEBUG-level logging for this run.
set VIDCOMP_DEBUG=1
"%~dp0VidComp.exe" --debug %*
'@
    Write-Host "[VidComp] Wrote debug launcher: $launcher"
}

Write-Host "[VidComp] Done. See dist\VidComp\VidComp.exe"
Write-Host "[VidComp] The exe was built with console=True - run from a"
Write-Host "[VidComp] terminal (cmd / PowerShell) to see live log output,"
Write-Host "[VidComp] and also check %APPDATA%\VidComp\logs\vidcomp.log."
