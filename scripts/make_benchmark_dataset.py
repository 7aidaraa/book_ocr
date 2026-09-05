"""Build the benchmark dataset: 8 Arabic page types with exact ground truth.

Why synthetic: ground truth typed by hand carries typing errors that are then
charged to the OCR engine. Here the reference text is the *source* the page is
rendered from, so CER/WER measure the engine and nothing else.

Its limit, stated plainly: a rendered page is cleaner than a real scan. These
numbers are a floor on error, not a prediction for a scanned book. The last
page is deliberately degraded (blur, noise, rotation, JPEG artefacts) to give
one data point closer to real scanning conditions; the real book benchmark
runs on the user's own machine against C:\\book.pdf.
"""

from __future__ import annotations

import io
import json
import random
from pathlib import Path

import pymupdf

DATASET_DIR = Path("data/work/ocr-benchmark/dataset")

_STYLE = "direction: rtl; text-align: right; font-size: 15px; line-height: 1.9;"

# Each page: (id, description, html, ground truth in reading order)
PAGES: list[tuple[str, str, str, str]] = [
    (
        "01-clean",
        "نثر عربي واضح، فقرات قصيرة",
        f"""<div style="{_STYLE}">
        <p>العلم نور يهتدي به الإنسان في ظلمات الجهل، وقد حث العلماء على طلبه
        منذ الصغر.</p>
        <p>ومن لم يذق مر التعلم ساعة، تجرع ذل الجهل طول حياته.</p>
        </div>""",
        "العلم نور يهتدي به الإنسان في ظلمات الجهل، وقد حث العلماء على طلبه منذ الصغر.\n"
        "ومن لم يذق مر التعلم ساعة، تجرع ذل الجهل طول حياته.",
    ),
    (
        "02-dense",
        "صفحة مزدحمة، فقرة طويلة متصلة",
        f"""<div style="{_STYLE}">
        <p>اعلم أن الكلام في هذا الباب يتفرع إلى وجوه، أولها النظر في اللفظ
        من حيث هو لفظ، وثانيها النظر فيه من حيث دلالته على المعنى، وثالثها
        النظر في المعنى من حيث هو معنى مجرد عن اللفظ، ورابعها النظر في
        التركيب الحاصل بين اللفظ والمعنى على جهة الوضع، وخامسها النظر في
        أحوال المتكلم والسامع، وسادسها النظر في المقام الذي يقتضي إيجازا أو
        إطنابا أو مساواة، وهذا كله مبسوط في مواضعه من كتب القوم.</p>
        </div>""",
        "اعلم أن الكلام في هذا الباب يتفرع إلى وجوه، أولها النظر في اللفظ من حيث هو لفظ، "
        "وثانيها النظر فيه من حيث دلالته على المعنى، وثالثها النظر في المعنى من حيث هو معنى "
        "مجرد عن اللفظ، ورابعها النظر في التركيب الحاصل بين اللفظ والمعنى على جهة الوضع، "
        "وخامسها النظر في أحوال المتكلم والسامع، وسادسها النظر في المقام الذي يقتضي إيجازا "
        "أو إطنابا أو مساواة، وهذا كله مبسوط في مواضعه من كتب القوم.",
    ),
    (
        "03-footnotes",
        "متن مع حواشٍ مرقمة أسفل الصفحة",
        f"""<div style="{_STYLE}">
        <p>قال المصنف رحمه الله: الفاعل مرفوع أبدا (١)، والمفعول منصوب (٢).</p>
        <hr/>
        <p style="font-size: 12px;">(١) وهذا مذهب البصريين، وخالفهم الكوفيون.</p>
        <p style="font-size: 12px;">(٢) إلا ما استثني مما ينوب عن الفاعل.</p>
        </div>""",
        "قال المصنف رحمه الله: الفاعل مرفوع أبدا (١)، والمفعول منصوب (٢).\n"
        "(١) وهذا مذهب البصريين، وخالفهم الكوفيون.\n"
        "(٢) إلا ما استثني مما ينوب عن الفاعل.",
    ),
    (
        "04-headings",
        "عناوين متعددة المستويات",
        f"""<div style="{_STYLE}">
        <h1 style="text-align: center;">كتاب الطهارة</h1>
        <h2>الفصل الأول: في المياه</h2>
        <p>الماء المطلق طاهر مطهر.</p>
        <h2>الفصل الثاني: في الآنية</h2>
        <p>يجوز استعمال كل إناء طاهر.</p>
        </div>""",
        "كتاب الطهارة\nالفصل الأول: في المياه\nالماء المطلق طاهر مطهر.\n"
        "الفصل الثاني: في الآنية\nيجوز استعمال كل إناء طاهر.",
    ),
    (
        "05-tashkeel",
        "نص مشكول بالكامل",
        f"""<div style="{_STYLE}">
        <p>الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ، وَالصَّلَاةُ وَالسَّلَامُ
        عَلَى أَشْرَفِ الْأَنْبِيَاءِ وَالْمُرْسَلِينَ.</p>
        <p>وَبَعْدُ: فَهَذَا مُخْتَصَرٌ فِي عِلْمِ النَّحْوِ.</p>
        </div>""",
        "الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ، وَالصَّلَاةُ وَالسَّلَامُ عَلَى أَشْرَفِ "
        "الْأَنْبِيَاءِ وَالْمُرْسَلِينَ.\nوَبَعْدُ: فَهَذَا مُخْتَصَرٌ فِي عِلْمِ النَّحْوِ.",
    ),
    (
        "06-table",
        "جدول بأعمدة",
        f"""<div style="{_STYLE}">
        <p>جدول الإعراب:</p>
        <table border="1" cellpadding="6" style="width: 100%; text-align: right;">
        <tr><td>الكلمة</td><td>الإعراب</td><td>العلامة</td></tr>
        <tr><td>محمد</td><td>فاعل</td><td>الضمة</td></tr>
        <tr><td>الكتاب</td><td>مفعول به</td><td>الفتحة</td></tr>
        </table>
        </div>""",
        "جدول الإعراب:\nالكلمة الإعراب العلامة\nمحمد فاعل الضمة\nالكتاب مفعول به الفتحة",
    ),
    (
        "07-numbers",
        "أرقام عربية وغربية ورموز",
        f"""<div style="{_STYLE}">
        <p>الطبعة الثالثة، سنة ١٤٣٥ هـ الموافق 2014 م، عدد الصفحات ٤٢٤.</p>
        <p>النسبة ٪٧٥، والسعر 12.50 د.ك، والهاتف 22334455.</p>
        <p>راجع الصفحات ١٢ - ٢٥ و٣٠/٤٠؛ انظر أيضا: باب [٣].</p>
        </div>""",
        "الطبعة الثالثة، سنة ١٤٣٥ هـ الموافق 2014 م، عدد الصفحات ٤٢٤.\n"
        "النسبة ٪٧٥، والسعر 12.50 د.ك، والهاتف 22334455.\n"
        "راجع الصفحات ١٢ - ٢٥ و٣٠/٤٠؛ انظر أيضا: باب [٣].",
    ),
    (
        "08-degraded",
        "محاكاة مسح ضوئي قديم (ضبابية، ضجيج، ميل، ضغط)",
        f"""<div style="{_STYLE}">
        <p>هذه صفحة تحاكي مسحا ضوئيا قديما، فيها ميل يسير وضجيج في الورق.</p>
        <p>والغرض منها قياس صمود المحرك أمام رداءة المسح لا رداءة الطباعة.</p>
        </div>""",
        "هذه صفحة تحاكي مسحا ضوئيا قديما، فيها ميل يسير وضجيج في الورق.\n"
        "والغرض منها قياس صمود المحرك أمام رداءة المسح لا رداءة الطباعة.",
    ),
]

DEGRADE_PAGE = "08-degraded"


def _degrade(png_bytes: bytes, seed: int = 7) -> bytes:
    """Make a clean render look like a mediocre scan, reproducibly."""
    from PIL import Image, ImageFilter

    random.seed(seed)
    image = Image.open(io.BytesIO(png_bytes)).convert("L")
    image = image.rotate(0.6, resample=Image.BICUBIC, fillcolor=245, expand=False)
    image = image.filter(ImageFilter.GaussianBlur(radius=0.7))

    pixels = image.load()
    width, height = image.size
    for _ in range((width * height) // 90):          # speckle
        x, y = random.randrange(width), random.randrange(height)
        pixels[x, y] = max(0, min(255, pixels[x, y] + random.randint(-70, 40)))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=45)    # generational loss
    return buffer.getvalue()


def build(out_dir: str | Path = DATASET_DIR, dpi: int = 200) -> dict:
    """Write pages.pdf plus one ground-truth .txt per page, and a manifest."""
    out_dir = Path(out_dir)
    truth_dir = out_dir / "ground_truth"
    truth_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open()
    manifest = {"dpi": dpi, "pages": []}

    for index, (page_id, description, html, truth) in enumerate(PAGES, 1):
        page = doc.new_page(width=595, height=842)
        page.insert_htmlbox(pymupdf.Rect(45, 45, 550, 797), html)

        if page_id == DEGRADE_PAGE:
            # Re-render this page as a degraded raster and replace it, so the
            # pipeline sees a scanned-looking page through the normal path.
            pixmap = page.get_pixmap(dpi=dpi)
            degraded = _degrade(pixmap.tobytes("png"))
            doc.delete_page(page.number)
            replacement = doc.new_page(width=595, height=842)
            replacement.insert_image(pymupdf.Rect(0, 0, 595, 842), stream=degraded)

        (truth_dir / f"{page_id}.txt").write_text(truth + "\n", encoding="utf-8")
        manifest["pages"].append({
            "page_number": index,
            "id": page_id,
            "description": description,
            "ground_truth": f"ground_truth/{page_id}.txt",
        })

    pdf_path = out_dir / "pages.pdf"
    doc.save(pdf_path)
    doc.close()
    manifest["pdf"] = str(pdf_path)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    info = build()
    print(f"{info['pdf']}: {len(info['pages'])} pages")
