"""
PDF highlight & annotation extractor -> Obsidian-ready Markdown.
"""

import os
import re
import sys
import unicodedata
from datetime import date
from statistics import median

try:
    import pymupdf as fitz  # PyMuPDF >= 1.24
except ImportError:  # older installs
    import fitz


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INPUT_FOLDER = "A"
OUTPUT_FOLDER = "B"

# Category -> (hex color, Obsidian tag). Order here = order in the output.
# Tags can't contain spaces or commas in Obsidian, so they are kebab-case.
CATEGORIES = {
    "Work Specific Note": ("#D7FB00", "work-specific-note"),
    "Important": ("#FF5D90", "important"),
    "Stats": ("#EC9FFF", "stats"),
    "General Notes": ("#B5F0FF", "general-notes"),
    "Definitions, Locations, People, Organizations": ("#FFFB00", "definitions-locations-people-organizations"),
    "Author Thesis and Methodology": ("#FFCC00", "author-thesis-and-methodology"),
    "Quotes": ("#D6D6D6", "quotes"),
}
MARGIN_NOTE_CATEGORY = "Margin Notes"
MARGIN_NOTE_TAG = "margin-note"
UNCATEGORIZED = "Uncategorized"
UNCATEGORIZED_TAG = "uncategorized-highlight"

# Tag added to every note's frontmatter.
DOCUMENT_TAG = "pdf-annotations"

# Max RGB distance (0-1 scale) for a highlight color to match a category.
# Colors go to the NEAREST palette entry; this only decides when a color is
# too far from all of them and goes to "Uncategorized" instead.
MAX_COLOR_DISTANCE = 0.18

# Scans with two book pages side by side on each PDF page.
#   "auto" = treat landscape PDF pages as two-page spreads
#   True / False = force on / off
SPLIT_SPREADS = "auto"

# Read printed page numbers from the top/bottom of each book page (e.g. 16, 17)
# and cite those instead of the PDF page number.
DETECT_PRINTED_PAGE_NUMBERS = True

# Remove footnote markers stuck to the end of sentences ("been.3" -> "been.")
STRIP_FOOTNOTE_MARKERS = True

# A margin note's color is matched to the category palette too; when it
# matches (e.g. your red note = Important) that category's tag is added.
TAG_MARGIN_NOTES_BY_COLOR = True

# Annotation types (PyMuPDF codes)
TEXT = fitz.PDF_ANNOT_TEXT            # sticky note
FREETEXT = fitz.PDF_ANNOT_FREE_TEXT   # text typed on the page / in the margin
INK = fitz.PDF_ANNOT_INK              # handwriting / pen
MARKUP_TYPES = {fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE,
                fitz.PDF_ANNOT_SQUIGGLY, fitz.PDF_ANNOT_STRIKE_OUT}
IGNORED_TYPES = {fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_POPUP, fitz.PDF_ANNOT_WIDGET}

WORD_FLAGS = fitz.TEXTFLAGS_WORDS & ~fitz.TEXT_DEHYPHENATE  # keep "con-"


# ---------------------------------------------------------------------------
# Text cleanup
# ---------------------------------------------------------------------------

def clean_text(text):
    """Normalize whitespace and typographic artifacts, keeping real characters
    (curly quotes, dashes, accents)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)  # ligatures etc.
    text = text.replace("­", "").replace("�", "")
    text = re.sub(r"(\w)-\s*\n\s*([a-z])", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tidy_punctuation(text):
    """OCR layers often store punctuation as separate words, giving
    'town . He' and ' " industrial unionist " '. Put it back where it goes."""
    text = re.sub(r"\s+([,.;:!?)\]}’”])", r"\1", text)
    text = re.sub(r"([(\[{‘“])\s+", r"\1", text)
    # Straight double quotes: pair them up, opening then closing.
    parts = text.split('"')
    if len(parts) > 1:
        out = parts[0]
        for i, seg in enumerate(parts[1:], start=1):
            if i % 2 == 1:   # opening quote
                out = out + '"' + seg.lstrip()
            else:            # closing quote
                out = out.rstrip() + '"' + seg
        text = out
    if STRIP_FOOTNOTE_MARKERS:
        text = re.sub(r"(?<![\d\s])([.,;:!?”\"’])\d{1,3}(?=\s|$)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def join_lines(lines):
    """Join highlighted line fragments, repairing end-of-line hyphenation."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out.endswith("-") and line[:1].islower() and not out.endswith(" -"):
            out = out[:-1] + line
        elif out:
            out += " " + line
        else:
            out = line
    return tidy_punctuation(clean_text(out))


def md_escape(text):
    """Stop extracted text from becoming Markdown structure or Obsidian
    tags/links by accident."""
    text = re.sub(r"(^|\s)#(?=\w)", r"\1\\#", text)
    text = text.replace("[[", "\\[\\[").replace("]]", "\\]\\]")
    text = re.sub(r"^([>*+-]|\d+\.)\s", r"\\\1 ", text)
    return text


def strip_xml(rich):
    """Plain text from a rich-text (/RC) XHTML string."""
    rich = re.sub(r"<br\s*/?>|</p>", "\n", rich, flags=re.I)
    rich = re.sub(r"<[^>]+>", "", rich)
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&apos;", "'"), ("&#39;", "'"), ("&nbsp;", " ")):
        rich = rich.replace(a, b)
    return clean_text(rich)


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

def hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#" + "".join(f"{round(c * 255):02X}" for c in rgb[:3])


def int_to_rgb(c):
    return ((c >> 16) & 255) / 255.0, ((c >> 8) & 255) / 255.0, (c & 255) / 255.0


PALETTE = {name: hex_to_rgb(hex_) for name, (hex_, _tag) in CATEGORIES.items()}


def classify_color(color, max_dist=MAX_COLOR_DISTANCE):
    """Nearest category color, or None if nothing is close enough."""
    if not color or len(color) < 3:
        return None
    color = tuple(color[:3])
    if max(color) > 1:
        color = tuple(c / 255.0 for c in color)
    best_name, best_dist = None, float("inf")
    for name, ref in PALETTE.items():
        dist = sum((a - b) ** 2 for a, b in zip(color, ref)) ** 0.5
        if dist < best_dist:
            best_name, best_dist = name, dist
    return best_name if best_dist <= max_dist else None


def is_colorful(rgb):
    """True for clearly colored ink (red, blue...) as opposed to black/gray
    print. Used to spot margin notes that were flattened into the page."""
    return max(rgb) - min(rgb) > 0.35


def annot_color(annot):
    colors = annot.colors or {}
    return colors.get("stroke") or colors.get("fill")


def note_color(doc, annot):
    """Color of a typed note's TEXT (stored in the /DA string, e.g.
    '1 0.36 0.56 rg'), falling back to its border/fill color."""
    try:
        kind, da = doc.xref_get_key(annot.xref, "DA")
        m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da or "")
        if m:
            return tuple(float(v) for v in m.groups())
        m = re.search(r"([\d.]+)\s+g\b", da or "")
        if m:
            g = float(m.group(1))
            return (g, g, g)
    except Exception:
        pass
    return annot_color(annot)


# ---------------------------------------------------------------------------
# Page layout: spreads, columns, printed page numbers
# ---------------------------------------------------------------------------

def is_spread(page):
    if SPLIT_SPREADS == "auto":
        return page.rect.width > page.rect.height * 1.15
    return bool(SPLIT_SPREADS)


def column_of(page, x0, x1, spread):
    if not spread:
        return 0
    return 0 if (x0 + x1) / 2 < page.rect.x0 + page.rect.width / 2 else 1


class Column:
    """One book page: a whole PDF page, or one half of a two-page spread."""

    def __init__(self, page_index, col, n_cols, words):
        self.page_index = page_index
        self.col = col
        self.n_cols = n_cols
        self.words = words
        heights = [w[3] - w[1] for w in words if w[3] > w[1]]
        self.line_h = median(heights) if heights else 12.0
        self.top = min((w[1] for w in words), default=0.0)
        self.bottom = max((w[3] for w in words), default=0.0)
        self.number = self._printed_number() if DETECT_PRINTED_PAGE_NUMBERS else None

    def _printed_number(self):
        """A bare number in the running header or footer, e.g. '16'."""
        if not self.words:
            return None
        band = self.line_h * 1.6
        cands = [w for w in self.words
                 if (w[1] <= self.top + band or w[3] >= self.bottom - band)
                 and re.fullmatch(r"\d{1,4}", w[4])]
        if not cands:
            return None
        # Outer corner is the usual spot: left on a left page, right on a right
        cands.sort(key=lambda w: w[0], reverse=(self.n_cols == 2 and self.col == 1))
        return int(cands[0][4])


def build_columns(doc):
    """Return {(page_index, col): Column} in reading order, with printed page
    numbers filled in or inferred from neighbors."""
    columns = {}
    order = []
    for page in doc:
        spread = is_spread(page)
        n = 2 if spread else 1
        words = page.get_text("words", sort=True, flags=WORD_FLAGS)
        for col in range(n):
            col_words = [w for w in words if column_of(page, w[0], w[2], spread) == col]
            c = Column(page.number, col, n, col_words)
            c.pdf_label = _pdf_label(page)
            columns[(page.number, col)] = c
            order.append(c)

    # Fill gaps (chapter openings often have no header) and reject numbers
    # that don't fit the sequence (an OCR misread or a stray year).
    nums = [c.number for c in order]
    for i, c in enumerate(order):
        prev_ok = i > 0 and nums[i - 1] is not None
        nxt_ok = i + 1 < len(order) and nums[i + 1] is not None
        if c.number is not None and prev_ok and nxt_ok \
                and c.number != nums[i - 1] + 1 and nums[i + 1] == nums[i - 1] + 2:
            nums[i] = nums[i - 1] + 1
    for _ in range(2):
        for i in range(len(order)):
            if nums[i] is None:
                if i > 0 and nums[i - 1] is not None:
                    nums[i] = nums[i - 1] + 1
                elif i + 1 < len(order) and nums[i + 1] is not None:
                    nums[i] = nums[i + 1] - 1
    for c, n in zip(order, nums):
        if DETECT_PRINTED_PAGE_NUMBERS and n is not None and n > 0:
            c.label = str(n)
        elif c.n_cols == 2:
            c.label = f"{c.pdf_label}{'L' if c.col == 0 else 'R'}"
        else:
            c.label = c.pdf_label
    return columns, order


def _pdf_label(page):
    try:
        label = page.get_label()
        if label:
            return label
    except Exception:
        pass
    return str(page.number + 1)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def quads_of(annot):
    verts = annot.vertices or []
    quads = [fitz.Quad(verts[i:i + 4]) for i in range(0, len(verts) - 3, 4)]
    return quads or [annot.rect.quad]


def text_under_quads(words, quads):
    """Words covered by a highlight.

    Each word is assigned to the highlighted line it overlaps most, and kept if
    most of its width is inside. This tolerates slightly tilted scans, where
    the OCR word boxes drift up or down across a line and the last word of a
    line would otherwise be dropped."""
    rects = [q.rect for q in quads if not q.rect.is_empty]
    per_quad = [[] for _ in rects]
    for w in words:
        x0, y0, x1, y1 = w[:4]
        ww, wh = max(x1 - x0, 0.01), max(y1 - y0, 0.01)
        best, best_score = None, 0.0
        for qi, r in enumerate(rects):
            if (min(x1, r.x1) - max(x0, r.x0)) / ww < 0.5:
                continue
            score = (min(y1, r.y1) - max(y0, r.y0)) / wh
            if score > best_score:
                best, best_score = qi, score
        if best is not None and best_score >= 0.25:
            per_quad[best].append(w)

    lines = []
    for ws in per_quad:
        ws.sort(key=lambda w: (w[5], w[6], w[7]))
        current, key = [], None
        for w in ws:
            if key is not None and (w[5], w[6]) != key:
                lines.append(" ".join(current))
                current = []
            key = (w[5], w[6])
            current.append(w[4])
        if current:
            lines.append(" ".join(current))
    return join_lines(lines)


# Labels PDF apps write automatically (usually the name of the tool used).
# On their own they carry no information, so they don't count as note text.
PLACEHOLDER_LABELS = {
    "highlight", "underline", "strikeout", "strike out", "strikethrough",
    "squiggly", "note", "notes", "comment", "comments", "sticky note", "text",
    "text box", "textbox", "free text", "freetext", "typewriter", "callout",
    "ink", "pen", "pencil", "freehand", "drawing", "eraser", "square",
    "rectangle", "circle", "oval", "line", "arrow", "polygon", "polyline",
    "stamp", "caret", "annotation", "untitled",
}


def is_placeholder(text, annot=None):
    t = text.strip().strip(".:").lower()
    if not t or t in PLACEHOLDER_LABELS:
        return True
    return annot is not None and t == annot.type[1].lower()


def is_highlighter_stroke(annot):
    """Freehand highlighter strokes are stored as ink. Recognize them by their
    label or by being see-through, so they aren't reported as handwriting."""
    info = annot.info or {}
    label = f"{info.get('subject', '')} {info.get('title', '')}".lower()
    if "highlight" in label:
        return True
    try:
        return 0 <= annot.opacity < 0.9
    except Exception:
        return False


def annot_text(doc, page, annot):
    """Every place an annotation's real text can hide, in order. Returns ""
    when all that's there is an automatic label such as "Highlight"."""
    info = annot.info or {}
    candidates = [lambda: info.get("content", "")]
    # rich text (/RC) — some apps leave /Contents empty
    candidates.append(lambda: strip_xml(doc.xref_get_key(annot.xref, "RC")[1])
                      if doc.xref_get_key(annot.xref, "RC")[0] == "string" else "")
    # text drawn in the annotation's appearance
    candidates.append(lambda: annot.get_text())
    for get in candidates:
        try:
            text = clean_text(get() or "")
        except Exception:
            continue
        if text and not is_placeholder(text, annot):
            return text
    return ""


def flattened_notes(page, spread, covered):
    """Colored text that is part of the page itself rather than an
    annotation: typed margin notes that an app 'flattened' on export.
    Scanned/OCR text is black or invisible, so colored text stands out."""
    notes = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                txt = span["text"].strip()
                rgb = int_to_rgb(span.get("color", 0))
                if not txt or not is_colorful(rgb):
                    continue
                r = fitz.Rect(span["bbox"])
                if any(r.intersects(c) for c in covered):
                    continue
                notes.append({"rect": r, "text": txt, "rgb": rgb})
    # Group spans into notes: same column, near each other vertically.
    notes.sort(key=lambda n: (column_of(page, n["rect"].x0, n["rect"].x1, spread),
                              n["rect"].y0, n["rect"].x0))
    groups = []
    for n in notes:
        g = groups[-1] if groups else None
        if (g and column_of(page, g["rect"].x0, g["rect"].x1, spread)
                == column_of(page, n["rect"].x0, n["rect"].x1, spread)
                and n["rect"].y0 - g["rect"].y1 < n["rect"].height * 1.2
                and abs(n["rect"].x0 - g["rect"].x0) < page.rect.width * 0.15):
            sep = "" if g["text"].endswith("-") else " "
            g["text"] = (g["text"][:-1] if sep == "" else g["text"]) + sep + n["text"]
            g["rect"] |= n["rect"]
        else:
            groups.append(dict(n))
    return groups


def new_item(kind, category, text, rect, col, comment="", color=None):
    return {
        "kind": kind, "category": category, "text": text, "comment": comment,
        "y": rect.y0, "x": rect.x0, "y_end": rect.y1,
        "line_h": max(rect.height, 1.0),
        "col_key": col,
        "color_hex": rgb_to_hex(color) if color else "",
        "note_category": None,
    }


def extract(pdf_path, debug_lines=None):
    doc = fitz.open(pdf_path)
    columns, order = build_columns(doc)
    items = []

    for page in doc:
        spread = is_spread(page)
        words = [w for c in (columns[(page.number, i)] for i in range(2 if spread else 1))
                 for w in c.words]
        page_items = []
        covered = []  # areas of annotations, to avoid double-counting their text

        if debug_lines is not None:
            debug_lines.append(f"\n=== PDF page {page.number + 1} "
                               f"(book page(s) {', '.join(columns[(page.number, i)].label for i in range(2 if spread else 1))}) ===")

        for annot in page.annots() or []:
            atype = annot.type[0]
            rect = annot.rect
            color = annot_color(annot)
            if debug_lines is not None:
                debug_lines.append(
                    f"  annot type={annot.type[1]!r} color={rgb_to_hex(color) if color else None} "
                    f"rect={tuple(round(v) for v in rect)} text={annot_text(doc, page, annot)[:80]!r}")
            if atype in IGNORED_TYPES:
                continue
            covered.append(rect)

            if atype in MARKUP_TYPES:
                quads = quads_of(annot)
                text = text_under_quads(words, quads)
                category = classify_color(color) or UNCATEGORIZED
                comment = (annot.info or {}).get("content", "") or ""
                comment = clean_text(comment)
                if is_placeholder(comment, annot):
                    comment = ""
                if not text and not comment:
                    continue
                if not text:
                    text = "[no text found under this highlight — the page may lack an OCR text layer]"
                first = quads[0].rect
                span = fitz.Rect(first.x0, first.y0, first.x1, max(q.rect.y1 for q in quads))
                col = (page.number, column_of(page, first.x0, first.x1, spread))
                it = new_item("highlight", category, text, span, col, comment, color)
                it["line_h"] = max(quads[-1].rect.height, 1.0)
                page_items.append(it)
                continue

            # Everything else: sticky notes, text boxes, stamps, shapes with
            # a note attached, handwriting.
            text = annot_text(doc, page, annot)
            if atype == FREETEXT:
                color = note_color(doc, annot)
            col = (page.number, column_of(page, rect.x0, rect.x1, spread))
            if text:
                it = new_item("margin", MARGIN_NOTE_CATEGORY, text, rect, col, color=color)
            elif atype == INK and not is_highlighter_stroke(annot):
                it = new_item("ink", MARGIN_NOTE_CATEGORY,
                              "[handwritten mark or note — see PDF]", rect, col, color=color)
            else:
                continue
            # (sticky-note icons are yellow by default, so their color means nothing)
            if color and TAG_MARGIN_NOTES_BY_COLOR and atype != TEXT:
                it["note_category"] = classify_color(color, max_dist=0.35)
            page_items.append(it)

        for n in flattened_notes(page, spread, covered):
            if debug_lines is not None:
                debug_lines.append(f"  colored page text color={rgb_to_hex(n['rgb'])} "
                                   f"rect={tuple(round(v) for v in n['rect'])} text={n['text'][:80]!r}")
            col = (page.number, column_of(page, n["rect"].x0, n["rect"].x1, spread))
            it = new_item("margin", MARGIN_NOTE_CATEGORY, clean_text(n["text"]), n["rect"], col, color=n["rgb"])
            if TAG_MARGIN_NOTES_BY_COLOR:
                it["note_category"] = classify_color(n["rgb"], max_dist=0.35)
            page_items.append(it)

        # Reading order: left book page before right, then top to bottom.
        page_items.sort(key=lambda it: (it["col_key"][1], round(it["y"] / 4), it["x"]))
        for it in page_items:
            c = columns[it["col_key"]]
            it["page_index"] = page.number
            it["page"] = it["end_page"] = c.label
        items.extend(merge_within_column(page_items))

    doc.close()
    return merge_across_columns(items, columns, order)


SENTENCE_END = re.compile(r"[.!?:;\"'”’)\]]$")


def join_passages(a, b):
    if a["text"].endswith("-") and b["text"][:1].islower():
        a["text"] = a["text"][:-1] + b["text"]
    else:
        a["text"] = a["text"] + " " + b["text"]
    a["comment"] = " / ".join(c for c in (a["comment"], b["comment"]) if c)


def merge_within_column(page_items):
    """Join same-color highlights on consecutive lines of the same book page
    (the pen was lifted at a line break) when the first doesn't end a
    sentence."""
    out, prev = [], None
    for it in page_items:
        if (it["kind"] == "highlight" and prev is not None
                and it["col_key"] == prev["col_key"]
                and it["category"] == prev["category"]
                and not SENTENCE_END.search(prev["text"])
                and -2 <= it["y"] - prev["y_end"] <= prev["line_h"] * 1.2):
            join_passages(prev, it)
            prev["y_end"], prev["line_h"] = it["y_end"], it["line_h"]
            continue
        out.append(it)
        if it["kind"] == "highlight":
            prev = it
    return out


def merge_across_columns(items, columns, order):
    """Join a highlight that runs off the bottom of one book page with the one
    that picks up at the top of the NEXT book page. All must hold:
      - it is the last highlight on its book page and ends within the last
        couple of lines of text,
      - the next one is the first highlight on the very next book page and
        starts within the first couple of lines (below the running header),
      - same color, and the first part doesn't end a sentence.
    So a highlight on page 16 is never joined to one on page 19."""
    hl = [it for it in items if it["kind"] == "highlight"]
    first_in, last_in = {}, {}
    for it in hl:
        first_in.setdefault(it["col_key"], it)
        last_in[it["col_key"]] = it
    next_col = {}
    for a, b in zip(order, order[1:]):
        next_col[(a.page_index, a.col)] = (b.page_index, b.col)

    absorbed = set()
    for it in hl:
        if id(it) in absorbed:
            continue
        cur = it
        while last_in.get(cur["col_key"]) is cur:
            c = columns[cur["col_key"]]
            nk = next_col.get(cur["col_key"])
            nxt = first_in.get(nk) if nk else None
            if nxt is None:
                break
            n = columns[nk]
            ends_at_bottom = cur["y_end"] >= c.bottom - c.line_h * 3.5
            starts_at_top = nxt["y"] <= n.top + n.line_h * 3.5
            if (nxt["category"] != it["category"] or SENTENCE_END.search(it["text"])
                    or not ends_at_bottom or not starts_at_top):
                break
            join_passages(it, nxt)
            it["end_page"] = nxt["page"]
            absorbed.add(id(nxt))
            cur = nxt
    return [it for it in items if id(it) not in absorbed]


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------

def tag_for(category):
    if category in CATEGORIES:
        return CATEGORIES[category][1]
    if category == MARGIN_NOTE_CATEGORY:
        return MARGIN_NOTE_TAG
    return UNCATEGORIZED_TAG


def tags_of(it):
    tags = [tag_for(it["category"])]
    if it.get("note_category"):
        tags.append(tag_for(it["note_category"]))
    return " ".join(f"#{t}" for t in tags)


def page_ref(it):
    if it["end_page"] != it["page"]:
        return f"pp. {it['page']}–{it['end_page']}"
    return f"p. {it['page']}"


def frontmatter(title, source, view, items):
    present = {it["category"] for it in items} | {it["note_category"] for it in items if it.get("note_category")}
    used_tags = [tag_for(c) for c in list(CATEGORIES) + [MARGIN_NOTE_CATEGORY, UNCATEGORIZED] if c in present]
    lines = [
        "---",
        f'title: "{title.replace(chr(34), chr(39))}"',
        f'source: "{source}"',
        f"view: {view}",
        f"extracted: {date.today().isoformat()}",
        f"highlight_count: {sum(1 for it in items if it['kind'] == 'highlight')}",
        f"note_count: {sum(1 for it in items if it['kind'] != 'highlight')}",
        "tags:",
        f"  - {DOCUMENT_TAG}",
    ] + [f"  - {t}" for t in used_tags] + ["---"]
    return "\n".join(lines) + "\n"


def render_item(it, show_category):
    text = md_escape(it["text"])
    if it["kind"] == "highlight":
        label = f"**{it['category']}** · " if show_category else ""
        line = f"- {label}“{text}” ({page_ref(it)}) {tags_of(it)} ^{it['block_id']}"
    else:
        label = "**Margin note** · " if show_category else ""
        line = f"- {label}{text} ({page_ref(it)}) {tags_of(it)} ^{it['block_id']}"
    if it["category"] == UNCATEGORIZED:
        line += f"\n    - Unrecognized highlight color: `{it['color_hex']}`"
    if it.get("comment"):
        line += f"\n    - **Comment:** {md_escape(it['comment'])}"
    return line + "\n"


def assign_block_ids(items):
    counter = {}
    for it in items:
        key = re.sub(r"[^A-Za-z0-9]", "", it["page"]) or str(it["page_index"] + 1)
        counter[key] = counter.get(key, 0) + 1
        it["block_id"] = f"p{key}-{counter[key]}"


def export_to_markdown(items, original_filename, categorized_path, chronological_path):
    assign_block_ids(items)
    cat_note = os.path.splitext(os.path.basename(categorized_path))[0]
    chron_note = os.path.splitext(os.path.basename(chronological_path))[0]
    source = original_filename + ".pdf"

    md = frontmatter(original_filename, source, "categorized", items)
    md += f"\n# {original_filename} — Highlights by Category\n\n"
    md += f"Reading-order view: [[{chron_note}]]\n"
    order = list(CATEGORIES) + [MARGIN_NOTE_CATEGORY, UNCATEGORIZED]
    present = [c for c in order if any(it["category"] == c for it in items)]
    if present:
        md += "\n**Contents:** " + " · ".join(f"[[#{c}]]" for c in present) + "\n"
    for category in present:
        md += f"\n## {category}\n\n"
        for it in items:
            if it["category"] == category:
                md += render_item(it, show_category=False)
    with open(categorized_path, "w", encoding="utf-8") as f:
        f.write(md)

    md = frontmatter(original_filename, source, "chronological", items)
    md += f"\n# {original_filename} — Highlights in Reading Order\n\n"
    md += f"Category view: [[{cat_note}]]\n"
    current = None
    for it in items:
        if it["page"] != current:
            current = it["page"]
            md += f"\n## Page {current}\n\n"
        md += render_item(it, show_category=True)
    with open(chronological_path, "w", encoding="utf-8") as f:
        f.write(md)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    debug = "--debug" in sys.argv
    if not os.path.isdir(INPUT_FOLDER):
        raise SystemExit(f"Can't find the '{INPUT_FOLDER}' folder. Run this script from the folder that contains A and B.")
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    pdf_files = sorted(f for f in os.listdir(INPUT_FOLDER) if f.lower().endswith(".pdf"))
    if not pdf_files:
        raise SystemExit(f"No PDF files found in '{INPUT_FOLDER}'.")

    for pdf_file in pdf_files:
        original_filename = os.path.splitext(pdf_file)[0]
        print(f"Processing {pdf_file} ...")
        debug_lines = [] if debug else None
        items = extract(os.path.join(INPUT_FOLDER, pdf_file), debug_lines)

        categorized_path = os.path.join(OUTPUT_FOLDER, f"category_{original_filename}.md")
        chronological_path = os.path.join(OUTPUT_FOLDER, f"chronological_{original_filename}.md")
        export_to_markdown(items, original_filename, categorized_path, chronological_path)

        n_hl = sum(1 for it in items if it["kind"] == "highlight")
        print(f"  {n_hl} highlights, {len(items) - n_hl} margin notes")
        unknown = sorted({it["color_hex"] for it in items if it["category"] == UNCATEGORIZED})
        if unknown:
            print(f"  ! Unrecognized highlight colors (listed under 'Uncategorized'): {', '.join(unknown)}")
        print(f"  -> {categorized_path}\n  -> {chronological_path}")
        if debug:
            path = os.path.join(OUTPUT_FOLDER, f"debug_{original_filename}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(debug_lines) + "\n")
            print(f"  -> {path}")


if __name__ == "__main__":
    main()