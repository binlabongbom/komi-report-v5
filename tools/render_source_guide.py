"""Render the maintained source guide with Qt's Thai text/image layout.

This creates documentation only, never application/installer artifacts. Run
with the project's Qt environment and QT_QPA_PLATFORM=offscreen.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "source" / "tests"))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QTextDocument, QPdfWriter, QPageSize, QFont, QTextCursor, QImage
from PyQt6.QtCore import QUrl, QMarginsF, QSizeF
from qt_render_environment import configure_offscreen_fonts


def render():
    app = QApplication.instance() or QApplication([])
    configure_offscreen_fonts(app)
    target = ROOT / "docs/customer-guide/KOMI_Report_5.2.12_Source_Guide.pdf"
    writer = QPdfWriter(str(target))
    writer.setTitle("KOMI Report 5.2.12 คู่มือ source ระหว่างพัฒนา")
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(18, 18, 18, 18))
    writer.setResolution(144)
    doc = QTextDocument()
    doc.documentLayout().setPaintDevice(writer)
    doc.setDefaultFont(QFont("Tahoma", 11))
    doc.setDocumentMargin(0)
    doc.setPageSize(QSizeF(writer.width(), writer.height()))
    content = (ROOT / "docs/CUSTOMER_GUIDE_V5_2_12_DRAFT.md").read_text(encoding="utf-8")
    content = content.replace("→", ">")
    doc.setMarkdown(content)
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isImageFormat():
                fmt = frag.charFormat().toImageFormat()
                path = ROOT / "docs" / fmt.name()
                img = QImage(str(path))
                if img.isNull():
                    raise ValueError(f"Missing guide image: {path}")
                url = QUrl.fromLocalFile(str(path))
                doc.addResource(QTextDocument.ResourceType.ImageResource, url, img)
                fmt.setName(url.toString())
                # Qt print() scales document coordinates from logical 96 dpi;
                # image format sizes must use the same logical coordinates.
                width = writer.width() * 96 / writer.resolution() * .97
                fmt.setWidth(width)
                fmt.setHeight(width * img.height() / img.width())
                cursor = QTextCursor(doc)
                cursor.setPosition(frag.position())
                cursor.setPosition(frag.position() + frag.length(), QTextCursor.MoveMode.KeepAnchor)
                cursor.setCharFormat(fmt)
            it += 1
        block = block.next()
    doc.print(writer)
    print(target)


if __name__ == "__main__":
    render()
