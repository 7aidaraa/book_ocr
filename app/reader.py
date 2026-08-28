"""Built-in book reader: renders book.md to a clean RTL HTML page.

Server-side rendering with the `markdown` library (BSD) — fully offline,
no CDN, no JavaScript needed to read.
"""

from __future__ import annotations

import markdown as md_lib

_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Amiri:wght@400;700&family=Tajawal:wght@400;700&display=swap');
* {{ box-sizing: border-box; }}
body {{
  font-family: "Amiri", "Noto Naskh Arabic", "Segoe UI", serif;
  background: #f3efe6; color: #23211c; margin: 0;
  line-height: 2.15;
}}
.topbar {{ font-family: "Tajawal", "Segoe UI", sans-serif; }}
.topbar {{
  position: sticky; top: 0; background: #fff;
  border-bottom: 1px solid #e0dbd0; padding: .6rem 1rem;
  display: flex; justify-content: space-between; align-items: center;
}}
.topbar a {{ color: #1f6f54; text-decoration: none; font-weight: 600; }}
.content {{
  max-width: 760px; margin: 0 auto; padding: 2rem 1.25rem 4rem;
  background: #fff; min-height: 100vh;
  border-inline: 1px solid #e0dbd0;
  font-size: 1.1rem;
}}
.content h1 {{ font-size: 1.6rem; }}
.content h2 {{
  font-size: 1.15rem; color: #1f6f54;
  border-bottom: 1px dashed #d5cfc2; padding-bottom: .3rem;
  margin-top: 2.5rem;
}}
.content blockquote {{
  border-inline-start: 3px solid #c9a227; margin: 1rem 0;
  padding: .25rem 1rem; color: #6b675e; background: #faf8f2;
}}
.content hr {{ border: none; border-top: 1px solid #e0dbd0; margin: 2rem 0; }}
</style>
</head>
<body>
  <nav class="topbar">
    <span>{title}</span>
    <a href="/">⌂ المنصة</a>
  </nav>
  <article class="content">
{body}
  </article>
</body>
</html>
"""


def render_book_html(book_md_text: str, book_name: str) -> str:
    body = md_lib.markdown(book_md_text, extensions=["tables"])
    return _PAGE_TEMPLATE.format(title=book_name, body=body)
