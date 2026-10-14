$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$config = Join-Path $project '.env.features-development'
if (-not (Test-Path -LiteralPath $config)) {
    throw 'Siapkan .env.features-development dengan database dan penyimpanan foto terpisah dari demo.'
}
$env:ELRISE_ENV_FILE = $config
$env:FLASK_SKIP_DOTENV = '1'
$env:PORT = '5003'
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-Location -LiteralPath $project
& (Join-Path $project '.venv\Scripts\python.exe') -B (Join-Path $project 'app.py')
