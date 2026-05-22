"""
מעבד נספחים משפטיים
עומד בהוראת מנהל בתי המשפט בדבר צורת מסמך ומבנהו (כ"ו תמוז תשפ"ה)
עיצוב מבוסס על מסמכי בתי משפט ישראליים בפועל
"""

import base64
import io
import os

from pypdf import PdfReader, PdfWriter
import weasyprint
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

# ---------------------------------------------------------------------------
# Font loading — David (מיקרוסופט וורד) עם fallback ל-Frank Ruhl Libre
# ---------------------------------------------------------------------------

_FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")

# מיקומים סטנדרטיים של גופן דוד — macOS ו-Windows
_DAVID_SEARCH = [
    # תיקיית הפרויקט (אם המשתמש העתיק ידנית)
    (os.path.join(_FONT_DIR, "David-Regular.ttf"),
     os.path.join(_FONT_DIR, "David-Bold.ttf")),
    # Microsoft Word — macOS
    ("/Applications/Microsoft Word.app/Contents/Resources/DFonts/david.ttf",
     "/Applications/Microsoft Word.app/Contents/Resources/DFonts/davidbd.ttf"),
    # גופני מערכת — macOS
    ("/Library/Fonts/David.ttf",          "/Library/Fonts/David Bold.ttf"),
    (os.path.expanduser("~/Library/Fonts/David.ttf"),
     os.path.expanduser("~/Library/Fonts/David Bold.ttf")),
    # Windows
    (r"C:\Windows\Fonts\david.ttf",       r"C:\Windows\Fonts\davidbd.ttf"),
]

def _find_david():
    for reg, bold in _DAVID_SEARCH:
        if os.path.exists(reg):
            return reg, bold if os.path.exists(bold) else reg
    return None, None

def _font_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

_david_reg, _david_bold = _find_david()

if _david_reg:
    _FONT_CSS = f"""
  @font-face {{
    font-family: 'David';
    font-weight: normal;
    src: url("data:font/truetype;base64,{_font_b64(_david_reg)}") format('truetype');
  }}
  @font-face {{
    font-family: 'David';
    font-weight: bold;
    src: url("data:font/truetype;base64,{_font_b64(_david_bold)}") format('truetype');
  }}
"""
else:
    # Fallback: Frank Ruhl Libre
    try:
        _reg_b64  = _font_b64(os.path.join(_FONT_DIR, "FrankRuhlLibre-Regular.ttf"))
        _bold_b64 = _font_b64(os.path.join(_FONT_DIR, "FrankRuhlLibre-Bold.ttf"))
        _FONT_CSS = f"""
  @font-face {{
    font-family: 'David';
    font-weight: normal;
    src: url("data:font/truetype;base64,{_reg_b64}") format('truetype');
  }}
  @font-face {{
    font-family: 'David';
    font-weight: bold;
    src: url("data:font/truetype;base64,{_bold_b64}") format('truetype');
  }}
"""
    except FileNotFoundError:
        _FONT_CSS = ""

# ---------------------------------------------------------------------------
# Shared CSS base (A4, 2.5cm margins, David font, 1.5 spacing — per directive)
# ---------------------------------------------------------------------------

_BASE_CSS = f"""
  {_FONT_CSS}
  @page {{
    size: 210mm 297mm;
    margin: 25mm;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    direction: rtl;
    font-family: 'David', Calibri, "Raanana", Arial, sans-serif;
    font-size: 12pt;
    line-height: 1.5;
    color: #000;
  }}
"""

# ---------------------------------------------------------------------------
# Cover page
# Layout (per reference documents):
#   top-center: "נספח N"  (bold, 36pt — per directive)
#   below:       description (bold, 24pt)
#   middle:     "עמוד N"  (regular, 18pt)
#   no border, no frame
# ---------------------------------------------------------------------------

COVER_HTML = """<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8">
<style>
  {base_css}
  .cover-top {{
    text-align: center;
    padding-top: 0.5cm;
  }}
  .appendix-title {{
    font-size: 36pt;
    font-weight: bold;
    display: block;
    margin-bottom: 0.5cm;
    letter-spacing: 0.02em;
  }}
  .appendix-desc {{
    font-size: 24pt;
    font-weight: bold;
    display: block;
    line-height: 1.4;
  }}
  .page-ref {{
    display: block;
    text-align: center;
    font-size: 18pt;
    font-weight: normal;
    margin-top: 2.5cm;
  }}
</style>
</head>
<body>
  <div class="cover-top">
    <span class="appendix-title">נספח {num}</span>
    <span class="appendix-desc">{name}</span>
  </div>
  <div class="page-ref">עמוד {page}</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Index / TOC page
# Title: "תוכן עניינים לנספחים"
# Table columns (RTL): נספח מס | שם הנספח | עמוד
# ---------------------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8">
<style>
  {base_css}
  h1 {{
    font-size: 22pt;
    font-weight: bold;
    text-align: center;
    margin-bottom: 0.8cm;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 0.3cm;
    font-size: 11pt;
  }}
  th, td {{
    border: 1px solid #000;
    padding: 0.18cm 0.35cm;
    text-align: right;
    vertical-align: top;
  }}
  thead tr {{
    background-color: #f0f0f0;
  }}
  th {{
    font-weight: bold;
    font-size: 11pt;
  }}
  .col-num  {{ width: 16%; white-space: nowrap; font-weight: bold; }}
  .col-name {{ width: 68%; }}
  .col-page {{ width: 16%; text-align: center; }}
  tr:nth-child(even) td {{ background-color: #fafafa; }}
</style>
</head>
<body>
  <h1>תוכן עניינים לנספחים</h1>
  <table>
    <thead>
      <tr>
        <th class="col-num">נספח מס</th>
        <th class="col-name">שם הנספח</th>
        <th class="col-page">עמוד</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Hebrew numeral helper (gematria)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _html_to_pdf(html: str) -> bytes:
    return weasyprint.HTML(string=html).write_pdf()


def _count_pages(pdf_bytes: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf_bytes)).pages)


def _make_number_overlay(w: float, h: float, page_num: int) -> object:
    """Return a single-page PdfReader with a '- N -' overlay."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setFont("Helvetica", 10)
    c.setFillColorRGB(0, 0, 0)
    c.drawCentredString(w / 2, 14 * mm, f"- {page_num} -")
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def _add_page_numbers_selective(
    pdf_bytes: bytes,
    main_doc_pages: int,
    main_doc_numbered: bool,
    numbered_start: int,
) -> bytes:
    """
    Overlay '- N -' page numbers.
    - Main doc pages: numbered only if main_doc_numbered is True.
    - All subsequent pages (pre-TOC, TOC, appendices): always numbered.
    numbering counter starts at numbered_start regardless.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    counter = numbered_start

    for i, page in enumerate(reader.pages):
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        if i < main_doc_pages:
            if main_doc_numbered:
                page.merge_page(_make_number_overlay(w, h, counter))
                counter += 1
        else:
            page.merge_page(_make_number_overlay(w, h, counter))
            counter += 1
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_appendices(
    appendices: list[dict],
    start_page_offset: int = 1,
    main_doc: dict | None = None,
    pre_toc_docs: list[dict] | None = None,
) -> bytes:
    """
    Build a merged PDF:
      [main_doc?] + [pre_toc_docs?] + TOC + [cover+content]×N + page numbers

    Parameters
    ----------
    appendices : list of {'pdf_bytes': bytes, 'name': str}
    start_page_offset : int
        First page number in the continuous sequence (default 1).
        If main_doc is numbered it starts here; otherwise pre_toc / TOC start here.
    main_doc : {'pdf_bytes': bytes, 'add_numbering': bool} or None
        The pleading document. Prepended before everything else.
    pre_toc_docs : list of {'pdf_bytes': bytes, 'name': str} or None
        Extra docs (תצהיר, ייפוי כוח…) placed after main_doc but before the TOC.
        Always receive page numbers.
    """
    if not appendices:
        raise ValueError("אין נספחים לעיבוד")

    if pre_toc_docs is None:
        pre_toc_docs = []

    main_doc_pages   = _count_pages(main_doc['pdf_bytes']) if main_doc else 0
    main_doc_numbered = bool(main_doc.get('add_numbering')) if main_doc else False
    pre_toc_counts   = [_count_pages(d['pdf_bytes']) for d in pre_toc_docs]
    pre_toc_total    = sum(pre_toc_counts)

    # ── Page-number accounting ───────────────────────────────────────────────
    # The continuous counter always starts at start_page_offset.
    # If main_doc is numbered, it consumes that many numbers first.
    # Pre-TOC docs and TOC always consume numbers.
    if main_doc_numbered:
        after_main = start_page_offset + main_doc_pages
    else:
        after_main = start_page_offset   # main_doc pages don't consume numbers

    # TOC sits at: after_main + pre_toc_total
    toc_page = after_main + pre_toc_total

    # First appendix cover starts after TOC (1 page)
    current = toc_page + 1
    appendix_meta = []
    cover_start_pages = []
    for i, count in enumerate(_count_pages(f['pdf_bytes']) for f in appendices):
        cover_start_pages.append(current)
        appendix_meta.append({'num': i + 1, 'name': appendices[i]['name'], 'start_page': current})
        current += 1 + count

    # ── Build merged PDF ─────────────────────────────────────────────────────
    merger = PdfWriter()

    # 1. Main document
    if main_doc:
        for page in PdfReader(io.BytesIO(main_doc['pdf_bytes'])).pages:
            merger.add_page(page)

    # 2. Pre-TOC documents
    for doc in pre_toc_docs:
        for page in PdfReader(io.BytesIO(doc['pdf_bytes'])).pages:
            merger.add_page(page)

    # 3. TOC
    rows_html = "".join(
        f'<tr><td class="col-num">נספח {m["num"]}</td>'
        f'<td class="col-name">{m["name"]}</td>'
        f'<td class="col-page">{m["start_page"]}</td></tr>'
        for m in appendix_meta
    )
    toc_pdf = _html_to_pdf(INDEX_HTML.format(base_css=_BASE_CSS, rows=rows_html))
    for page in PdfReader(io.BytesIO(toc_pdf)).pages:
        merger.add_page(page)

    # 4. Appendices (cover + content)
    for i, f in enumerate(appendices):
        cover_pdf = _html_to_pdf(COVER_HTML.format(
            base_css=_BASE_CSS, num=i + 1,
            name=f['name'], page=cover_start_pages[i],
        ))
        for page in PdfReader(io.BytesIO(cover_pdf)).pages:
            merger.add_page(page)
        for page in PdfReader(io.BytesIO(f['pdf_bytes'])).pages:
            merger.add_page(page)

    # ── Overlay page numbers ─────────────────────────────────────────────────
    merged_buf = io.BytesIO()
    merger.write(merged_buf)
    return _add_page_numbers_selective(
        merged_buf.getvalue(),
        main_doc_pages=main_doc_pages,
        main_doc_numbered=main_doc_numbered,
        numbered_start=start_page_offset,
    )
