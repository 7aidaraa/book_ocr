@echo off
chcp 65001 >nul
title Arabic Book OCR — Tesseract vs Surya
cd /d "%~dp0"

rem One-click experiment: install Surya (once) and compare it against the
rem current default engine on a few pages. Drag a PDF onto this file, or
rem run it with no arguments to use C:\book.pdf.

set "BOOK=%~1"
if "%BOOK%"=="" set "BOOK=C:\book.pdf"

if not exist "%BOOK%" (
  echo.
  echo [!] PDF not found: %BOOK%
  echo     الملف غير موجود. اسحب ملف PDF وأفلته على هذا الملف.
  pause
  exit /b 1
)

if not exist .venv\INSTALLED_OK (
  echo [!] Run start.bat once first. / شغّل start.bat أولًا للتثبيت.
  pause
  exit /b 1
)

.venv\Scripts\python -c "import surya" 2>nul
if errorlevel 1 (
  echo.
  echo [1/2] Installing Surya ^(~2 GB, one time, several minutes^)...
  echo       تثبيت Surya - مرة واحدة فقط، عدة دقائق. اترك النافذة مفتوحة.
  echo.
  .venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cpu || goto :fail
  .venv\Scripts\python -m pip install surya-ocr || goto :fail
) else (
  echo [i] Surya already installed. / Surya مثبّت مسبقًا.
)

echo.
echo [2/2] Comparing pages 14, 50, 150, 300... / المقارنة جارية...
echo       First run downloads Surya models ^(~1 GB^). / أول تشغيل ينزّل النماذج.
echo.
.venv\Scripts\python scripts\compare_surya.py "%BOOK%" 14 50 150 300 || goto :fail

start "" explorer "data\work\compare-surya"
echo.
echo [OK] Done. Send the .md files in the opened folder to Claude.
echo      اكتمل. أرسل ملفات .md من المجلد المفتوح إلى كلود.
pause
exit /b 0

:fail
echo.
echo [X] Failed. Copy the error text above and send it to Claude.
echo     فشل - انسخ نص الخطأ أعلاه وأرسله.
pause
exit /b 1
