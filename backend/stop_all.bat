@echo off
chcp 65001 >nul
echo Останавливаю Redis...
docker stop shorts_redis >nul 2>&1
echo Redis остановлен.
echo.
echo Теперь закрой вручную 3 открытых окна:
echo   - Celery Worker
echo   - Celery Beat
echo   - FastAPI Server
echo (просто нажми крестик на каждом окне)
pause
