"""Generate a small local Arabic PDF fixture — no internet, no real book.

insert_htmlbox uses MuPDF's Story engine, which shapes Arabic (bidi +
ligatures) correctly, so the rendered page is realistic enough for OCR.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

ARABIC_HTML = """
<div style="direction: rtl; text-align: right; font-size: 16px;">
<h1 style="text-align: center;">الفصل الأول: في طلب العلم</h1>
<p>العلم نورٌ يهتدي به الإنسان في ظلمات الجهل، وقد حثّ العلماء على طلبه
منذ الصغر، فقالوا: العلم في الصغر كالنقش على الحجر.</p>
<p style="text-align: center;">
اطلبِ العلمَ ولا تكسَلْ فما<br/>
أبعدَ الخيرَ على أهلِ الكسَلْ
</p>
<p>وهذا نصٌّ ثانٍ للتجربة يحتوي على كلماتٍ مشكولةٍ مثل: العِلْمُ
والحِكْمَةُ والصَّبْرُ.</p>
</div>
"""


def make_fixture(out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)  # A4
    rect = pymupdf.Rect(50, 50, 545, 792)
    page.insert_htmlbox(rect, ARABIC_HTML)
    doc.save(out_path)
    doc.close()
    return out_path


if __name__ == "__main__":
    print(make_fixture("data/input/fixture.pdf"))
