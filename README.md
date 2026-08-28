# Arabic Book OCR

منصة محلية مجانية بالكامل لتحويل كتب PDF العربية المصوّرة إلى Markdown عالي الجودة.

- كل المعالجة على جهازك — لا Cloud، لا API مدفوع، لا رفع للكتب إلى الإنترنت.
- المحرك الأساسي: PaddleOCR / PP-StructureV3 (تحليل تخطيط + ترتيب قراءة)، مع واجهة `OCREngine` تسمح بإضافة Tesseract لاحقًا.
- المبدأ: استخراج أمين — لا تصحيح بالذكاء الاصطناعي، لا حذف تشكيل، لا دمج أسطر الشعر.

الخطة الكاملة: [`خطة-منصة-OCR.md`](خطة-منصة-OCR.md)

## الحالة

- المرحلة A ✓ — صفحة واحدة ← OCR ← `PageResult` ← Markdown.
- المرحلة B ✓ — كتاب كامل ← `pages/*.md` (صفحة بصفحة، فشل صفحة لا يوقف الكتاب، إعادة التشغيل تعالج الفاشلة فقط).
- المرحلة C ✓ — `book.md` + `metadata.json` + `README.md` لكل كتاب.
- المرحلة D ✓ — خادم FastAPI + واجهة عربية RTL (رفع محلي، بدء التحويل).
- المرحلة E ✓ — شريط تقدم وحالة عبر polling.
- القارئ المدمج ✓ — بعد التحويل يفتح الكتاب على `/reader/<اسم-الكتاب>` بعرض قراءة RTL، مع قائمة الكتب المحوّلة في الصفحة الرئيسية.

## التشغيل (الواجهة)

```bash
python run.py
```

ثم افتح: `http://127.0.0.1:8000`

## نشر المنصة على رابط دائم (Hugging Face Spaces — مجاني)

يعطيك رابطًا ثابتًا بواجهة كاملة تفتح من الهاتف بلا أي تثبيت.

1. أنشئ Space جديدًا: <https://huggingface.co/new-space> — اختر **Docker ← Blank**، والرؤية **Private**.
2. من تبويب **Files ← + Add file ← Create a new file**، سمِّ الملف `Dockerfile`، والصق فيه محتوى
   [`deploy/hf-space-Dockerfile`](deploy/hf-space-Dockerfile) ثم **Commit**.
3. انتظر البناء (~10 دقائق أول مرة) ← يفتح الرابط على واجهة المنصة.

بعد أي تحديث هنا: **Settings ← Factory rebuild**.

⚠ ملاحظتان: المعالجة تجري على خوادم Hugging Face لا على جهازك؛ ومساحة التخزين مؤقتة —
نزّل `book.md` بعد كل تحويل، فالنتائج تُمحى عند إعادة تشغيل الـSpace.

## التشغيل من هاتف أندرويد (عبر Google Colab)

لا يمكن تشغيل PaddleOCR على الهاتف مباشرة، لكن يمكن تشغيله مجانًا على خوادم Colab من متصفح الهاتف:

1. افتح: <https://colab.research.google.com/github/7aidaraa/book_ocr/blob/main/colab/arabic_book_ocr.ipynb>
2. سجّل دخول بحساب Google ← **Runtime ← Run all**.
3. ارفع PDF عند الطلب ← انتظر ← ينزل ZIP فيه `book.md` وكل الصفحات.

⚠ في هذا المسار يُعالَج الكتاب على خوادم Google، لا محليًا.

## أسرع تشغيل على Windows (بلا أوامر)

1. ثبّت Python من python.org — فعّل خيار `Add python.exe to PATH` أثناء التثبيت (مرة واحدة).
2. نزّل المشروع ZIP: <https://github.com/7aidaraa/book_ocr/archive/refs/heads/main.zip> وفك الضغط.
3. انقر نقرًا مزدوجًا على `start.bat` — أول مرة يثبّت كل شيء تلقائيًا (~1GB)، ثم يفتح المتصفح على `http://127.0.0.1:8000` وحده.

في المرات التالية: نقرة على `start.bat` فقط.

## التثبيت

```bash
pip install -r requirements.txt
```

عند أول تشغيل يُنزّل PaddleOCR نماذجه مرة واحدة (من HuggingFace أو BOS — يلزم إنترنت لهذه المرة فقط)، ثم يعمل كل شيء Offline.

## الاستخدام

```bash
# كتاب كامل (الملف الأصلي لا يُمس)
python -m app.cli path/to/book.pdf

# صفحة واحدة للتجربة
python -m app.cli path/to/book.pdf --page 1

# إعادة معالجة كل الصفحات حتى الناجحة
python -m app.cli path/to/book.pdf --no-resume
```

الناتج النهائي في `data/output/<اسم-الكتاب>/` (`book.md`, `metadata.json`, `pages/`)،
والوسائط في `data/work/<اسم-الكتاب>/pages/NNN/` (`source.png`, `ocr.json`, `result.md`) وقابلة للحذف.

## الاختبار

```bash
python -m pytest tests/ -m "not slow"   # اختبارات النواة (بلا نماذج)
python -m pytest tests/ -m slow          # اختبار PaddleOCR الكامل
```

الاختبارات تولّد PDF عربي تجريبي محليًا — لا حاجة لأي ملف خارجي.

## البنية

```text
app/
├── models.py        # PageResult / Block — البيانات المنظمة
├── pdf.py           # قراءة PDF صفحة بصفحة (PyMuPDF)
├── markdown.py      # PageResult ← Markdown محافظ
├── pipeline.py      # خط معالجة الصفحة الواحدة
├── book.py          # الكتاب كامل: pages/ + book.md + metadata.json + استئناف
├── cli.py           # تشغيل يدوي (كتاب كامل أو صفحة)
└── engines/
    ├── base.py                # واجهة OCREngine
    └── paddleocr_engine.py    # PP-StructureV3
```
