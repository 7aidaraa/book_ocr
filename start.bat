@echo off
chcp 65001 >nul
title Arabic Book OCR
cd /d "%~dp0"

rem PaddleOCR needs Python 3.9-3.13 (not the newest release). Prefer 3.12
rem via the py launcher; fall back to whatever "python" resolves to.
set "PY=py -3.12"
%PY% --version >nul 2>nul
if errorlevel 1 (
  set "PY=python"
  where python >nul 2>nul
  if errorlevel 1 (
    echo.
    echo [!] Python 3.12 not found. / بايثون 3.12 غير موجود.
    echo     Run this once, then re-run this file:
    echo     شغّل هذا الأمر مرة واحدة ثم أعد تشغيل هذا الملف:
    echo         py install 3.12
    pause
    exit /b 1
  )
)

rem A previous run may have created .venv with an incompatible Python
rem (e.g. 3.14) before failing install — a missing marker means retry clean.
if exist .venv (
  if not exist .venv\INSTALLED_OK (
    echo [i] Removing incomplete previous install... / إزالة تثبيت سابق غير مكتمل...
    rmdir /s /q .venv
  )
)

if not exist .venv (
  echo.
  echo [1/2] First run: installing libraries ^(~1 GB, several minutes^)...
  echo       أول تشغيل: تثبيت المكتبات - قد يستغرق عدة دقائق، انتظر...
  %PY% -m venv .venv || goto :fail
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || goto :fail
  type nul > .venv\INSTALLED_OK
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
