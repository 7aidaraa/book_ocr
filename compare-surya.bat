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

if not exist .venv-surya\Scripts\python.exe (
  echo.
  echo [1/2] Creating a separate Surya environment ^(~2.5 GB, one time^)...
  echo       بيئة منفصلة لـSurya - لا تمسّ .venv. عدة دقائق، اترك النافذة مفتوحة.
  echo.
  python -m venv .venv-surya || goto :fail
  .venv-surya\Scripts\python -m pip install -q --upgrade pip
  rem Pinned on purpose: surya-ocr >=0.20 needs an external llama-server
  rem binary that pip does not install, so an unpinned install ends in
  rem "llama-server binary not found". 0.17.1 is the last pure-PyTorch release.
  .venv-surya\Scripts\python -m pip install -r requirements-surya.txt || goto :fail
) else (
  echo [i] Surya environment already present. / بيئة Surya موجودة مسبقًا.
)

echo.
echo [2/2] Comparing pages 14, 50, 150, 300... / المقارنة جارية...
echo       First run downloads Surya models ^(~1 GB^) from models.datalab.to
echo       أول تشغيل ينزّل النماذج.
echo.
.venv-surya\Scripts\python scripts\compare_surya.py "%BOOK%" 14 50 150 300 || goto :fail

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
