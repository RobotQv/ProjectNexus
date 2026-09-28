$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$record = Get-Content -LiteralPath (Join-Path $projectRoot 'data/alpha-demo/processes.json') -Raw | ConvertFrom-Json
foreach ($owned in $record.processes) {
 $process = Get-Process -Id $owned.pid -ErrorAction Stop
 if ($process.StartTime.ToUniversalTime().Ticks -ne ([datetime]$owned.started).ToUniversalTime().Ticks -or $process.Path -ne $owned.executable) { throw '进程记录不匹配。' }
 Write-Output "$($owned.role): running"
}
$url = "http://127.0.0.1:$($record.port)"
$health = Invoke-RestMethod "$url/health/ready"
if ($health.status -ne 'ready') { throw 'API 未就绪。' }
$page = Invoke-WebRequest $url
if ($page.StatusCode -ne 200) { throw '前端入口不可用。' }
Write-Output "API/schema: ready; frontend: 200; entry: $url"
Write-Output '进程存在不等于真实模型可用；还需登录后上传资料、提问并检查队列结果。公网与手机应在对应设备另测。'
