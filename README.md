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

## المنصة برابط، من الهاتف، مجانًا (Google Colab)

يشغّل المنصة كاملة على خوادم Colab ويعطيك رابطًا عامًا تفتحه من أي جهاز:

1. افتح: <https://colab.research.google.com/github/7aidaraa/book_ocr/blob/main/colab/arabic_book_ocr.ipynb>
2. شغّل الخلايا الثلاث بالترتيب (زر ▶).
3. الخلية الثالثة تطبع رابطًا مثل `https://xxxx.trycloudflare.com` — اضغطه لتفتح الواجهة.

⚠ اترك تبويب Colab مفتوحًا أثناء العمل؛ الرابط يتغيّر في كل تشغيل؛ والمعالجة على خوادم Google لا على جهازك.

## رابط ثابت مجاني على Render (محرك Tesseract الخفيف)

خطة Render المجانية (512MB) لا تكفي PaddleOCR، لكنها تكفي محرك Tesseract البديل —
دقة أقل وسرعة أبطأ، مقابل رابط ثابت يعمل دائمًا:

1. من لوحة Render: **New ← Blueprint** ← اربط مستودع `book_ocr` — يقرأ `render.yaml` تلقائيًا.
2. أو: **New ← Web Service** ← اختر المستودع ← Runtime: **Docker** ← Dockerfile Path: `Dockerfile.render` ← Plan: **Free**.

ملاحظات الخطة المجانية: الخدمة تنام بعد 15 دقيقة خمول (أول فتح بعدها يتأخر ~دقيقة)،
والقرص مؤقت — نزّل `book.md` بعد كل تحويل.

### عن الاستضافة الدائمة

ملفا [`Dockerfile`](Dockerfile) و[`deploy/hf-space-Dockerfile`](deploy/hf-space-Dockerfile) جاهزان لأي
استضافة تدعم الحاويات. لكن Hugging Face Spaces لم تعد تصلح مجانًا: أنواع Docker وGradio صارت
تتطلب اشتراك PRO، والمجاني منها Static فقط (لا يشغّل بايثون). كذلك الخطط المجانية في Render
وأمثالها (512MB ذاكرة) لا تكفي نماذج PaddleOCR.

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
