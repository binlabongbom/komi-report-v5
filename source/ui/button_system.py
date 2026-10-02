"""Application-wide button geometry and motion rules."""

from __future__ import annotations

import re

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QVariantAnimation
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QPushButton, QSizePolicy

from ui.styles.tokens import (
    BUTTON_HEIGHT,
    BUTTON_ICON_SIZE,
    BUTTON_LARGE_HEIGHT,
    BUTTON_LINK_HEIGHT,
    BUTTON_MOTION_MS,
    BUTTON_RADIUS,
    NAV_BUTTON_HEIGHT,
)


class ButtonSystem(QObject):
    """Normalize every QPushButton and provide subtle, uniform motion."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        app.installEventFilter(self)
        for widget in app.allWidgets():
            if isinstance(widget, QPushButton):
                self.polish(widget)

    @staticmethod
    def _role(button: QPushButton) -> str:
        explicit = str(button.property("uiButtonRole") or "")
        if explicit:
            return explicit
        if button.objectName() == "nav":
            return "nav"
        style = button.styleSheet().replace(" ", "").lower()
        if "text-decoration:underline" in style or (
            "background:transparent" in style and "border:none" in style
        ):
            return "link"
        label = button.text().strip()
        # A native QMessageBox briefly reports a very small current width
        # before macOS finishes laying out its textual OK/Yes/No button.  Only
        # an explicit maximum-width constraint identifies a real icon button;
        # using the temporary current width turns "OK" into a clipped square.
        if len(label) <= 2 and button.maximumWidth() <= 50:
            return "icon"
        if button.minimumHeight() >= 46:
            return "large"
        return "standard"

    def polish(self, button: QPushButton) -> None:
        if button.property("uiButtonPolished"):
            return
        button.setProperty("uiButtonPolished", True)
        role = self._role(button)
        button.setProperty("uiButtonResolvedRole", role)
        policy = button.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        button.setSizePolicy(policy)

        if role == "nav":
            button.setFixedHeight(NAV_BUTTON_HEIGHT)
        elif role == "link":
            button.setFixedHeight(BUTTON_LINK_HEIGHT)
        elif role == "icon":
            button.setFixedSize(BUTTON_ICON_SIZE, BUTTON_ICON_SIZE)
        elif role == "compact-icon":
            button.setFixedSize(24, 24)
        elif role == "compact":
            button.setFixedHeight(28)
        elif role == "large":
            button.setFixedHeight(BUTTON_LARGE_HEIGHT)
        else:
            button.setFixedHeight(BUTTON_HEIGHT)

        if role not in {"nav", "link"}:
            # Never create a local stylesheet on helper buttons: in Qt that
            # can mask application-level primary/disabled colors.  Only
            # normalize legacy buttons that already own an inline stylesheet.
            existing_style = button.styleSheet()
            if existing_style:
                button.setStyleSheet(
                    re.sub(
                        r"border-radius\s*:\s*\d+(?:\.\d+)?px",
                        f"border-radius: {BUTTON_RADIUS}px",
                        existing_style,
                    )
                )
            effect = QGraphicsDropShadowEffect(button)
            effect.setBlurRadius(8.0)
            effect.setOffset(0.0, 1.0)
            effect.setColor(QColor(11, 111, 175, 0))
            button.setGraphicsEffect(effect)
            button._komi_shadow_level = 0.0
            button._komi_shadow_effect = effect
            button._komi_shadow_animation = None

    def _animate(self, button: QPushButton, target: float) -> None:
        effect = getattr(button, "_komi_shadow_effect", None)
        if effect is None or not button.isEnabled():
            return
        previous = getattr(button, "_komi_shadow_animation", None)
        if previous is not None:
            previous.stop()
        start = float(getattr(button, "_komi_shadow_level", 0.0))
        animation = QVariantAnimation(button)
        animation.setStartValue(start)
        animation.setEndValue(max(0.0, min(1.0, target)))
        animation.setDuration(BUTTON_MOTION_MS)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def update(value) -> None:
            level = float(value)
            button._komi_shadow_level = level
            effect.setBlurRadius(8.0 + 6.0 * level)
            effect.setOffset(0.0, 1.0 + 2.0 * level)
            effect.setColor(QColor(11, 111, 175, round(62 * level)))

        animation.valueChanged.connect(update)
        button._komi_shadow_animation = animation
        animation.start()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QPushButton):
            event_type = event.type()
            if event_type == QEvent.Type.Show:
                self.polish(watched)
            elif event_type in (QEvent.Type.Enter, QEvent.Type.FocusIn):
                self._animate(watched, 1.0)
            elif event_type in (QEvent.Type.Leave, QEvent.Type.FocusOut):
                self._animate(watched, 0.0)
            elif event_type == QEvent.Type.MouseButtonPress:
                self._animate(watched, 0.28)
            elif event_type == QEvent.Type.MouseButtonRelease:
                self._animate(watched, 1.0 if watched.underMouse() else 0.0)
        return super().eventFilter(watched, event)


def install_button_system(app: QApplication | None = None) -> ButtonSystem | None:
    """Install once per QApplication and return the shared controller."""
    app = app or QApplication.instance()
    if app is None:
        return None
    from ui.warning_diagnostics import install_warning_diagnostics
    install_warning_diagnostics(app)
    existing = getattr(app, "_komi_button_system", None)
    if existing is not None:
        return existing
    controller = ButtonSystem(app)
    app._komi_button_system = controller
    return controller
