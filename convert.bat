@echo off
chcp 65001 >nul
title Arabic Book OCR — convert
cd /d "%~dp0"

rem Daily use: drag one or more PDF files onto this .bat. Each book is
rem converted with Tesseract (resumable), then its output folder opens.

if "%~1"=="" (
  echo.
  echo Drag PDF files onto this file to convert them.
  echo اسحب ملف PDF ^(أو عدة ملفات^) وأفلتها على هذا الملف لتحويلها.
  pause
  exit /b 1
)

if not exist .venv\INSTALLED_OK (
  echo [!] Run start.bat once first to install. / شغّل start.bat أولًا للتثبيت.
  pause
  exit /b 1
)

where tesseract >nul 2>nul
if errorlevel 1 (
  echo [!] Tesseract not found on PATH. / Tesseract غير موجود. See دليل-التشغيل.md
  pause
  exit /b 1
)

set FAILED=0
:next
if "%~1"=="" goto :done
echo.
echo ================================================================
echo  %~nx1
echo ================================================================
.venv\Scripts\python -m app.cli "%~1" --engine tesseract
if errorlevel 1 set FAILED=1
start "" explorer "data\output\%~n1"
shift
goto :next

:done
echo.
if "%FAILED%"=="1" (
  echo [!] Some pages failed - see مراجعة.md in each output folder.
  echo     بعض الصفحات فشلت - انظر مراجعة.md في مجلد كل كتاب.
) else (
  echo [OK] Done. Start review from مراجعة.md in each output folder.
  echo      اكتمل. ابدأ المراجعة من مراجعة.md في مجلد كل كتاب.
)
pause
exit /b 0
