# طبقة مصادر الكتب — Book Sources Layer

طبقة **فوق** خط المعالجة، لا داخله. مهمتها تنتهي عند تسليم مسار PDF محلي
متحقَّق منه إلى `process_book()` — نفس الدالة التي يستدعيها الرفع اليدوي.

## المسار

```
استعلام المستخدم
   ↓  resolver.parse_query
SearchQuery
   ↓  BookSource.search  (لكل مصدر مفعّل)
BookCandidate[]
   ↓  resolver.resolve → normalize / dedupe / rank / §7
النتيجة المختارة
   ↓  policies.check_url  (كل قفزة، بلا استثناء)
   ↓  downloader.download (streaming + sha256 + retry + cancel)
ملف محلي
   ↓  verifier.verify_pdf (%PDF- + %%EOF + فتح فعلي + الحدود)
VerifiedPdf
   ↓  acquire.run_acquisition
process_book()   ← خط OCR الحالي، بلا تعديل
```

## الملفات

| الملف | المسؤولية |
|---|---|
| `base.py` | `BookSource` و`BookCandidate` و`SearchQuery` |
| `policies.py` | البوابة الأمنية: https فقط، allowlist، رفض العناوين الخاصة |
| `resolver.py` | تطبيع عربي، ترتيب، إزالة تكرار، قاعدة المؤلف §7 |
| `downloader.py` | تنزيل متدفق بـurllib، redirect يدوي لفحص كل قفزة |
| `verifier.py` | إثبات أن الملف PDF كامل وقابل للفتح |
| `cache.py` | ذاكرة نتائج البحث فقط، بـTTL. لا تُخزَّن ملفات |
| `metadata.py` | سجل المنشأ §19 |
| `registry.py` | جدول المصادر وحالة التحقق من كل واحد |
| `sources/mock.py` | مكتبة محلية تسلك سلوك مصدر بعيد — للاختبار والعرض |

## قاعدتان لا تُخترقان

1. **المستخدم لا يرسل رابطًا أبدًا.** `/api/books/acquire` يقبل مُعرّف نتيجة
   أصدرها الخادم نفسه، لا `pdf_url`. لذلك لا يمكن تحويل الطبقة إلى وكيل SSRF.
2. **الميتاداتا ليست محتوى.** ما يقوله المصدر عن الكتاب يُسجَّل كمنشأ فقط.
   نص الكتاب يأتي حصرًا من OCR للصفحات، مع `source_page` لكل صفحة.

## تفعيل المصادر

لا مصدر مفعّل افتراضيًا. شبكة الفكر `UNVERIFIED` ولا يوجد كود يتصل بها
(`factory = None`).

للتجربة محليًا بمكتبة وهمية من ملفاتك الحقيقية:

```cmd
mkdir data\mock-library
copy C:\book.pdf data\mock-library\
set BOOKSOURCES_MOCK=1
start.bat
```

يظهر قسم «🔎 ابحث عن كتاب» في الواجهة. بدون هذا المتغير لا يظهر القسم أصلًا.

## أوامر

```
python -m app.cli sources          # جدول المصادر وحالتها
python -m app.cli search "قطر الندى" --author "ابن هشام"
python -m app.cli probe            # إعادة فحص الوصول
```

## المهام

تُحفظ في `data/jobs/<id>.json` (خارج جيت). الحالات:
`queued → downloading → processing → completed | failed | cancelled`.

مهمة قُطعت بإعادة تشغيل الخادم تُفتح كـ`failed` مع `interrupted: true` —
لا تختفي، ولا تُستأنف تلقائيًا. إعادة التشغيل تستفيد من استئناف OCR الحالي
فتتخطى الصفحات الناجحة.
