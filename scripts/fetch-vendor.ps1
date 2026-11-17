$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force -Path vendor, vendor\bin | Out-Null

function Ensure-Clone($url, $dest) {
  if (Test-Path (Join-Path $dest ".git")) {
    Write-Host "OK exists: $dest"
    return
  }
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  Write-Host "Cloning $url -> $dest"
  git clone --depth 1 $url $dest
}

Ensure-Clone "https://github.com/lay295/TwitchDownloader.git" "vendor/TwitchDownloader"
Ensure-Clone "https://github.com/mutonby/openshorts.git" "vendor/openshorts"
Ensure-Clone "https://github.com/m-bain/whisperX.git" "vendor/whisperX"
Ensure-Clone "https://github.com/Breakthrough/PySceneDetect.git" "vendor/PySceneDetect"
Ensure-Clone "https://github.com/WyattBlue/auto-editor.git" "vendor/auto-editor"

$cliDir = "vendor/bin/TwitchDownloaderCLI"
$cliExe = Join-Path $cliDir "TwitchDownloaderCLI.exe"
if (-not (Test-Path $cliExe)) {
  $zip = "vendor/bin/TwitchDownloaderCLI.zip"
  $url = "https://github.com/lay295/TwitchDownloader/releases/download/1.56.5/TwitchDownloaderCLI-1.56.5-Windows-x64.zip"
  Write-Host "Downloading TwitchDownloaderCLI release..."
  Invoke-WebRequest -Uri $url -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $cliDir -Force
}

Write-Host "Vendor ready."
Get-ChildItem vendor | Select-Object Name
