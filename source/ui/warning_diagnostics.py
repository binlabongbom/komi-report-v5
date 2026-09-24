"""Give every warning/error message box a complete, explicit copy action."""
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton

from i18n import tr
from services.support_diagnostics import CATALOG, diagnose, safe_text, warning_report


class WarningDiagnostics(QObject):
    def eventFilter(self, watched, event):
        if (isinstance(watched, QMessageBox) and event.type() == QEvent.Type.Show
                and watched.icon() in {QMessageBox.Icon.Warning, QMessageBox.Icon.Critical}
                and not watched.property('komiDiagnosticReady')):
            watched.setProperty('komiDiagnosticReady', True)
            text = safe_text(watched.text())
            heading, marker, report = text.partition('KOMI Diagnostic v1\n')
            if marker:
                report = marker + report
                diagnostic = diagnose(report)
                watched.setText(heading.strip() or diagnostic.summary)
                watched.setInformativeText(f'Error Code: {diagnostic.error_code}\n{diagnostic.summary}\n\n{CATALOG[diagnostic.code][1]}\n\n{diagnostic.action}')
            else:
                # Validation/business warnings keep their exact instruction.
                # They are not automatically labelled as network/auth failures.
                report = warning_report(watched.windowTitle(), text, advice=watched.informativeText(), details=watched.detailedText())
                watched.setText(text)
                watched.setInformativeText(f'Error Code: {diagnose(report).error_code}\n' + watched.informativeText())
            watched.setTextFormat(Qt.TextFormat.PlainText)
            watched.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            watched.setDetailedText(report)
            watched.setProperty('komiDiagnosticText', report)
            # QMessageBox closes even for custom ActionRole buttons. Keep Copy
            # outside its button box so the user can copy without dismissing it.
            button = QPushButton(tr('คัดลอกรายละเอียด', 'Copy details'), watched)
            button.setAutoDefault(False)
            layout = watched.layout()
            layout.addWidget(button, layout.rowCount(), 0, 1, layout.columnCount())
            button.setObjectName('copy_warning_diagnostic')
            button.clicked.connect(lambda _checked=False, bundle=report: QApplication.clipboard().setText(bundle))
        return False


def install_warning_diagnostics(app):
    if app is not None and not hasattr(app, '_komi_warning_diagnostics'):
        app._komi_warning_diagnostics = WarningDiagnostics(app)
        app.installEventFilter(app._komi_warning_diagnostics)
