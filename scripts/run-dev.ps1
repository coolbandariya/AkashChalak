$ErrorActionPreference = "Stop"

Write-Host "Starting AkashChalak backend at http://localhost:8000"
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\..\backend'; python -m uvicorn app.main:app --reload --port 8000"

Write-Host "Starting AkashChalak frontend at http://localhost:5173"
Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoExit", "-Command", "cd '$PSScriptRoot\..\frontend'; python -m http.server 5173"

Write-Host "Open http://localhost:5173"
