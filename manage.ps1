param (
    [ValidateSet("up", "down", "reset", "logs", "status")]
    [string]$Action = "up"
)

$ErrorActionPreference = "Stop"

function Test-Prerequisites {
    if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
        Write-Error "Docker is not installed or not on PATH."
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker daemon is not running. Please start Docker Desktop."
    }
}

Test-Prerequisites

switch ($Action) {
    "up" {
        if (-not (Test-Path "./docker-compose.yml")) {
            Write-Host "[1/3] Running bootstrap.py to generate project files..." -ForegroundColor Cyan
            python bootstrap.py
        }
        Write-Host "[2/3] Building and starting Docker containers..." -ForegroundColor Cyan
        docker compose up --build -d

        Write-Host "[3/3] Waiting for GridPulse Control Plane on port 8000..." -ForegroundColor Cyan
        $retries = 20
        while ($retries -gt 0) {
            try {
                $resp = Invoke-WebRequest -Uri "http://localhost:8000/api/status" -UseBasicParsing -TimeoutSec 2
                if ($resp.StatusCode -eq 200) { break }
            } catch {
                Start-Sleep -Seconds 2
                $retries--
            }
        }

        Write-Host "`n==========================================================" -ForegroundColor Green
        Write-Host " GridPulse Prototype is LIVE!" -ForegroundColor Green
        Write-Host " -> Control Website : http://localhost:8000" -ForegroundColor Yellow
        Write-Host " -> Grafana UI      : http://localhost:3000 (admin / admin)"
        Write-Host " -> RabbitMQ Broker : http://localhost:15672 (grid_broker / broker_password)"
        Write-Host "==========================================================`n" -ForegroundColor Green
        Start-Process "http://localhost:8000"
    }
    "down" {
        Write-Host "Stopping GridPulse containers..." -ForegroundColor Yellow
        docker compose down
    }
    "reset" {
        Write-Host "Wiping database volumes, regenerating files, and rebuilding..." -ForegroundColor Magenta
        docker compose down -v
        python bootstrap.py
        docker compose up --build -d
    }
    "logs" {
        docker compose logs -f web_and_sim
    }
    "status" {
        docker compose ps
    }
}
