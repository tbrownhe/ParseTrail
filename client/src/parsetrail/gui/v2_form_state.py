"""Presentation-only cues for required, unsaved and saved workflow choices."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)

REQUIRED_FILL = "#FFF0F0"
READY_FILL = "#EDF7EF"
ACTION_FILL = "#E8F2FF"

_DESCRIPTIONS = {
    "required": "Required choice still needed",
    "invalid": "Required choice needs correction",
    "ready": "Valid choice; not saved",
    "saved": "Saved choice",
    "optional": "Optional choice",
    "readonly": "Read-only source or retained choice",
    "blocked": "A prerequisite needs attention",
    "loading": "Loading saved state",
    "neutral": "",
}

_STYLE = """
QLineEdit[formState="required"], QComboBox[formState="required"],
QAbstractSpinBox[formState="required"], QCheckBox[formState="required"],
QLineEdit[formState="invalid"], QComboBox[formState="invalid"],
QAbstractSpinBox[formState="invalid"], QCheckBox[formState="invalid"] {
    background-color: #FFF0F0; color: #5B2020;
    border: 1px solid #B66868; border-radius: 3px;
}
QLineEdit[formState="ready"], QComboBox[formState="ready"],
QAbstractSpinBox[formState="ready"], QCheckBox[formState="ready"] {
    background-color: #EDF7EF; color: #173D25;
    border: 1px solid #5C8967; border-radius: 3px;
}
QLineEdit[formState]:focus, QComboBox[formState]:focus,
QAbstractSpinBox[formState]:focus, QCheckBox[formState]:focus {
    border: 2px solid #286BA8;
}
QComboBox QAbstractItemView {
    background-color: palette(base); color: palette(text);
    selection-background-color: palette(highlight); selection-color: palette(highlighted-text);
}
QLabel[formRole="status"] {
    padding: 4px 6px; border: 1px solid transparent; border-radius: 4px;
}
QLabel[formState="required"], QLabel[formState="invalid"] {
    background-color: #FFF0F0; color: #5B2020; border-color: #B66868;
}
QLabel[formState="ready"] {
    background-color: #EDF7EF; color: #173D25; border-color: #5C8967;
}
QLabel[formState="blocked"] {
    background-color: #FFF4D6; color: #553A0D; border-color: #B18C44;
}
QPushButton {
    background-color: palette(button); color: palette(button-text);
    border: 2px solid palette(mid); border-radius: 4px; padding: 3px 12px;
}
QPushButton[formState="ready"] {
    background-color: #E8F2FF; color: #173D63; border-color: #507DA7;
}
QPushButton[formState="ready"]:hover {
    background-color: #D8E9FC;
}
QPushButton[formState="ready"]:pressed {
    background-color: #C5DEF8;
}
QPushButton:focus {
    border: 2px solid #286BA8;
}
QPushButton:disabled, QPushButton[formState]:disabled {
    background-color: palette(button); color: palette(mid); border-color: palette(mid);
}
QGroupBox[formRole="decision"] {
    border: 1px solid #9EADB7; border-radius: 5px;
    margin-top: 7px; padding-top: 8px;
}
QGroupBox[formRole="decision"]::title {
    subcontrol-origin: margin; left: 8px; padding: 0 4px;
}
"""


def install_form_styles(root: QWidget) -> None:
    """Scope cues to this surface, preserving any existing presentation rules."""
    install_initial_focus(root)
    if root.property("parsetrailFormStyles"):
        return
    root.setProperty("parsetrailFormStyles", True)
    root.setStyleSheet(root.styleSheet() + "\n" + _STYLE)


class _InitialFocusPolicy(QObject):
    """Apply opening focus once, without interfering with subsequent refreshes."""

    def __init__(self, root: QWidget):
        super().__init__(root)
        self._opening = 0

    def eventFilter(self, watched, event):
        if (
            isinstance(watched, (QDialog, QMainWindow))
            and watched.isWindow()
            and type(watched).__module__.startswith("parsetrail.gui.v2_")
        ):
            if event.type() == QEvent.Show:
                self._opening += 1
                watched.setProperty("parsetrailOpeningFocus", True)
                self._queue_focus(watched)
            elif event.type() == QEvent.WindowActivate and watched.property("parsetrailOpeningFocus"):
                # Some platforms restore the previous child focus on activation,
                # after Show. Correct that once during this opening, never when
                # the user later switches back to an already open task.
                watched.setProperty("parsetrailOpeningFocus", False)
                self._queue_focus(watched)
            elif event.type() in (QEvent.Hide, QEvent.WindowDeactivate):
                # Discard work from this opening before a hide/reopen or a later
                # activation can make an old queued callback relevant again.
                self._opening += 1
                watched.setProperty("parsetrailOpeningFocus", False)
        return False

    def _queue_focus(self, root):
        opening = self._opening
        QTimer.singleShot(0, root, lambda: self._focus(root) if opening == self._opening else None)

    @staticmethod
    def _focus(dialog):
        if not dialog.isVisible() or not dialog.isWindow():
            return
        preferred_name = dialog.property("initialFocusObject")
        preferred = dialog.findChild(QWidget, preferred_name) if preferred_name else None
        if preferred is not None and preferred.isVisibleTo(dialog) and preferred.isEnabled():
            preferred.setFocus(Qt.OtherFocusReason)
            return
        candidate = dialog.nextInFocusChain()
        while candidate is not dialog:
            # Editable combos own their line edit; never focus that implementation
            # child independently or bypass a disabled/readonly parent input.
            parent = candidate.parentWidget()
            input_widget = isinstance(candidate, (QComboBox, QLineEdit, QPlainTextEdit, QTextEdit))
            editable = not isinstance(candidate, (QLineEdit, QPlainTextEdit, QTextEdit)) or not candidate.isReadOnly()
            if (
                input_widget
                and editable
                and not isinstance(parent, QComboBox)
                and candidate.window() is dialog
                and candidate.isVisibleTo(dialog)
                and candidate.isEnabled()
                and candidate.focusPolicy() != Qt.NoFocus
            ):
                candidate.setFocus(Qt.OtherFocusReason)
                return
            candidate = candidate.nextInFocusChain()


def install_initial_focus(root: QWidget) -> None:
    """Give this V2 task window a first input without filtering unrelated objects."""
    if not hasattr(root, "_parsetrail_initial_focus"):
        policy = _InitialFocusPolicy(root)
        root._parsetrail_initial_focus = policy
        root.installEventFilter(policy)


def set_field_state(widget: QWidget, state: str, detail: str = "") -> None:
    """Describe presentation state; never infer accounting eligibility or save."""
    if state not in _DESCRIPTIONS:
        raise ValueError(f"Unknown form state: {state}")
    if widget.property("formBaseDescription") is None:
        widget.setProperty("formBaseDescription", widget.accessibleDescription())
    base = widget.property("formBaseDescription") or ""
    state_description = (
        "Action available; activate to review or save these choices"
        if isinstance(widget, QPushButton) and state == "ready"
        else _DESCRIPTIONS[state]
    )
    description = ". ".join(part for part in (base, state_description, detail) if part)
    widget.setAccessibleDescription(description)
    if widget.property("formState") == state:
        return
    widget.setProperty("formState", state)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.updateGeometry()
    widget.update()


def set_status(label: QLabel, state: str, text: str) -> None:
    label.setProperty("formRole", "status")
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setText(text)
    set_field_state(label, state)
