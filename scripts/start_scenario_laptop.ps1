# Start the local CPU planner and run the existing workbench in this terminal.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$portableOllama = Join-Path $projectRoot 'vendor/ollama/ollama.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Install the lightweight application as described under Run on the laptop in README.md.'
}
$modelPort = if ($env:FAILUREFORGE_OLLAMA_PORT) { [int]$env:FAILUREFORGE_OLLAMA_PORT } else { 11434 }
$modelName = if ($env:FAILUREFORGE_SCENARIO_MODEL) { $env:FAILUREFORGE_SCENARIO_MODEL } else { 'qwen2.5:3b' }
$env:OLLAMA_HOST = "127.0.0.1:$modelPort"
$env:OLLAMA_NO_CLOUD = '1'

function Get-ModelInventory {
    try {
        return Invoke-RestMethod -Uri "http://127.0.0.1:$modelPort/api/tags" -TimeoutSec 2
    } catch {
        return $null
    }
}

$inventory = Get-ModelInventory
if ($null -eq $inventory) {
    $runtime = if (Test-Path -LiteralPath $portableOllama) {
        $env:OLLAMA_MODELS = Join-Path $projectRoot 'models/ollama'
        $portableOllama
    } else {
        (Get-Command ollama -ErrorAction SilentlyContinue).Source
    }
    if ($runtime) {
        $env:CUDA_VISIBLE_DEVICES = '-1'
        Start-Process -FilePath $runtime -ArgumentList 'serve' -WorkingDirectory $projectRoot -WindowStyle Hidden
        for ($attempt = 0; $attempt -lt 15 -and $null -eq $inventory; $attempt++) {
            Start-Sleep -Milliseconds 400
            $inventory = Get-ModelInventory
        }
    }
}
if ($null -eq $inventory) {
    Write-Host 'The CPU analysis workbench is available. Install or start local Ollama to enable AI suggestions.'
} elseif ($modelName -notin $inventory.models.name -and "${modelName}:latest" -notin $inventory.models.name) {
    Write-Host "Install the selected model with ollama pull $modelName, then refresh Discover scenarios."
}
Push-Location -LiteralPath $projectRoot
try {
    try { $appHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2 } catch { $appHealth = $null }
    if ($appHealth.status -eq 'ok') {
        Write-Host 'FailureForge is already running at http://127.0.0.1:8000/#/projects'
    } else {
        Write-Host 'Open http://127.0.0.1:8000/#/projects and choose Discover scenarios in a saved project.'
        & $pythonPath -m failureforge serve
    }
} finally {
    Pop-Location
}
