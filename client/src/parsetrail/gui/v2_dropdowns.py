"""Whole-control dropdown opening, scoped to each V2 widget owner."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QComboBox, QLineEdit, QWidget
from shiboken6 import isValid


class _DropdownOpeningPolicy(QObject):
    """Observe only this owner's descendants; retain no widget graph in Python."""

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self._owner = weakref.ref(owner)
        self._watched = weakref.WeakSet()
        self._scan_timer = QTimer(self)
        self._scan_timer.setSingleShot(True)
        self._scan_timer.timeout.connect(self._scan)
        owner.installEventFilter(self)
        self._scan_timer.start(0)

    def _scan(self):
        owner = self._owner()
        if owner is None or not isValid(owner):
            return
        for widget in (owner, *owner.findChildren(QWidget)):
            if widget not in self._watched:
                widget.installEventFilter(self)
                self._watched.add(widget)
            if isinstance(widget, QComboBox):
                current = getattr(widget, "_parsetrail_dropdown_owner", lambda: None)()
                if current is None or not isValid(current) or not current._within_owner(widget):
                    widget._parsetrail_dropdown_owner = weakref.ref(self)

    def _within_owner(self, widget):
        owner = self._owner()
        return owner is not None and isValid(owner) and (widget is owner or owner.isAncestorOf(widget))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.ChildAdded:
            if not self._scan_timer.isActive():
                self._scan_timer.start(0)
            return False
        if event.type() != QEvent.MouseButtonPress or event.button() != Qt.LeftButton:
            return False
        combo = (
            watched
            if isinstance(watched, QComboBox)
            else watched.parentWidget()
            if isinstance(watched, QLineEdit)
            else None
        )
        if (
            not isinstance(combo, QComboBox)
            or getattr(combo, "_parsetrail_dropdown_owner", lambda: None)() is not self
            or not self._within_owner(combo)
            or not combo.isEnabled()
            or not combo.isVisible()
            or combo.view().isVisible()
        ):
            return False
        if watched is combo:
            combo.setFocus(Qt.MouseFocusReason)
            combo.showPopup()
            return True
        # The editable text keeps its native cursor/selection handling. Opening
        # after that press also preserves typing and completion behavior.
        combo_ref = weakref.ref(combo)
        policy_ref = weakref.ref(self)

        def open_after_press():
            current = combo_ref()
            policy = policy_ref()
            if (
                current is not None
                and isValid(current)
                and policy is not None
                and isValid(policy)
                and getattr(current, "_parsetrail_dropdown_owner", lambda: None)() is policy
                and policy._within_owner(current)
                and current.isEnabled()
                and current.isVisible()
                and not current.view().isVisible()
            ):
                current.showPopup()

        QTimer.singleShot(0, combo, open_after_press)
        return False


def install_dropdown_opening(owner: QWidget) -> None:
    """Include later-created combos without an application-wide event filter."""
    if not hasattr(owner, "_parsetrail_dropdown_opening"):
        owner._parsetrail_dropdown_opening = _DropdownOpeningPolicy(owner)
