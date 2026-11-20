$ErrorActionPreference = "Stop"
Write-Host "Clips Kitty brain setup (Gemma via Ollama)"
Write-Host "========================================="

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
  Write-Host "Ollama not found."
  Write-Host "1) Install from https://ollama.com/download  (or: winget install Ollama.Ollama)"
  Write-Host "2) Re-open this terminal"
  Write-Host "3) Re-run: .\\scripts\\setup-gemma.ps1"
  exit 1
}

Write-Host "Ollama OK: $($ollama.Source)"
# Weak / CPU PCs: gemma3:4b (~2.5GB). Stronger GPU: gemma:7b
$model = if ($env:CLIPER_GEMMA_MODEL) { $env:CLIPER_GEMMA_MODEL } else { "gemma3:4b" }
Write-Host "Pulling $model (good for weaker PCs)..."
ollama pull $model

Write-Host ""
Write-Host "Installed models:"
ollama list
Write-Host ""
Write-Host "Restart the Cliperworld API, then check that gemma shows ready in the UI."
Write-Host "Tips for weak PCs: use 360p/480p quality, fewer clips, close Chrome tabs."
