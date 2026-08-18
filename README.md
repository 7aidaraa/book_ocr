# Arabic Book OCR

منصة محلية مجانية بالكامل لتحويل كتب PDF العربية المصوّرة إلى Markdown عالي الجودة.

- كل المعالجة على جهازك — لا Cloud، لا API مدفوع، لا رفع للكتب إلى الإنترنت.
- المحرك الأساسي: PaddleOCR / PP-StructureV3 (تحليل تخطيط + ترتيب قراءة)، مع واجهة `OCREngine` تسمح بإضافة Tesseract لاحقًا.
- المبدأ: استخراج أمين — لا تصحيح بالذكاء الاصطناعي، لا حذف تشكيل، لا دمج أسطر الشعر.

الخطة الكاملة: [`خطة-منصة-OCR.md`](خطة-منصة-OCR.md)

## الحالة

المرحلة A منجزة: صفحة واحدة ← OCR ← `PageResult` ← Markdown، مع اختبارات.
المراحل B–E (كتاب كامل، `book.md`، الواجهة، التقدم) لاحقة.

## التثبيت

```bash
pip install -r requirements.txt
```

عند أول تشغيل يُنزّل PaddleOCR نماذجه مرة واحدة (من HuggingFace أو BOS — يلزم إنترنت لهذه المرة فقط)، ثم يعمل كل شيء Offline.

## الاستخدام (المرحلة A)

```bash
# صفحة واحدة من PDF محلي (الملف الأصلي لا يُمس)
python -m app.cli path/to/book.pdf --page 1
```

الناتج الوسيط في `data/work/<اسم-الكتاب>/pages/NNN/` — يشمل `source.png` و`ocr.json` و`result.md`.

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
├── cli.py           # تشغيل يدوي للمرحلة A
└── engines/
    ├── base.py                # واجهة OCREngine
    └── paddleocr_engine.py    # PP-StructureV3
```
