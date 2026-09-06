"""Small synthetic operations that exercise packaged native dependencies."""

from __future__ import annotations

from io import BytesIO


def _sample_pdf() -> bytes:
    stream = b"BT /F1 12 Tf 20 40 Td (ParseTrail smoke) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(document)


def check_native_operations() -> None:
    """Use memory-only fixtures; never read settings, credentials, or financial data."""
    import sqlite3

    import numpy as np
    import openpyxl
    import pdfplumber
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from PySide6.QtGui import QImage
    from scipy.linalg import solve
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.naive_bayes import MultinomialNB

    key = Ed25519PrivateKey.generate()
    message = b"ParseTrail frozen runtime smoke"
    key.public_key().verify(key.sign(message), message)
    connection = sqlite3.connect(":memory:")
    try:
        if connection.execute("SELECT ? + ?", (2, 3)).fetchone() != (5,):
            raise RuntimeError("SQLite smoke failed")
    finally:
        connection.close()
    workbook = openpyxl.Workbook()
    workbook.active.append(["ParseTrail smoke", 5])
    spreadsheet = BytesIO()
    workbook.save(spreadsheet)
    workbook.close()
    spreadsheet.seek(0)
    loaded = openpyxl.load_workbook(spreadsheet, read_only=True)
    try:
        if loaded.active["B1"].value != 5:
            raise RuntimeError("XLSX smoke failed")
    finally:
        loaded.close()
    with pdfplumber.open(BytesIO(_sample_pdf())) as pdf:
        if pdf.pages[0].extract_text() != "ParseTrail smoke":
            raise RuntimeError("PDF text smoke failed")
        # Rendering exercises the bundled PDFium and Pillow native libraries too.
        pdf.pages[0].to_image(resolution=36).original.close()
    if not np.allclose(solve(np.eye(2), np.array([2.0, 3.0])), [2.0, 3.0]):
        raise RuntimeError("Scientific-library smoke failed")
    vectorizer = TfidfVectorizer()
    features = vectorizer.fit_transform(["grocery apples", "grocery bread", "train ticket", "bus ticket"])
    model = MultinomialNB().fit(features, [0, 0, 1, 1])
    if model.predict(vectorizer.transform(["grocery apples"])).tolist() != [0]:
        raise RuntimeError("Categorization-library smoke failed")
    if QImage(2, 2, QImage.Format.Format_RGB32).isNull():
        raise RuntimeError("Qt image smoke failed")
