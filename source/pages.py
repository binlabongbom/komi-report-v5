"""Compatibility imports for pages; new code imports the owning ui module."""

from ui.parser_editor import (
    _open_check_parser as _open_check_parser,
)
from ui.pages.overview import (
    _OverviewMetricCard as _OverviewMetricCard,
    _OverviewTonerBar as _OverviewTonerBar,
    PageOverviewV2 as PageOverviewV2,
    PageOverview as PageOverview,
)
from ui.pages.imports import (
    _NoParserMatchDialog as _NoParserMatchDialog,
    PreviewDialog as PreviewDialog,
    PageImport as PageImport,
)
from ui.reports.legacy import (
    _FlowLayout as _FlowLayout,
    _load_pyqtgraph as _load_pyqtgraph,
    PageHistory as PageHistory,
)
from ui.settings.legacy import (
    PageSettings as PageSettings,
)
from ui.pages.manual import (
    _ManualDocumentImage as _ManualDocumentImage,
    PageManual as PageManual,
)
