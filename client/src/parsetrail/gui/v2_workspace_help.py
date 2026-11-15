"""Local guidance and truthful build identity for the fresh workspace."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QScrollArea, QVBoxLayout, QWidget

from parsetrail.version import __developer__, __version__


def show_workspace_help(parent=None) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Getting started with your 2.0 workspace")
    dialog.resize(680, 570)
    layout = QVBoxLayout(dialog)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    guide = QVBoxLayout(content)
    scroll.setWidget(content)
    layout.addWidget(scroll)
    steps = (
        (
            "1. Import a statement",
            "In Documents, choose Import statement. If formats are missing, first use Install statement formats. "
            "Choose an existing account or create a new one, then check the recognized dates and amounts. "
            "Import and assign saves the original, accounts and assignments together. It posts no transactions. "
            "Original files stay where you selected them. Changing an imported format is not supported yet, "
            "so cancel if the preview is wrong.",
        ),
        (
            "2. Review the transactions",
            "Open the statement in Review. Source evidence and Open original let you check what was imported. "
            "Choose a transaction type and category. Add category opens a separate creation task. Budget opens "
            "category and budget management. Use Ctrl-click or Shift to select several rows. Transfers, repayments "
            "and loan principal have separate review routes because they are not additional expenses.",
        ),
        (
            "3. Build a review set, then confirm",
            "Enter a shared reason in Review set. It applies to every staged row, including rows hidden by filters. "
            "Stage selected captures your choices and applies that reason to the whole set. Selecting another "
            "row does not change the reason; later unstaged edits do not change the captured reason. "
            "Review staged shows the exact effects before you confirm and post. Cancel keeps your choices. "
            "Review set options removes selected proposals or clears the set without changing saved entries.",
        ),
        (
            "4. See the monthly budget impact",
            "Open Budget, choose a month and select a category to edit its budget. The table shows budget, "
            "reviewed spending and remaining. Remaining is budget minus reviewed spending, not an account balance. "
            "View spending from a statement also selects its month for Budget. Multi-month statements show "
            "which month is selected. Ordinary navigation retains your dates and month. All profile accounts "
            "are included; pending activity and missing source coverage can limit the result.",
        ),
        (
            "Reading the choice colors",
            "Pale red marks a required choice that is missing or needs correction. Pale green marks a valid "
            "choice that has not been saved. Unchanged saved choices, read-only source facts and empty optional "
            "fields stay neutral. Light-blue buttons show available next actions; read their labels and confirmations. "
            "An amber message explains a prerequisite. Nearby messages give the same "
            "meaning without color. Green does not certify an interpretation, complete coverage or reconciliation. "
            "Read the confirmation before saving; cancelling it retains your draft.",
        ),
        (
            "5. Correct a saved review",
            "Inspect an entry from Budget or Reports, then Review / correct source row. The saved reason is "
            "read-only; enter a new correction reason before confirming. It is separate from the shared reason "
            "for staged rows. Back to budget or Back to report returns to your prior context. "
            "Source evidence and saved history remain available. Accounts has optional balances and history; "
            "an unknown opening or position is not zero.",
        ),
        (
            "6. Back up and recover",
            "Profile > Back up current profile creates a verified copy. Restore backup as new profile "
            "preserves the existing profile. Save selected source original recovers an embedded document. "
            "Ordinary financial data stays local. Profiles, backups and recovered originals contain financial data and are not encrypted by "
            "ParseTrail. The signed catalog cache and global preferences are separate from profile backups.",
        ),
    )
    for title, body in steps:
        heading = QLabel(title)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        guide.addWidget(heading)
        text = QLabel(body)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        guide.addWidget(text)
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
