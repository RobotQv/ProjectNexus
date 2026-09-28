param([string]$Python = '')
$ErrorActionPreference = 'Stop'
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
if (-not $Python) { $Python = Join-Path $repoRoot '.venv/Scripts/python.exe' }
$Python = (Get-Command $Python -ErrorAction Stop).Source
$runDir = Join-Path $PSScriptRoot ('runs/' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$logPath = Join-Path $runDir 'acceptance.txt'
$failures = [Collections.Generic.List[string]]::new()
$savedEnv = @{}
$isolated = @{
    PYTHONIOENCODING = 'utf-8'
    NEXUS_ENVIRONMENT = 'test'
    NEXUS_DATABASE_URL = 'sqlite:///' + (Join-Path $runDir 'migration.db').Replace('\','/')
    NEXUS_STORAGE_DIR = (Join-Path $runDir 'files')
    NEXUS_JWT_SECRET = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
    NEXUS_MODULE_MODE = 'disabled'
    NEXUS_MODULE_FACTORY = ' '
    NEXUS_LLM_MODE = 'disabled'
    NEXUS_LLM_API_KEY = 'offline-placeholder-not-a-real-key'
    NEXUS_RUN_LIVE_TESTS = '0'
}
function Invoke-Check([string]$Name, [string[]]$Arguments) {
    Write-Host "Checking: $Name"
    Add-Content -LiteralPath $logPath -Value "`n## $Name" -Encoding utf8
    $result = & $Python @Arguments 2>&1
    $code = $LASTEXITCODE
    $result | Out-File -LiteralPath $logPath -Append -Encoding utf8
    Add-Content -LiteralPath $logPath -Value "exit_code=$code" -Encoding utf8
    if ($code -ne 0) { $failures.Add($Name); Write-Host "FAIL ($code): $Name" }
    else { Write-Host "PASS: $Name" }
}
Push-Location $repoRoot
try {
    foreach ($key in $isolated.Keys) {
        $savedEnv[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, $isolated[$key], 'Process')
    }
    "ProjectNexus offline acceptance $(Get-Date -Format o)" | Out-File -LiteralPath $logPath -Encoding utf8
    Invoke-Check 'pytest (all offline suites)' @('-m','pytest','--tb=short')
    Invoke-Check 'ruff check' @('-m','ruff','check','app','shared','team_modules','tests','migrations','examples')
    Invoke-Check 'ruff format check' @('-m','ruff','format','--check','app','shared','team_modules','tests','migrations','examples')
    Invoke-Check 'fresh database migrations' @('-m','alembic','upgrade','head')
    if (-not $failures.Contains('fresh database migrations')) {
        Invoke-Check 'schema drift' @('-m','alembic','check')
    }
    Add-Content -LiteralPath $logPath -Value ("Failed checks: " + ($failures -join ', ')) -Encoding utf8
    Write-Host "Log: $logPath"
} finally {
    foreach ($key in $savedEnv.Keys) { [Environment]::SetEnvironmentVariable($key, $savedEnv[$key], 'Process') }
    Pop-Location
}
if ($failures.Count -gt 0) { exit 1 }
exit 0
