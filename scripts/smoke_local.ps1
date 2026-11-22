<#
.SYNOPSIS
    HappyClaw 本机冒烟测试：临时数据目录启动服务并检查 /api/health。

.DESCRIPTION
    步骤：
      1. 找一个空闲端口；
      2. 把 HAPPYCLAW_HOME 指到临时目录（不触碰真实 ~/.octop）；
      3. 启动 `octop run`；
      4. 轮询 http://127.0.0.1:<port>/api/health；
      5. 输出响应、数据目录清单与日志末尾；
      6. 停止进程并清理临时目录（-Keep 可保留）。
    返回码：0 成功；1 启动或健康检查失败；2 找不到可执行的 octop。

.PARAMETER Port
    指定端口；默认自动选择空闲端口。

.PARAMETER TimeoutSeconds
    等待服务就绪的最长秒数，默认 90。

.PARAMETER Keep
    保留临时数据目录与日志，便于排查。

.EXAMPLE
    powershell -File scripts/smoke_local.ps1

.EXAMPLE
    powershell -File scripts/smoke_local.ps1 -Port 8091 -Keep
#>
[CmdletBinding()]
param(
    [int]$Port = 0,
    [int]$TimeoutSeconds = 90,
    [switch]$Keep
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
$RepoRoot = Split-Path -Parent $scriptDir

function Fail([string]$Message, [int]$Code = 1) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    exit $Code
}

function Get-FreePort {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $free = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
    $listener.Stop()
    return $free
}

function Resolve-Octop {
    $cmd = Get-Command octop -ErrorAction SilentlyContinue
    if ($cmd) { return @{ File = $cmd.Source; Args = @() } }

    $venvExe = Join-Path $RepoRoot ".venv\Scripts\octop.exe"
    if (Test-Path $venvExe) { return @{ File = $venvExe; Args = @() } }

    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        & $venvPython -c "import octop" 2>$null | Out-Null
        $importOk = ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = $prevEap
        if ($importOk) { return @{ File = $venvPython; Args = @("-m", "octop") } }
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) {
        foreach ($candidate in @(
            (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
            (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
        )) {
            if (Test-Path $candidate) { $uv = Get-Item $candidate; break }
        }
    }
    if ($uv) { return @{ File = $uv.Source; Args = @("run", "--no-sync", "octop") } }

    return $null
}

if ($Port -le 0) { $Port = Get-FreePort }
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tempHome = Join-Path $env:TEMP "happyclaw-smoke-$stamp"
$stdoutLog = Join-Path $tempHome "smoke.stdout.log"
$stderrLog = Join-Path $tempHome "smoke.stderr.log"
New-Item -ItemType Directory -Path $tempHome -Force | Out-Null

$octop = Resolve-Octop
if (-not $octop) {
    $msg = "找不到可执行的 octop。请先安装依赖：`n  uv sync`n或安装 HappyClaw：`n  powershell -ExecutionPolicy Bypass -File scripts/install.ps1"
    Fail $msg 2
}

Write-Host "HappyClaw smoke test" -ForegroundColor White
Write-Host "  octop     : $($octop.File) $($octop.Args -join ' ')" -ForegroundColor DarkGray
Write-Host "  HAPPYCLAW_HOME: $tempHome" -ForegroundColor DarkGray
Write-Host "  port      : $Port" -ForegroundColor DarkGray

$oldHome = $env:HAPPYCLAW_HOME
$oldHost = $env:HAPPYCLAW_BIND_HOST
$oldPort = $env:HAPPYCLAW_PORT
$env:HAPPYCLAW_HOME = $tempHome
$env:HAPPYCLAW_BIND_HOST = "127.0.0.1"
$env:HAPPYCLAW_PORT = "$Port"

$process = $null
$startedAt = Get-Date
try {
    $argList = @($octop.Args) + @("run", "--host", "127.0.0.1", "--port", "$Port")
    $process = Start-Process -FilePath $octop.File `
        -ArgumentList $argList `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -PassThru -WindowStyle Hidden

    $health = $null
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) { break }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
            break
        }
        catch {
            Start-Sleep -Milliseconds 700
        }
    }

    if (-not $health) {
        Write-Host "[FAIL] 服务在 $TimeoutSeconds 秒内未就绪" -ForegroundColor Red
        if (Test-Path $stderrLog) {
            Write-Host "--- stderr (tail) ---" -ForegroundColor DarkGray
            Get-Content $stderrLog -Tail 30
        }
        if (Test-Path $stdoutLog) {
            Write-Host "--- stdout (tail) ---" -ForegroundColor DarkGray
            Get-Content $stdoutLog -Tail 30
        }
        exit 1
    }

    $elapsed = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
    Write-Host "[PASS] /api/health 响应（首次可用耗时 ${elapsed}s）：" -ForegroundColor Green
    $health | ConvertTo-Json -Depth 5

    Write-Host "[INFO] 临时数据目录内容：" -ForegroundColor Cyan
    Get-ChildItem $tempHome -Force | Select-Object Mode, Length, Name | Format-Table -AutoSize | Out-String | Write-Host

    if (-not $health.ok) {
        Write-Host "[FAIL] /api/health 返回 ok=false" -ForegroundColor Red
        exit 1
    }
    Write-Host "[PASS] 冒烟测试通过" -ForegroundColor Green
}
finally {
    if ($process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $process.WaitForExit(5000) | Out-Null
        Write-Host "[INFO] 已停止测试进程 (PID $($process.Id))" -ForegroundColor DarkGray
    }
    $env:HAPPYCLAW_HOME = $oldHome
    $env:HAPPYCLAW_BIND_HOST = $oldHost
    $env:HAPPYCLAW_PORT = $oldPort

    if ($Keep) {
        Write-Host "[INFO] 保留临时目录：$tempHome" -ForegroundColor Yellow
    }
    else {
        Remove-Item $tempHome -Recurse -Force -ErrorAction SilentlyContinue
    }
}
