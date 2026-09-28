from io import BytesIO

import pdfplumber
import pytest
from parsetrail.plugins.pdf_citicc_202506 import Parser


def thin_glyph_pdf(description_x=150):
    """Synthetic accessible-PDF metrics: text glyph boxes are only 0.24pt high."""
    content = (
        b"BT /F1 12 Tf "
        + b" ".join(
            f"1 0 0 0.02 {x} {y} Tm ({word}) Tj".encode()
            for x, y, word in (
                (30, 700, "Trans."),
                (90, 700, "Post"),
                (150, 700, "Description"),
                (400, 700, "Amount"),
                (30, 680, "08/30"),
                (90, 680, "08/30"),
                (description_x, 680, "FIRST"),
                (404.656, 680, "$10.00"),
                (30, 660, "08/31"),
                (90, 660, "08/31"),
                (description_x, 660, "LAST"),
                (411.328, 660, "$5.14"),
            )
        )
        + b" ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /FontDescriptor 5 0 R >>",
        b"<< /Type /FontDescriptor /FontName /Helvetica /Flags 32 /FontBBox [0 0 1000 20] /Ascent 20 /Descent 0 /CapHeight 20 /StemV 80 /ItalicAngle 0 >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 7\n0000000000 65535 f \n"
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return data + f"trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


@pytest.mark.parametrize("description_x", [150, 138])
def test_thin_glyph_table_retains_last_transaction_row_and_full_description(description_x):
    with pdfplumber.open(BytesIO(thin_glyph_pdf(description_x))) as pdf:
        page = pdf.pages[0]
        assert page.chars[0]["height"] < 1
        rows = Parser().get_transactions_from_page(page)
        assert [row for row in rows if row[0]] == [
            ["08/30", "08/30", "FIRST", "$10.00"],
            ["08/31", "08/31", "LAST", "$5.14"],
        ]
