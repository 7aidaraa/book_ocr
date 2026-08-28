@echo off
chcp 65001 >nul
title Arabic Book OCR
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [!] Python is not installed. / بايثون غير مثبت على الجهاز.
  echo     Opening download page... During install CHECK "Add python.exe to PATH".
  echo     ستفتح صفحة التنزيل الآن - عند التثبيت فعّل خيار "Add python.exe to PATH".
  start https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist .venv (
  echo.
  echo [1/2] First run: installing libraries ^(~1 GB, several minutes^)...
  echo       أول تشغيل: تثبيت المكتبات - قد يستغرق عدة دقائق، انتظر...
  python -m venv .venv || goto :fail
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || goto :fail
)

echo.
echo [2/2] Starting server... / تشغيل الخادم...
echo       Keep this window OPEN. / اترك هذه النافذة مفتوحة.
echo.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
.venv\Scripts\python run.py
pause
exit /b 0

:fail
echo.
echo [X] Installation failed. Copy the error text above and send it to Claude.
echo     فشل التثبيت - انسخ نص الخطأ أعلاه وأرسله.
pause
exit /b 1
