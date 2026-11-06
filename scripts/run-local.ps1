param(
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

# Fast offline smoke/demo mode. Production uses docker-compose with MySQL,
# Redis and Ollama; this mode keeps the full Agent runtime available locally.
$env:DATABASE_URL = "sqlite:///./data/mindbridge-local.db"
$env:AI_PROVIDER = "mock"
$env:KNOWLEDGE_VECTOR_ENABLED = "false"
$env:TOOL_QUEUE_ENABLED = "false"

python -m uvicorn app.main:app --host 127.0.0.1 --port $Port
