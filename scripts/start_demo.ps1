param([int]$Port = 8000, [string]$ListenAddress = '127.0.0.1', [string]$Model = '', [switch]$Initialize, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtimeDir = Join-Path $projectRoot 'data/alpha-demo'
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
$manifestPath = Join-Path $runtimeDir 'processes.json'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '先按 README 安装 .venv 和项目依赖。' }
if (Test-Path -LiteralPath $manifestPath) { throw '已有演示进程记录，请先运行 stop_demo.ps1。' }
$probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($ListenAddress), $Port)
try { $probe.Start() } finally { $probe.Stop() }
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$variables = @{
 NEXUS_DATABASE_URL = 'sqlite:///' + (Join-Path $runtimeDir 'demo.db').Replace('\','/')
 NEXUS_STORAGE_DIR = (Join-Path $runtimeDir 'files')
 NEXUS_WEB_DIST_DIR = (Join-Path $projectRoot 'frontend/web/dist')
 NEXUS_MODULE_FACTORY = 'team_modules.factory:build_modules'
 VITE_API_BASE = '/api/v1'
 VITE_DEFAULT_MODE = 'live'
}
$previous = @{}
if ($Model) { $variables.NEXUS_LLM_MODEL = $Model }
$owned = @()
Push-Location $projectRoot
try {
 foreach ($name in $variables.Keys) {
  $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
  [Environment]::SetEnvironmentVariable($name, $variables[$name], 'Process')
 }
 if (-not $SkipBuild) {
  Push-Location (Join-Path $projectRoot 'frontend/web')
  try { & npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' } } finally { Pop-Location }
 }
 & $pythonPath -m app.cli migrate
 if ($LASTEXITCODE -ne 0) { throw '数据库迁移失败。' }
 if ($Initialize) {
  & $pythonPath -m app.cli seed-demo
  if ($LASTEXITCODE -ne 0) { throw '演示数据初始化失败（仅适用于空库）。' }
 }
 foreach ($role in @('api','worker')) {
  $arguments = if ($role -eq 'api') { @('-m','uvicorn','app.main:create_app','--factory','--host',$ListenAddress,'--port',"$Port") } else { @('-m','app.worker') }
  $process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir "$role.out.log") -RedirectStandardError (Join-Path $runtimeDir "$role.err.log")
  $owned += @{ role=$role; pid=$process.Id; started=$process.StartTime.ToUniversalTime().ToString('o'); executable=$pythonPath }
 }
 @{ port=$Port; address=$ListenAddress; root=$projectRoot; processes=$owned } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
 $ready = $false
 for ($attempt=0; $attempt -lt 30; $attempt++) {
  try { $response = Invoke-RestMethod "http://127.0.0.1:$Port/health/ready"; $ready = $response.status -eq 'ready' } catch { }
  if ($ready) { break }
  Start-Sleep -Milliseconds 500
 }
 if (-not $ready) { throw 'API 未就绪；请查看 data/alpha-demo 日志，随后运行 stop_demo.ps1。' }
 Write-Output "演示入口：http://127.0.0.1:$Port；账号 demo1—demo6，密码为初始化时设置的值。"
 Write-Output '使用独立 data/alpha-demo 数据库；其他设备访问须显式 -ListenAddress 0.0.0.0，并使用本机局域网 IP。'
} finally {
 foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
 Pop-Location
}
