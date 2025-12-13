from PyQt5.QtWidgets import QDialog, QLineEdit, QVBoxLayout, QDialogButtonBox, QLabel
from parsetrail.core import auth
from parsetrail.core.settings import settings


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Login to Server")

        self.email_edit = QLineEdit(self)
        self.email_edit.setPlaceholderText("Email")
        if getattr(settings, "email", None):
            self.email_edit.setText(settings.email)

        self.password_edit = QLineEdit(self)
        self.password_edit.setPlaceholderText("Password")
        self.password_edit.setEchoMode(QLineEdit.Password)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Email:"))
        layout.addWidget(self.email_edit)
        layout.addWidget(QLabel("Password:"))
        layout.addWidget(self.password_edit)
        layout.addWidget(buttons)

    def email(self) -> str:
        return self.email_edit.text().strip()

    def password(self) -> str:
        return self.password_edit.text()


def qt_prompt_for_credentials():
    dlg = LoginDialog()
    if dlg.exec() == QDialog.Accepted:
        # optionally persist username in settings.server_username here
        return dlg.email(), dlg.password()
    return None


def configure_ui_hooks():
    """Add all bootstrapped hooks for GUI implementation here"""
    # Replace UI-free default method with the PyQt dialog
    auth.prompt_for_credentials = qt_prompt_for_credentials
