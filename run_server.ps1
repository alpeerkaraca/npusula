# EnPusula FastAPI Sunucu Başlatıcı
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "EnPusula Backend Sunucusu Başlatılıyor..." -ForegroundColor Green
Write-Host "Adres: http://127.0.0.1:8000" -ForegroundColor Yellow
Write-Host "Swagger UI: http://127.0.0.1:8000/docs" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan

uv run uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
