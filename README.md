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
- المرحلتان D وE (واجهة FastAPI + التقدم) لاحقتان.

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
