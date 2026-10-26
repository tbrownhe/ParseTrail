"""Local guidance and truthful build identity for the fresh workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from parsetrail.version import __developer__, __version__


def show_workspace_help(parent=None) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Getting started with your 2.0 workspace")
    dialog.resize(680, 570)
    layout = QVBoxLayout(dialog)
    steps = (
        (
            "1. Keep your profiles separate",
            "This fresh workspace is independent of your 1.x history. Add the financial accounts and categories "
            "you want to track here. The active profile path is always shown in the window.",
        ),
        (
            "2. Install a signed catalog and import originals",
            "Choose Install signed catalog, then import a CSV/PDF file or a folder. Ordinary imports and "
            "analysis stay on your device. Original files stay where you selected them; the profile retains "
            "a copy of every successfully imported original.",
        ),
        (
            "3. Confirm accounts and repeated evidence",
            "Select a saved source and review its account bindings. Use Review repeated rows for possible "
            "overlap. Equal amounts are suggestions to inspect, not proof of a duplicate or a transfer.",
        ),
        (
            "4. Review before posting",
            "Review supported cash activity, card purchases and transfers explicitly. Importing and account "
            "binding do not post money. Transfers and card repayments do not create a second expense. "
            "Unsupported activity remains pending.",
        ),
        (
            "5. Establish openings and inspect reports",
            "Use Review openings for source-backed opening positions. Statement coverage separates source "
            "facts, live checks and saved reconciliations. Reviewed reports show spending, income, budgets "
            "and dated account history. Unknown openings are not zero; pending activity and coverage limits "
            "still matter when balances agree.",
        ),
        (
            "6. Back up and recover",
            "Profile > Back up current profile creates a verified copy. Restore backup as new profile "
            "preserves the existing profile. Save selected source original recovers an embedded document. "
            "Profiles, backups and recovered originals contain financial data and are not encrypted by "
            "ParseTrail. The signed catalog cache and global preferences are separate from profile backups.",
        ),
    )
    for title, body in steps:
        heading = QLabel(title)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        text = QLabel(body)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(text)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.rejected.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.exec()


def show_workspace_about(parent=None) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("About this workspace")
    layout = QVBoxLayout(dialog)
    text = QLabel(
        "ParseTrail 2.0 development workspace\n\n"
        f"Application build version: {__version__}\n"
        f"Developer: {__developer__}\n\n"
        "This workspace is under development. Its build version is unchanged during the 2.0 pilot; "
        "this is not a released 2.0 application.\n\n"
        "Ordinary financial data and analysis stay local. Your 1.x application and history remain independent."
    )
    text.setWordWrap(True)
    text.setMinimumWidth(440)
    text.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(text)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.rejected.connect(dialog.accept)
    layout.addWidget(buttons)
    dialog.exec()
