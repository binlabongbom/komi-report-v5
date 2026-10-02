"""Shared metric labels and safe paper-size details; pages own their layout."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QSizePolicy

from ui.styles import text as text_styles


class MetricCard(QFrame):
    """Common display elements without report calculations or responsive policy."""

    def __init__(
        self,
        title: str,
        *,
        object_prefix: str,
        accent: str,
        transparent_value: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(f"{object_prefix}_card")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.lbl_title = QLabel(title)
        self.lbl_title.setObjectName(f"{object_prefix}_title")
        self.lbl_val = QLabel("—")
        self.lbl_val.setObjectName(f"{object_prefix}_value")
        self.lbl_val.setStyleSheet(
            text_styles.label(accent, background="transparent", border="0")
            if transparent_value else text_styles.label(accent)
        )
        self.lbl_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_detail = QLabel("")
        self.lbl_detail.setObjectName(f"{object_prefix}_detail")

    def _set_detail(self, detail: str) -> None:
        """Only paper-size pairs use rich text; all other content stays literal."""
        prefix, separator, suffix = detail.partition("  |  ")
        if prefix.startswith("A3 ") and separator and suffix.startswith("A4 "):
            self.lbl_detail.setTextFormat(Qt.TextFormat.RichText)
            self.lbl_detail.setText(text_styles.paper_size_detail(prefix[3:], suffix[3:]))
            return
        self.lbl_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_detail.setText(detail)
