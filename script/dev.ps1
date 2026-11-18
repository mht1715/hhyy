<#
.SYNOPSIS
    HHAgent 一键开发脚本（M0-08）。

.DESCRIPTION
    把「起依赖 / 建表 / 灌数据 / 跑测试 / 跑 lint / 查观测」收敛成一条命令，
    避免每次翻笔记拼命令。

.EXAMPLE
    .\script\dev.ps1 up
    .\script\dev.ps1 init
    .\script\dev.ps1 seed
    .\script\dev.ps1 check
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet(
        'help', 'up', 'down', 'status', 'logs',
        'init', 'seed', 'kb', 'agents', 'test', 'lint', 'check', 'langfuse',
        'backend', 'frontend'
    )]
    [string]$Command = 'help'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root '.venv\Scripts\python.exe'

# 让所有脚本都能 import app.*（等价于在 backend/ 目录下执行）
$env:PYTHONPATH = Join-Path $Root 'backend'

# 只起「依赖」服务，backend 容器不在本地开发时使用（本地 uvicorn 才能读到根目录 .env）
$CoreServices = @('db', 'redis', 'etcd', 'minio', 'standalone')

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Show-Help {
    @"
HHAgent 开发脚本

  up        启动依赖：PostgreSQL / Redis / Milvus（不含 backend 容器）
  down      停止并移除容器（保留数据卷）
  status    查看容器状态
  logs      跟踪依赖日志
  init      建表 / 升级数据库（Alembic）
  seed      灌入演示账号与药品数据
  kb        灌入知识库种子数据（4 库 12 文档，会真实调用 embedding）
  agents    灌入 Agent 与 Prompt 模板（4 个 Agent，纯 DB 写入，很快）
  backend   本地起后端（uvicorn --reload，读取根目录 .env）
  frontend  本地起前端（vite）
  test      单元测试（不连外部服务）
  lint      ruff 检查
  check     lint + test + 前端构建（提交前跑这个）
  langfuse  Langfuse 连通性自检

示例：
  .\script\dev.ps1 up
  .\script\dev.ps1 init; .\script\dev.ps1 seed; .\script\dev.ps1 kb; .\script\dev.ps1 agents
  .\script\dev.ps1 check
"@ | Write-Host
}

switch ($Command) {
    'help' { Show-Help }

    'up' {
        Write-Step '启动依赖服务'
        docker compose up -d $CoreServices
        Write-Host "Milvus 首次启动约需 90 秒，稍后用 '.\script\dev.ps1 status' 确认 healthy"
    }

    'down' {
        Write-Step '停止服务'
        docker compose down
    }

    'status' {
        docker compose ps
    }

    'logs' {
        docker compose logs -f --tail 100
    }

    'init' {
        Write-Step '初始化数据库（Alembic）'
        & $Py (Join-Path $Root 'script\init_db.py')
    }

    'seed' {
        Write-Step '灌入种子数据'
        & $Py (Join-Path $Root 'script\seed_users.py')
        & $Py (Join-Path $Root 'script\seed_products.py')
    }

    'kb' {
        Write-Step '灌入知识库种子数据（4 库 12 文档，会真实调用 embedding，约 1-2 分钟）'
        & $Py (Join-Path $Root 'script\seed_kb.py')
    }

    'agents' {
        Write-Step '灌入 Agent 与 Prompt 模板（4 个 Agent）'
        & $Py (Join-Path $Root 'script\seed_agents.py')
    }

    'test' {
        Write-Step '运行单元测试'
        & $Py -m pytest -q
    }

    'lint' {
        Write-Step 'ruff 检查'
        & $Py -m ruff check (Join-Path $Root 'backend') (Join-Path $Root 'script')
    }

    'check' {
        Write-Step 'ruff 检查'
        & $Py -m ruff check (Join-Path $Root 'backend') (Join-Path $Root 'script')

        Write-Step '单元测试'
        & $Py -m pytest -q

        Write-Step '前端构建'
        Push-Location (Join-Path $Root 'frontend')
        try { npm run build } finally { Pop-Location }
    }

    'langfuse' {
        & $Py (Join-Path $Root 'script\check_langfuse.py')
    }

    'backend' {
        Write-Step '启动后端 http://127.0.0.1:8000 （文档 /docs）'
        Push-Location (Join-Path $Root 'backend')
        try { & $Py -m uvicorn app.main:app --reload --port 8000 } finally { Pop-Location }
    }

    'frontend' {
        Write-Step '启动前端 http://127.0.0.1:5173'
        Push-Location (Join-Path $Root 'frontend')
        try { npm run dev } finally { Pop-Location }
    }
}
