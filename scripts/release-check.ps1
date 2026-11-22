<#
.SYNOPSIS
    HappyClaw 发布前自动检查（单人本地版）。

.DESCRIPTION
    覆盖 docs/RELEASE-CHECKLIST.md 中可自动化的项目：
      - 版本号一致性（pyproject / README / README_CN）
      - 发布必需文件与文档是否存在
      - README 与快速开始是否残留多用户 / 登录 / 邀请文案
      - 默认端口占用情况
      - 数据目录是否可写（存在时）
      - PowerShell 脚本语法
      - Docker Compose 配置是否可解析（本机有 docker 时）
      - 文档与脚本中的明文密钥扫描
    失败项返回退出码 1；警告项不阻断发布。

.PARAMETER RepoRoot
    仓库根目录，默认取脚本上一级目录。

.PARAMETER Port
    检查是否被占用的默认端口，默认 8088。

.PARAMETER SkipSecretScan
    跳过明文密钥扫描（仅用于离线排查）。

.EXAMPLE
    powershell -File scripts/release-check.ps1

.EXAMPLE
    powershell -File scripts/release-check.ps1 -Port 8090
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [int]$Port = 8088,
    [switch]$SkipSecretScan
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (-not $scriptDir) { $scriptDir = (Get-Location).Path }
    $RepoRoot = Split-Path -Parent $scriptDir
}
$script:Failures = @()
$script:Warnings = @()
$script:Passed = @()

function Add-Pass([string]$Message) { $script:Passed += $Message; Write-Host "[PASS] $Message" -ForegroundColor Green }
function Add-Warn([string]$Message) { $script:Warnings += $Message; Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Add-Fail([string]$Message) { $script:Failures += $Message; Write-Host "[FAIL] $Message" -ForegroundColor Red }
function Add-Info([string]$Message) { Write-Host "[INFO] $Message" -ForegroundColor Cyan }

Write-Host "HappyClaw release check" -ForegroundColor White
Write-Host "Repo: $RepoRoot" -ForegroundColor DarkGray
Write-Host ("-" * 64) -ForegroundColor DarkGray

if (-not (Test-Path (Join-Path $RepoRoot "pyproject.toml"))) {
    Add-Fail "未找到 pyproject.toml，RepoRoot 可能不是 HappyClaw 仓库根目录：$RepoRoot"
    exit 1
}

# ---------------------------------------------------------------------------
# 1. 版本号一致性
# ---------------------------------------------------------------------------
try {
    $pyproject = Get-Content (Join-Path $RepoRoot "pyproject.toml") -Raw
    $versionMatch = [regex]::Match($pyproject, '(?m)^version\s*=\s*"([^"]+)"')
    if (-not $versionMatch.Success) {
        Add-Fail "pyproject.toml 中没有找到 version 字段"
        $version = $null
    }
    else {
        $version = $versionMatch.Groups[1].Value
        Add-Pass "pyproject.toml 版本：$version"
    }

    if ($version) {
        foreach ($readme in @("README.md", "README_CN.md")) {
            $path = Join-Path $RepoRoot $readme
            if (-not (Test-Path $path)) { continue }
            $text = Get-Content $path -Raw
            $badge = [regex]::Match($text, 'version-([0-9][^-\s"]*)-orange')
            if ($badge.Success) {
                if ($badge.Groups[1].Value -eq $version) {
                    Add-Pass "$readme 徽章版本与 pyproject 一致"
                }
                else {
                    Add-Fail "$readme 徽章版本 $($badge.Groups[1].Value) 与 pyproject $version 不一致"
                }
            }
            else {
                Add-Warn "$readme 中未找到版本徽章"
            }
        }

        $changelogPath = Join-Path $RepoRoot "CHANGELOG.md"
        if (Test-Path $changelogPath) {
            $changelog = Get-Content $changelogPath -Raw
            if ($changelog -match [regex]::Escape($version)) {
                Add-Pass "CHANGELOG.md 包含当前版本 $version"
            }
            else {
                Add-Fail "CHANGELOG.md 未包含当前版本 $version"
            }
        }
        else {
            Add-Fail "缺少 CHANGELOG.md"
        }
    }
}
catch {
    Add-Fail "读取版本信息失败：$($_.Exception.Message)"
}

# ---------------------------------------------------------------------------
# 2. 必需文件
# ---------------------------------------------------------------------------
$required = @(
    "README.md",
    "README_CN.md",
    "CHANGELOG.md",
    "LICENSE",
    "pyproject.toml",
    "uv.lock",
    "src/happyclaw/__init__.py",
    "docker/docker-compose.yml",
    "scripts/install.ps1",
    "scripts/install.sh",
    "docs/quickstart.md",
    "docs/user-guide.md",
    "docs/configuration.md",
    "docs/RELEASE-CHECKLIST.md"
)
$missing = @()
foreach ($rel in $required) {
    if (-not (Test-Path (Join-Path $RepoRoot $rel))) { $missing += $rel }
}
if ($missing.Count -eq 0) {
    Add-Pass "必需文件齐全（$($required.Count) 项）"
}
else {
    Add-Fail "缺少必需文件：$($missing -join ', ')"
}

# ---------------------------------------------------------------------------
# 3. 单人文案残留
# ---------------------------------------------------------------------------
$scanFiles = @(
    "README.md", "README_CN.md",
    "docs/quickstart.md", "docs/user-guide.md"
)
$forbidden = @(
    "支持多用户", "多租户部署", "邀请成员", "注册账号", "管理员账号",
    "登录后可见", "JWT 用户隔离", "面向团队"
)
$hits = @()
foreach ($rel in $scanFiles) {
    $path = Join-Path $RepoRoot $rel
    if (-not (Test-Path $path)) { continue }
    $lines = Get-Content $path
    for ($i = 0; $i -lt $lines.Count; $i++) {
        foreach ($term in $forbidden) {
            if ($lines[$i].Contains($term)) {
                $hits += "${rel}:$($i + 1) 含「$term」"
            }
        }
    }
}
if ($hits.Count -eq 0) {
    Add-Pass "README 与快速开始未发现多用户 / 登录 / 邀请文案"
}
else {
    Add-Fail ("单人文案残留：`n  " + ($hits -join "`n  "))
}

# ---------------------------------------------------------------------------
# 4. 端口占用
# ---------------------------------------------------------------------------
try {
    $client = New-Object System.Net.Sockets.TcpClient
    $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
    $connected = $async.AsyncWaitHandle.WaitOne(800)
    if ($connected -and $client.Connected) {
        Add-Warn "端口 $Port 已被占用；若是正在运行的 HappyClaw 可忽略，否则换端口"
    }
    else {
        Add-Pass "端口 $Port 可用"
    }
    $client.Close()
}
catch {
    Add-Warn "无法检测端口 $Port：$($_.Exception.Message)"
}

# ---------------------------------------------------------------------------
# 5. 数据目录可写
# ---------------------------------------------------------------------------
$octopHome = $env:OCTOP_HOME
if (-not $octopHome) { $octopHome = Join-Path $HOME ".octop" }
if (Test-Path $octopHome) {
    try {
        $probe = Join-Path $octopHome ".release-check-probe"
        Set-Content -Path $probe -Value "ok" -Encoding UTF8
        Remove-Item $probe -Force
        Add-Pass "数据目录可写：$octopHome"
    }
    catch {
        Add-Fail "数据目录不可写：$octopHome（$($_.Exception.Message)）"
    }
}
else {
    Add-Info "数据目录尚不存在：$octopHome（首次启动自动创建）"
}

# ---------------------------------------------------------------------------
# 6. PowerShell 脚本语法
# ---------------------------------------------------------------------------
$psScripts = Get-ChildItem (Join-Path $RepoRoot "scripts") -Filter "*.ps1" -ErrorAction SilentlyContinue
$syntaxErrors = @()
foreach ($ps1 in $psScripts) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($ps1.FullName, [ref]$tokens, [ref]$errors) | Out-Null
    foreach ($err in $errors) {
        $syntaxErrors += "$($ps1.Name):$($err.Extent.StartLineNumber) $($err.Message)"
    }
}
if ($syntaxErrors.Count -eq 0) {
    Add-Pass "PowerShell 脚本语法正常（$($psScripts.Count) 个）"
}
else {
    Add-Fail ("PowerShell 语法错误：`n  " + ($syntaxErrors -join "`n  "))
}

# ---------------------------------------------------------------------------
# 7. Docker Compose
# ---------------------------------------------------------------------------
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    $composeFile = Join-Path $RepoRoot "docker/docker-compose.yml"
    $output = & docker compose -f $composeFile config -q 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-Pass "docker-compose.yml 配置可解析"
    }
    else {
        Add-Fail "docker-compose.yml 解析失败：$output"
    }
}
else {
    Add-Info "未安装 docker，跳过 Compose 校验"
}

# ---------------------------------------------------------------------------
# 8. 明文密钥扫描
# ---------------------------------------------------------------------------
if (-not $SkipSecretScan) {
    $secretDirs = @("docs", "scripts", "docker")
    $secretFiles = @("README.md", "README_CN.md")
    $patterns = @(
        'sk-[A-Za-z0-9]{20,}',
        'AKID[A-Za-z0-9]{16,}',
        'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY',
        'Bearer\s+[A-Za-z0-9._-]{20,}'
    )
    $secretHits = @()
    $targets = @()
    foreach ($dir in $secretDirs) {
        $full = Join-Path $RepoRoot $dir
        if (Test-Path $full) {
            $targets += Get-ChildItem $full -Recurse -File -Include *.md, *.ps1, *.sh, *.yml, *.yaml, *.json, *.html -ErrorAction SilentlyContinue
        }
    }
    foreach ($file in $secretFiles) {
        $full = Join-Path $RepoRoot $file
        if (Test-Path $full) { $targets += Get-Item $full }
    }
    foreach ($file in $targets) {
        $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
        if (-not $content) { continue }
        # HTML 内的 base64 图片会误命中密钥正则，先剔除 data URI
        $content = $content -replace 'data:[^"]+', ''
        foreach ($pattern in $patterns) {
            if ($content -match $pattern) {
                $secretHits += $file.FullName.Substring($RepoRoot.Length + 1)
                break
            }
        }
    }
    if ($secretHits.Count -eq 0) {
        Add-Pass "文档 / 脚本 / docker 未发现明文密钥"
    }
    else {
        Add-Fail ("疑似明文密钥：" + (($secretHits | Sort-Object -Unique) -join ', '))
    }
}
else {
    Add-Info "已跳过明文密钥扫描"
}

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
Write-Host ("-" * 64) -ForegroundColor DarkGray
Write-Host "通过 $($script:Passed.Count) 项，警告 $($script:Warnings.Count) 项，失败 $($script:Failures.Count) 项" -ForegroundColor White
if ($script:Failures.Count -gt 0) {
    Write-Host "发布检查未通过，请先处理 FAIL 项。" -ForegroundColor Red
    exit 1
}
Write-Host "自动检查通过。请继续核对 docs/RELEASE-CHECKLIST.md 中的人工项。" -ForegroundColor Green
exit 0
