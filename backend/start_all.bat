@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   Запуск Shorts App
echo ============================================
echo.

if not exist "venv\Scripts\activate.bat" (
    echo ОШИБКА: виртуальное окружение не найдено.
    echo Сначала выполни один раз: python -m venv venv
    echo Потом: venv\Scripts\activate  и  pip install -r requirements.txt
    pause
    exit /b 1
)

echo [1/4] Проверяю Redis...
docker inspect shorts_redis >nul 2>&1
if errorlevel 1 (
    echo       Контейнер не найден, создаю новый...
    docker run -d --name shorts_redis -p 6379:6379 redis:7 >nul
) else (
    docker start shorts_redis >nul 2>&1
)
echo       Redis готов.

echo [2/4] Запускаю Celery worker в отдельном окне...
start "Celery Worker" cmd /k "call venv\Scripts\activate.bat && celery -A app.celery_app worker --loglevel=info --pool=solo"

echo [3/4] Запускаю Celery Beat в отдельном окне...
start "Celery Beat" cmd /k "call venv\Scripts\activate.bat && celery -A app.celery_app beat --loglevel=info"

echo [4/4] Запускаю сервер FastAPI в отдельном окне...
start "FastAPI Server" cmd /k "call venv\Scripts\activate.bat && uvicorn app.main:app --reload --port 8000"

echo.
echo Жду 6 секунд, пока сервер поднимется, и открываю браузер...
timeout /t 6 >nul
start http://localhost:8000/docs

echo.
echo ============================================
echo   Готово! Открылось 3 окна с процессами + браузер.
echo   НЕ ЗАКРЫВАЙ эти окна, пока пользуешься приложением.
echo   Чтобы остановить всё - запусти stop_all.bat
echo ============================================
pause
