$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$manifestPath = Join-Path $projectRoot 'data/alpha-demo/processes.json'
if (-not (Test-Path -LiteralPath $manifestPath)) { Write-Output '没有本脚本启动的演示进程。'; exit 0 }
$record = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($record.root -ne $projectRoot) { throw '进程记录所属目录不一致，未停止任何进程。' }
foreach ($owned in $record.processes) {
 $process = Get-Process -Id $owned.pid -ErrorAction SilentlyContinue
 if (-not $process) { continue }
 if ($process.StartTime.ToUniversalTime().Ticks -ne ([datetime]$owned.started).ToUniversalTime().Ticks -or $process.Path -ne $owned.executable) {
  throw "PID $($owned.pid) 已复用或进程不匹配，拒绝结束。"
 }
 # Windows venv launcher 会启动实际 Python 子进程；只结束已核对根进程的子树。
 $process.Kill($true)
 $process.WaitForExit(5000) | Out-Null
}
Remove-Item -LiteralPath $manifestPath
Write-Output '已停止本脚本启动的 API 与 Worker；数据库、文件和日志全部保留。'
