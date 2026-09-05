@echo off
chcp 65001 >nul
title Arabic Book OCR — Engine Benchmark
cd /d "%~dp0"

rem Compare OCR engines on identical pages and write numbers, not impressions.
rem Surya lives in its OWN environment (.venv-surya) so the working .venv is
rem never touched: Surya would otherwise downgrade pillow and add ~2.5 GB.

if not exist .venv\INSTALLED_OK (
  echo [!] Run start.bat once first. / شغّل start.bat أولًا.
  pause
  exit /b 1
)

echo.
echo [1/3] Benchmarking the current engine ^(Tesseract^)...
echo       قياس المحرك الحالي — سريع، بلا أي تثبيت.
echo.
.venv\Scripts\python -m app.cli ocr-benchmark --engines tesseract || goto :fail

echo.
echo [2/3] Preparing Surya in a separate environment...
echo       تجهيز Surya في بيئة منفصلة — لا يمسّ .venv إطلاقًا.
echo       أول مرة فقط: ~2.5 غيغابايت. اترك النافذة مفتوحة.
echo.
if not exist .venv-surya\Scripts\python.exe (
  python -m venv .venv-surya || goto :fail
)
.venv-surya\Scripts\python -m pip install -q --upgrade pip
.venv-surya\Scripts\python -m pip install -r requirements-surya.txt || goto :fail

echo.
echo [3/3] Benchmarking Surya on the SAME pages...
echo       أول تشغيل ينزّل نماذج Surya ^(~1 غيغابايت^) من models.datalab.to
echo.
.venv-surya\Scripts\python -m app.cli ocr-benchmark --engines surya ^
  --out data\work\ocr-benchmark-surya || goto :fail

echo.
echo [OK] Done. Send BOTH report.md files to Claude:
echo      اكتمل. أرسل الملفين إلى كلود:
echo        data\work\ocr-benchmark\report.md
echo        data\work\ocr-benchmark-surya\report.md
start "" explorer "data\work"
pause
exit /b 0

:fail
echo.
echo [X] Failed. Copy the error text above and send it.
echo     فشل — انسخ نص الخطأ أعلاه وأرسله.
pause
exit /b 1
