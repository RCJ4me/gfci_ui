# -*- coding: utf-8 -*-
"""Render Markdown reports and export them as PDF files with Qt."""

from __future__ import annotations

import html
import os
import re
import tempfile
from pathlib import Path

import markdown
from PyQt6.QtCore import QMarginsF, QRectF, QSizeF, QUrl
from PyQt6.QtGui import (
    QFont,
    QImageReader,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextDocument,
)

PDF_PAGE_MARGIN_MM = 12.0
PDF_RESOLUTION = 96
PDF_IMAGE_WIDTH_RATIO = 0.72
PDF_IMAGE_HEIGHT_RATIO = 0.38

_IMAGE_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_PAGE_BREAK_TAG = re.compile(
    r"""<div\b[^>]*\bclass\s*=\s*["'][^"']*\bpdf-page-break\b"""
    r"""[^"']*["'][^>]*>\s*</div>""",
    re.IGNORECASE,
)
_EMPTY_PARAGRAPH = re.compile(r"<p>\s*</p>", re.IGNORECASE)
_HTML_DOCUMENT = re.compile(
    r"(?is)^(?P<prefix>.*?<body>)(?P<body>.*)(?P<suffix></body>.*)$"
)


REPORT_STYLESHEET = """
body {
    color: #20242a;
    font-family: "Helvetica Neue", Arial, sans-serif;
    font-size: 9pt;
    line-height: 1.35;
}
h1 {
    color: #17365d;
    font-size: 18pt;
    margin: 0 0 12pt 0;
}
h2 {
    color: #17365d;
    font-size: 14pt;
    margin: 16pt 0 8pt 0;
}
h3 {
    color: #244f7a;
    font-size: 11pt;
    margin: 12pt 0 6pt 0;
}
p {
    margin: 2pt 0 7pt 0;
}
ul {
    margin: 3pt 0 8pt 18pt;
}
li {
    margin: 1pt 0;
}
hr {
    color: #c7d1dc;
    margin: 10pt 0;
}
table {
    border-collapse: collapse;
    margin: 7pt 0 12pt 0;
    width: 100%;
}
th, td {
    border: 1px solid #8f9baa;
    padding: 5pt 7pt;
    vertical-align: top;
}
th {
    background-color: #e8eef7;
    font-weight: 600;
    padding-left: 8pt;
    padding-right: 8pt;
}
tr {
    page-break-inside: avoid;
}
img {
    display: block;
    margin: 8pt auto 14pt auto;
    page-break-inside: avoid;
}
code {
    font-family: Menlo, Consolas, monospace;
    font-size: 8pt;
}
"""


class ReportExportError(RuntimeError):
    """Raised when a Markdown report cannot be written as PDF."""


def markdown_to_html(markdown_text: str) -> str:
    """Convert Markdown content into an HTML fragment with table support."""
    return markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code"],
        output_format="html5",
    )


def _image_path_from_source(
    source: str,
    base_dir: Path | None,
) -> Path | None:
    decoded_source = html.unescape(source)
    url = QUrl(decoded_source)
    if url.isLocalFile():
        return Path(url.toLocalFile())
    if url.scheme():
        return None

    image_path = Path(decoded_source)
    if not image_path.is_absolute() and base_dir is not None:
        image_path = base_dir / image_path
    return image_path


def _scaled_image_dimensions(
    width: int,
    height: int,
    max_width_px: int,
    max_height_px: int,
) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise ValueError("Image dimensions must be positive.")
    scale = min(max_width_px / width, max_height_px / height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _size_local_images(
    body: str,
    base_dir: Path | None,
    max_width_px: int,
    max_height_px: int,
) -> str:
    """Apply explicit aspect-ratio-preserving dimensions to local images."""
    image_tag = re.compile(r"<img\b(?P<attrs>[^>]*)>", re.IGNORECASE)
    source_attr = re.compile(
        r"""\bsrc\s*=\s*(?P<quote>["'])(?P<src>.*?)(?P=quote)""",
        re.IGNORECASE,
    )
    dimension_attr = re.compile(
        r"""\s+(?:width|height)\s*=\s*(?P<quote>["']).*?(?P=quote)""",
        re.IGNORECASE,
    )

    def resize_tag(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        source_match = source_attr.search(attrs)
        if source_match is None:
            return match.group(0)

        image_path = _image_path_from_source(
            source_match.group("src"),
            base_dir,
        )
        if image_path is None or not image_path.is_file():
            return dimension_attr.sub("", match.group(0))

        source_size = QImageReader(str(image_path)).size()
        if not source_size.isValid():
            return dimension_attr.sub("", match.group(0))

        width, height = _scaled_image_dimensions(
            source_size.width(),
            source_size.height(),
            max_width_px,
            max_height_px,
        )
        clean_attrs = dimension_attr.sub("", attrs).rstrip()
        return f'<img{clean_attrs} width="{width}" height="{height}">'

    return image_tag.sub(resize_tag, body)


def render_report_html(
    markdown_text: str,
    base_dir: str | Path | None = None,
    max_image_width_px: int | None = None,
    max_image_height_px: int | None = None,
    *,
    include_images: bool = True,
    include_page_breaks: bool = True,
) -> str:
    """Render a complete, styled HTML document for preview and PDF output."""
    body = markdown_to_html(markdown_text)
    if not include_images:
        body = _EMPTY_PARAGRAPH.sub("", _IMAGE_TAG.sub("", body))
    if not include_page_breaks:
        body = _PAGE_BREAK_TAG.sub("", body)
    resolved_base_dir = Path(base_dir).resolve() if base_dir is not None else None
    if (
        include_images
        and resolved_base_dir is not None
        and max_image_width_px is not None
        and max_image_height_px is not None
    ):
        body = _size_local_images(
            body,
            resolved_base_dir,
            max_image_width_px,
            max_image_height_px,
        )
    base_tag = ""
    if resolved_base_dir is not None:
        base_url = resolved_base_dir.as_uri()
        base_tag = f'<base href="{html.escape(base_url)}/">'
    return (
        "<!DOCTYPE html>"
        f"<html><head><meta charset=\"utf-8\">{base_tag}"
        f"<style>{REPORT_STYLESHEET}</style>"
        f"</head><body>{body}</body></html>"
    )


def pdf_path_for_markdown(markdown_path: str | Path) -> Path:
    """Return the PDF path that shares the Markdown file's directory and stem."""
    return Path(markdown_path).with_suffix(".pdf")


def pdf_path_for_csv(
    markdown_path: str | Path,
    csv_name: str | Path,
) -> Path:
    """Return the user-facing PDF path for an imported CSV report."""
    source = Path(markdown_path)
    csv_stem = Path(csv_name).stem
    if not csv_stem:
        raise ValueError(f"CSV name has no file stem: {csv_name}")
    return source.with_name(f"TD GFCI Report {csv_stem}.pdf")


def pdf_image_size_limits() -> tuple[int, int]:
    """Return safe image bounds inside the configured A4 content area."""
    page_size = QPageSize(QPageSize.PageSizeId.A4).size(
        QPageSize.Unit.Millimeter
    )
    content_width_mm = page_size.width() - 2 * PDF_PAGE_MARGIN_MM
    content_height_mm = page_size.height() - 2 * PDF_PAGE_MARGIN_MM
    width_px = round(content_width_mm / 25.4 * PDF_RESOLUTION)
    height_px = round(content_height_mm / 25.4 * PDF_RESOLUTION)
    return (
        max(1, round(width_px * PDF_IMAGE_WIDTH_RATIO)),
        max(1, round(height_px * PDF_IMAGE_HEIGHT_RATIO)),
    )


def _report_title(markdown_text: str, markdown_path: Path) -> str:
    match = re.search(r"(?m)^#\s+(.+?)\s*$", markdown_text)
    if match is None:
        return markdown_path.stem
    title = re.sub(r"[*_`]", "", match.group(1)).strip()
    return title or markdown_path.stem


def _split_html_pages(html_text: str) -> list[str]:
    """Create one complete HTML document for each explicit report page."""
    match = _HTML_DOCUMENT.match(html_text)
    if match is None:
        return [html_text]

    prefix = match.group("prefix")
    suffix = match.group("suffix")
    sections = [
        section.strip()
        for section in _PAGE_BREAK_TAG.split(match.group("body"))
        if section.strip()
    ]
    return [f"{prefix}{section}{suffix}" for section in sections] or [html_text]


def _write_pdf(
    html_text: str,
    title: str,
    output_path: Path,
    base_dir: Path | None = None,
) -> None:
    writer = QPdfWriter(str(output_path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    if not writer.setPageMargins(
        QMarginsF(
            PDF_PAGE_MARGIN_MM,
            PDF_PAGE_MARGIN_MM,
            PDF_PAGE_MARGIN_MM,
            PDF_PAGE_MARGIN_MM,
        ),
        QPageLayout.Unit.Millimeter,
    ):
        raise ReportExportError("Qt rejected the requested PDF page margins.")
    # QTextDocument layouts in 96-DPI logical pixels. A 96-DPI writer keeps
    # fonts at their intended point size while PDF page geometry stays physical.
    writer.setResolution(PDF_RESOLUTION)
    writer.setTitle(title)
    writer.setCreator("Torch Dragon")

    paint_rect = writer.pageLayout().paintRectPixels(writer.resolution())
    page_size = QSizeF(paint_rect.width(), paint_rect.height())

    painter = QPainter(writer)
    if not painter.isActive():
        raise ReportExportError("Qt could not start PDF painting.")
    try:
        first_page = True
        for page_html in _split_html_pages(html_text):
            document = QTextDocument()
            document.setDocumentMargin(0.0)
            document.setDefaultFont(QFont("Helvetica Neue", 9))
            document.setMetaInformation(
                QTextDocument.MetaInformation.DocumentTitle,
                title,
            )
            if base_dir is not None:
                document.setBaseUrl(
                    QUrl.fromLocalFile(f"{base_dir.resolve()}{os.sep}")
                )
            document.documentLayout().setPaintDevice(writer)
            document.setPageSize(page_size)
            document.setHtml(page_html)

            for page_index in range(document.pageCount()):
                if not first_page:
                    writer.newPage()
                first_page = False
                page_top = page_index * page_size.height()
                painter.save()
                painter.translate(0.0, -page_top)
                painter.setClipRect(
                    QRectF(
                        0.0,
                        page_top,
                        page_size.width(),
                        page_size.height(),
                    )
                )
                painter_rect = QRectF(
                    0.0,
                    page_top,
                    page_size.width(),
                    page_size.height(),
                )
                document.drawContents(painter, painter_rect)
                painter.restore()
    finally:
        painter.end()


def export_markdown_to_pdf(
    markdown_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    """Export the current contents of a Markdown report to an A4 PDF file."""
    source = Path(markdown_path)
    if not source.is_file():
        raise FileNotFoundError(f"Markdown report not found: {source}")

    target = (
        Path(output_path)
        if output_path is not None
        else pdf_path_for_markdown(source)
    )
    if not target.parent.is_dir():
        raise FileNotFoundError(
            f"PDF output directory not found: {target.parent}"
        )

    markdown_text = source.read_text(encoding="utf-8")
    image_width, image_height = pdf_image_size_limits()
    html_text = render_report_html(
        markdown_text,
        source.parent,
        max_image_width_px=image_width,
        max_image_height_px=image_height,
    )
    title = _report_title(markdown_text, source)

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.stem}-",
            suffix=".pdf",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)

        _write_pdf(html_text, title, temporary, source.parent)
        pdf_bytes = temporary.read_bytes()
        if not pdf_bytes.startswith(b"%PDF-") or not pdf_bytes:
            raise ReportExportError(
                f"Qt produced an invalid PDF for {source}."
            )
        os.replace(temporary, target)
    except (OSError, RuntimeError) as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise ReportExportError(
            f"Could not export Markdown report {source} to {target}: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return target
