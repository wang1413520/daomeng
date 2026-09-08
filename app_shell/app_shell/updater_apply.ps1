# 到梦空间工作台 · 更新应用脚本
# 等待旧进程退出 -> 用新版目录覆盖应用目录（保留 config/token/state 等用户数据）-> 重新启动
param(
  [string]$AppDir,
  [string]$NewDir,
  [string]$ZipPath,
  [string]$ExePath,
  [int]$Pid
)
$ErrorActionPreference = 'Continue'
Start-Sleep -Seconds 2
if ($Pid -gt 0) { Wait-Process -Id $Pid -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
# 覆盖应用目录（/E 全量拷贝、排除 .update，不删除用户数据文件）
robocopy $NewDir $AppDir /E /XD ".update" /NFL /NDL /NJH /NJS /R:2 /W:2 | Out-Null
# 清理更新缓存
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue }
if (Test-Path $NewDir) { Remove-Item $NewDir -Recurse -Force -ErrorAction SilentlyContinue }
$pending = Join-Path $AppDir ".update\pending.json"
if (Test-Path $pending) { Remove-Item $pending -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
if (Test-Path $ExePath) { Start-Process -FilePath $ExePath -WorkingDirectory $AppDir }
