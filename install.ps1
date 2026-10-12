# Install or update termwraith (Windows). Re-run to update.
#   irm https://raw.githubusercontent.com/linkinxp/TermWraith/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$Repo = if ($env:TERMWRAITH_REPO) { $env:TERMWRAITH_REPO } else { "https://github.com/linkinxp/TermWraith.git" }
$Base = Join-Path $env:LOCALAPPDATA "termwraith"
$Src = Join-Path $Base "src"
$Bin = Join-Path $Base "bin"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "termwraith: git is required" }

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PyCmd = @("py", "-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PyCmd = @("python")
} else {
    throw "termwraith: Python 3.10 or newer is required"
}

if (Test-Path (Join-Path $Src ".git")) {
    git -C $Src pull --ff-only -q
} else {
    git clone -q $Repo $Src
}

$Venv = Join-Path $Src ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    & $PyCmd[0] @($PyCmd[1..($PyCmd.Length - 1)]) -m venv $Venv
}
& $VenvPy -m pip install -q --upgrade pip
& $VenvPy -m pip install -q $Src

New-Item -ItemType Directory -Force -Path $Bin | Out-Null
$Launcher = "@echo off`r`n`"$Venv\Scripts\termwraith.exe`" %*`r`n"
Set-Content -Path (Join-Path $Bin "termwraith.cmd") -Value $Launcher -NoNewline

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ";") -notcontains $Bin) {
    [Environment]::SetEnvironmentVariable("Path", (($UserPath, $Bin) -join ";").TrimStart(";"), "User")
    Write-Host "Added $Bin to your user PATH. Open a new terminal."
}
Write-Host "termwraith installed in $Src. Run: termwraith"
