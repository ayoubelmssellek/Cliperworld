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
Ensure-Clone "https://github.com/ColinGPT9/clips-studio.git" "vendor/clips-studio"
Ensure-Clone "https://github.com/m-bain/whisperX.git" "vendor/whisperX"
Ensure-Clone "https://github.com/Breakthrough/PySceneDetect.git" "vendor/PySceneDetect"
Ensure-Clone "https://github.com/WyattBlue/auto-editor.git" "vendor/auto-editor"
Ensure-Clone "https://github.com/daylennguyen/vertify.git" "vendor/vertify"
# auto-clipper topic — facecam YuNet / gaming layouts
Ensure-Clone "https://github.com/gummybearansh/Auto-Clipper.git" "vendor/Auto-Clipper"
Ensure-Clone "https://github.com/xAmirHamza77/StreamCut.git" "vendor/StreamCut"
Ensure-Clone "https://github.com/HmdNvd/Gaming-Clipper.git" "vendor/Gaming-Clipper"

$cliDir = "vendor/bin/TwitchDownloaderCLI"
$cliExe = Join-Path $cliDir "TwitchDownloaderCLI.exe"
if (-not (Test-Path $cliExe)) {
  $zip = "vendor/bin/TwitchDownloaderCLI.zip"
  $url = "https://github.com/lay295/TwitchDownloader/releases/download/1.56.5/TwitchDownloaderCLI-1.56.5-Windows-x64.zip"
  Write-Host "Downloading TwitchDownloaderCLI release..."
  Invoke-WebRequest -Uri $url -OutFile $zip
  Expand-Archive -Path $zip -DestinationPath $cliDir -Force
}

# Vertify Windows CLI (16:9 -> 9:16 Shorts with blur fill)
$vertifyDir = "vendor/bin/vertify"
$vertifyExe = Join-Path $vertifyDir "vertify.exe"
if (-not (Test-Path $vertifyExe)) {
  New-Item -ItemType Directory -Force -Path $vertifyDir | Out-Null
  $vZip = "vendor/bin/vertify.zip"
  $vUrl = "https://github.com/daylennguyen/vertify/releases/download/v0.1.1-ae1b686/vertify-v0.1.1-ae1b686-windows-x64.zip"
  Write-Host "Downloading Vertify release..."
  Invoke-WebRequest -Uri $vUrl -OutFile $vZip
  Expand-Archive -Path $vZip -DestinationPath $vertifyDir -Force
  # Release zip may nest one folder — flatten exe to vendor/bin/vertify/vertify.exe
  $nested = Get-ChildItem $vertifyDir -Recurse -Filter "vertify.exe" | Select-Object -First 1
  if ($nested -and $nested.DirectoryName -ne (Resolve-Path $vertifyDir).Path) {
    Copy-Item $nested.FullName $vertifyExe -Force
    $ff = Join-Path $nested.DirectoryName "ffmpeg.exe"
    $fp = Join-Path $nested.DirectoryName "ffprobe.exe"
    if (Test-Path $ff) { Copy-Item $ff (Join-Path $vertifyDir "ffmpeg.exe") -Force }
    if (Test-Path $fp) { Copy-Item $fp (Join-Path $vertifyDir "ffprobe.exe") -Force }
  }
}

Write-Host "Vendor ready."
Get-ChildItem vendor | Select-Object Name
