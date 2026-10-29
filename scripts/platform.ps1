param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "logs")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Compose {
    param([string[]]$Arguments)

    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose 执行失败，退出码: $LASTEXITCODE"
    }
}

function Assert-DockerAvailable {
    try {
        & docker version --format "{{.Server.Version}}" *> $null
    }
    catch {
        throw "未检测到可用的 Docker Desktop，请先启动 Docker Desktop。"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop 未运行或当前用户无权访问 Docker。"
    }
}

function Wait-AppHealthy {
    param([int]$TimeoutSeconds = 300)

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $containerId = ((& docker compose ps -q eat-agent) -join "").Trim()
        if ($containerId) {
            $health = ((& docker inspect --format "{{.State.Health.Status}}" $containerId 2>$null) -join "").Trim()
            if ($health -eq "healthy") {
                return
            }
            if ($health -eq "unhealthy") {
                Invoke-Compose @("logs", "--tail", "80", "eat-agent")
                throw "eat-agent 健康检查失败。"
            }
        }
        Start-Sleep -Seconds 5
    } while ((Get-Date) -lt $deadline)

    Invoke-Compose @("ps")
    throw "等待 eat-agent 健康检查超时（${TimeoutSeconds} 秒）。"
}

Push-Location $repoRoot
try {
    Assert-DockerAvailable
    switch ($Action) {
        "start" {
            # up 会复用 Docker 构建缓存，并确保配置或代码变化后重新构建。
            Invoke-Compose @("up", "-d", "--build")
            Wait-AppHealthy
            Invoke-Compose @("ps")
        }
        "stop" {
            # stop 不删除容器卷，数据仍保留在 Docker volume 中。
            Invoke-Compose @("stop")
        }
        "restart" {
            Invoke-Compose @("restart")
            Wait-AppHealthy
            Invoke-Compose @("ps")
        }
        "status" {
            Invoke-Compose @("ps")
        }
        "logs" {
            Invoke-Compose @("logs", "--tail", "200", "-f")
        }
    }
}
finally {
    Pop-Location
}
