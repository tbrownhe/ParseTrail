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
            "1. Keep your profiles separate",
            "This fresh workspace is independent of your 1.x history. Add the financial accounts and categories "
            "you want to track here. The active profile path is always shown in the window.",
        ),
        (
            "2. Install a signed catalog and import originals",
            "Choose Install signed catalog, then import a CSV/PDF file or a folder. Ordinary imports and "
            "analysis stay on your device. Original files stay where you selected them; the profile retains "
            "a copy of every successfully imported original. Choose an existing account or Create a new account, "
            "then review the recognized dates and amounts. CSV headers must match a declared format; account "
            "details narrow formats automatically. Unresolved format conflicts block import without a column-mapping "
            "choice. Import and assign saves original/evidence, new account drafts and "
            "assignments together without posting transactions. Back keeps choices; Skip/Cancel discards unsaved "
            "drafts and keeps completed files. PDF uses automatic signed routing.",
        ),
        (
            "3. Confirm accounts and repeated evidence",
            "Import shows every account group in the document. Header compatibility does not identify your account; "
            "Create a new account stays available beside compatible existing choices. Product supplies the "
            "asset/liability class and permitted scope. Use Review possible repeated transactions for overlap. "
            "Choose institutions by name or deliberately choose Institution not identified. "
            "Generic CSV headers do not identify a bank; a listed institution does not mean every format "
            "from it is supported. Equal amounts are suggestions to inspect, not proof of a duplicate or a transfer.",
        ),
        (
            "4. Review before posting",
            "Review supported cash activity, card purchases and transfers explicitly. Importing and account "
            "binding do not post money. Transfers and card repayments do not create a second expense. "
            "Unsupported activity remains pending. Use Ctrl-click or Shift to select several unreviewed rows, "
            "choose a shared purpose/category/note, then Stage selected and Review staged before confirming. "
            "One transaction uses the same staging flow. The table distinguishes staged unsaved proposals from "
            "not-staged and reviewed rows; remove selected proposals to undo staging. "
            "Each row keeps its own date. Successful staging captures the note for every staged row; "
            "later unstaged edits do not change it. Saved entries are corrected individually.",
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
