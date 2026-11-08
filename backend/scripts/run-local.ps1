param(
    [string]$Python = 'python',
    [int]$Port = 8000,
    [string]$EnvFile = ''
)

$backendRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$localEnv = Join-Path $backendRoot 'app/.env'
if ($EnvFile) { $localEnv = (Resolve-Path -LiteralPath $EnvFile).Path }
$allowed = @{
    OPENROUTER_API_KEY = $true
    CHAT_PROVIDER = $true
    CHAT_SPEND_CAP_USD = $true
    SUPABASE_URL = $true
    SUPABASE_PUBLISHABLE_KEY = $true
    REDIS_URL = $true
    APP_DB_PATH = $true
    CHAT_RUNTIME = $true
    HERMES_API_URL = $true
    HERMES_API_KEY = $true
    HERMES_TIMEOUT_SECONDS = $true
    PUBLIC_MCP_URL = $true
    PUBLIC_MCP_TOKEN = $true
    MODEL_GATEWAY_URL = $true
    MODEL_GATEWAY_KEY = $true
    DISCOVERY_ENABLED = $true
    DISCOVERY_PUBLIC_ENABLED = $true
    DISCOVERY_SEARCH_PROVIDER = $true
    DISCOVERY_OPENROUTER_KEY = $true
    DISCOVERY_AUTO_VERIFY = $true
    DISCOVERY_MAX_REQUESTS = $true
    DISCOVERY_SPEND_CAP_USD = $true
}

if (Test-Path -LiteralPath $localEnv) {
    foreach ($line in (Get-Content -LiteralPath $localEnv)) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $name = $Matches[1]
            if (-not $allowed.ContainsKey($name)) { continue }
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}

$env:CHAT_PROVIDER = 'openrouter'
if (-not $env:CHAT_SPEND_CAP_USD) { $env:CHAT_SPEND_CAP_USD = '0.10' }
$env:PYTHONDONTWRITEBYTECODE = '1'

Push-Location $backendRoot
try {
    & $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port --no-proxy-headers
} finally {
    Pop-Location
}
