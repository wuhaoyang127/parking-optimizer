# 停车系统公网部署 · 第1步：创建 cloudflared 隧道并绑定两个固定子域名
# 前置：1) 域名 wuhaoyang127.top 已在 Cloudflare 显示 Active（审核通过 + NS 已改）
#       2) 本机已安装 cloudflared（已装，版本 2026.10.7）
# 用法：powershell -ExecutionPolicy Bypass -File .\setup-tunnel.ps1
param(
    [string]$TunnelName  = 'parking',
    [string]$DriverHost  = 'driver.wuhaoyang127.top',
    [string]$ConsoleHost = 'console.wuhaoyang127.top'
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$cf = (Get-Command cloudflared -ErrorAction Stop).Source
Write-Host "[1/5] 登录 Cloudflare（会弹浏览器，请点授权）"
& $cf tunnel login
if ($LASTEXITCODE -ne 0) { throw 'tunnel login 失败' }

Write-Host "[2/5] 创建隧道：$TunnelName"
& $cf tunnel create $TunnelName
if ($LASTEXITCODE -ne 0) { throw 'tunnel create 失败' }

Write-Host "[3/5] 生成 config.yml（两个入口）"
$list = & $cf tunnel list --output json | ConvertFrom-Json
$tunnelId = ($list | Where-Object { $_.name -eq $TunnelName }).id
if (-not $tunnelId) { throw '未找到隧道 ID' }
$cfDir = Join-Path $env:USERPROFILE '.cloudflared'
$configPath = Join-Path $cfDir 'config.yml'
@"
tunnel: $tunnelId
credentials-file: $(Join-Path $cfDir "$tunnelId.json")
ingress:
  - hostname: $DriverHost
    service: http://127.0.0.1:8000
  - hostname: $ConsoleHost
    service: http://127.0.0.1:8501
  - service: http_status:404
"@ | Set-Content -LiteralPath $configPath -Encoding UTF8
Write-Host "   已写入 $configPath"

Write-Host "[4/5] 绑定 DNS：$DriverHost"
& $cf tunnel route dns $TunnelName $DriverHost
if ($LASTEXITCODE -ne 0) { throw 'route dns 失败（确认域名已在 Cloudflare Active）' }

Write-Host "[5/5] 绑定 DNS：$ConsoleHost"
& $cf tunnel route dns $TunnelName $ConsoleHost
if ($LASTEXITCODE -ne 0) { throw 'route dns 失败（确认域名已在 Cloudflare Active）' }

Write-Host ''
Write-Host "完成。隧道名=$TunnelName"
Write-Host "  车主端: https://$DriverHost  -> 本机 8000"
Write-Host "  控制台: https://$ConsoleHost -> 本机 8501"
Write-Host '下一步：powershell -ExecutionPolicy Bypass -File .\start-public.ps1'
