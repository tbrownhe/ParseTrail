"""Public synthetic source documents for actual bounded family admission tests.

These deliberately small documents exercise the source boundary, not historical
source parity, complete capture, accounting, or installed/frozen acceptance.
The PDF writer uses only standard-library bytes and produces real PDF objects,
escaped string literals, cross-reference offsets, metadata and annotations.
"""

from __future__ import annotations

from dataclasses import dataclass

Word = tuple[int, int, str]


def _literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_document(
    pages: tuple[tuple[Word, ...], ...],
    *,
    metadata: dict[str, str] | None = None,
    horizontal_lines: dict[int, tuple[int, ...]] | None = None,
    annotations: tuple[tuple[str, str], ...] = (),
) -> bytes:
    """Render fixed public fixture text; no source paths or external PDF library."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    ]
    kids = []
    for page_index, words in enumerate(pages):
        number = len(objects) + 1
        kids.append(number)
        annotation_ids = tuple(range(number + 2, number + 2 + len(annotations))) if page_index == 0 else ()
        annots = " /Annots [" + " ".join(f"{item} 0 R" for item in annotation_ids) + "]" if annotation_ids else ""
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1400 1000] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {number + 1} 0 R{annots} >>"
            ).encode("ascii")
        )
        commands = [f"BT /F1 10 Tf {x} {y} Td ({_literal(value)}) Tj ET" for x, y, value in words]
        commands.extend(f"15 {y} m 1200 {y} l S" for y in (horizontal_lines or {}).get(page_index, ()))
        stream = "\n".join(commands).encode("cp1252")
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")
        if annotation_ids:
            objects.extend(
                (
                    f"<< /Type /Annot /Subtype /Widget /Rect [10 10 60 20] "
                    f"/T ({_literal(field)}) /V ({_literal(value)}) >>"
                ).encode("ascii")
                for field, value in annotations
            )
    objects[1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{number} 0 R' for number in kids)}] /Count {len(kids)} >>"
    ).encode("ascii")
    info = ""
    if metadata:
        objects.append(
            ("<< " + " ".join(f"/{key} ({_literal(value)})" for key, value in metadata.items()) + " >>").encode()
        )
        info = f" /Info {len(objects)} 0 R"
    document = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(document))
        document.extend(f"{number} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R{info} >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(document)


def text_page(*lines: str) -> tuple[Word, ...]:
    return tuple((20, 970 - index * 18, line) for index, line in enumerate(lines))


def table_page(headers: tuple[str, ...], rows: tuple[tuple[str, ...], ...], xs: tuple[int, ...]) -> tuple[Word, ...]:
    return tuple((x, 700, label) for x, label in zip(xs, headers, strict=True)) + tuple(
        (x, 680 - index * 20, value)
        for index, row in enumerate(rows)
        for x, value in zip(xs, row, strict=True)
        if value
    )


@dataclass(frozen=True)
class FamilySource:
    definition_name: str
    source: bytes
    suffix: str = ".pdf"


def family_sources() -> tuple[FamilySource, ...]:
    """One successful source per unchanged current declaration, with explicit routing."""
    from devtools.parser_engine_pilot import (
        test_card_lines,
        test_dual_text_card_lines,
        test_hsa_cash_lines,
        test_investment_summary_lines,
        test_legacy_citi_lines,
        test_loan_history_lines,
        test_occu_bank_lines,
        test_occu_card_lines,
        test_plan_label_summary,
        test_savings_lines,
        test_single_column_summary,
        test_summary_savings_lines,
        test_two_date_card_lines,
        test_wells_loan_lines,
    )

    # Reuse public synthetic text inputs, never parser outputs as expected facts.
    def line_pages(evidence) -> tuple[tuple[Word, ...], ...]:
        return tuple(
            text_page(*(line.raw for line in evidence.lines if line.page == page))
            for page in range(1, evidence.page_count + 1)
        )

    def located(name, evidence, marker, *, metadata=None):
        pages = line_pages(evidence)
        return FamilySource(
            name,
            pdf_document(
                (text_page(marker) + tuple((x, y - 18, s) for x, y, s in pages[0]), *pages[1:]), metadata=metadata
            ),
        )

    chase = test_card_lines.pages()
    chase[0] = "www.chase.com/cardhelp\nTransaction Merchant Name or Transaction Description $ Amount\n" + chase[0]
    happen = test_savings_lines.pages()
    happen[0] = "Summary of Accounts\n" + happen[0]
    new_lending = test_summary_savings_lines.pages()
    health = test_hsa_cash_lines.pages()
    health[0] = "HealthEquity HealthSavingsAccount\n" + health[0]
    us_layout, us_simple = test_dual_text_card_lines.channels()
    us_pages = text_page("U.S. Bank reivisa.com", *(line.raw for line in (*us_layout.lines, *us_simple.lines)))
    vanguard = test_single_column_summary.lines({2: "EMPLOYEES 123456"})
    cases = [
        FamilySource(
            "chase-card-pilot-definition.json",
            pdf_document(
                tuple(text_page(*p.splitlines()) for p in chase),
                metadata={"Producer": "OpenText Output Transformation Engine"},
            ),
        ),
        FamilySource(
            "happen-savings-pilot-definition.json",
            pdf_document(
                tuple(text_page(*p.splitlines()) for p in happen),
                metadata={"Creator": "VCTransaction", "Title": "StmtAPISvc"},
            ),
        ),
        FamilySource(
            "lendingclub-savings-pilot-definition.json",
            pdf_document(
                tuple(text_page(*p.splitlines()) for p in new_lending), metadata={"Creator": "ImageCentre Statements"}
            ),
        ),
        FamilySource("hsa-cash-pilot-definition.json", pdf_document(tuple(text_page(*p.splitlines()) for p in health))),
        located(
            "fidelity-hsa-summary-pilot-definition.json",
            test_investment_summary_lines.lines(),
            "Fidelity Health Savings Account",
        ),
        located("capital-one-loan-pilot-definition.json", test_loan_history_lines.lines(), "Capital One Auto Finance"),
        located(
            "fidelity-401k-summary-pilot-definition.json",
            test_plan_label_summary.lines(),
            "Fidelity Brokerage Services",
        ),
        located("vanguard-summary-pilot-definition.json", vanguard, "vanguard.com"),
        located(
            "occu-bank-pilot-definition.json",
            test_occu_bank_lines.lines(),
            "Oregon Community Credit Union MemberNumber",
        ),
        located("occu-card-pilot-definition.json", test_occu_card_lines.lines(), "www.myoccu.org CardServices"),
        located(
            "legacy-citi-pilot-definition.json",
            test_legacy_citi_lines.lines({5: "Date Description Amount"}),
            "Synthetic statement",
            metadata={"Producer": "Synthetic legacy layout"},
        ),
        located("yamaha-card-pilot-definition.json", test_two_date_card_lines.lines(), "Yamaha Motor Finance"),
        located(
            "wells-loan-pilot-definition.json", test_wells_loan_lines.lines(), "Wells Fargo Personal Loan Statement"
        ),
        FamilySource("usbank-rei-card-pilot-definition.json", pdf_document((us_pages,))),
        FamilySource(
            "transamerica-summary-pilot-definition.json",
            pdf_document(
                (
                    text_page(
                        "Transamerica retirement account statement",
                        "for January 1, 2026 - March 31, 2026 types",
                        "123456 12345 Transphorm 401(k) Plan $115.00",
                        "Beginning Balance $100.00 rate of return",
                        "Money In 3 Mo.",
                        "Your Contributions $20.00 forecast",
                        "Money Out -$10.00",
                        "Credits/Fees $0.00",
                        "Gain/Loss $5.00 estimated income",
                        "Ending Balance $115.00 all accounts",
                    ),
                )
            ),
        ),
    ]
    card = text_page(
        "www.citicards.com",
        "Billing Period: 01/01/26-01/31/26",
        "Account number ending in: 1234",
        "Previous balance $100.00",
        "New balance $110.00",
    )
    card_rows = (("01/02", "01/02", "SHOP", "$10.00"),)
    cases.extend(
        (
            FamilySource(
                "middle-citi-table-pilot-definition.json",
                pdf_document(
                    (card + table_page(("Trans.", "Post", "Description", "Amount"), card_rows, (20, 100, 200, 800)),),
                    metadata={"Producer": "crawfordtech"},
                ),
            ),
            FamilySource(
                "recent-citi-pilot-definition.json",
                pdf_document(
                    (card + table_page(("Sale", "Post", "Description", "Amount"), card_rows, (20, 100, 200, 800)),),
                    metadata={"Author": "Citibank, N.A."},
                    horizontal_lines={0: (690, 670)},
                ),
            ),
            FamilySource(
                "wells-table-pilot-definition.json",
                pdf_document(
                    (
                        text_page(
                            "Wells Fargo Initiate Business Checking",
                            "October 31, 2026 Page 1 of 1",
                            "Statement period activity summary Account number: 1234567890",
                            "Beginning balance on 10/1 $100.00",
                            "Ending balance on 10/31 $101.00",
                        )
                        + table_page(
                            ("Date", "Description", "Credits", "Debits", "balance"),
                            (("10/1", "Printed", "$1.00", "", "$101.00"),),
                            (20, 100, 400, 600, 800),
                        ),
                    )
                ),
            ),
            FamilySource(
                "wells-personal-table-pilot-definition.json",
                pdf_document(
                    (
                        text_page(
                            "Wells Fargo Everyday Checking",
                            "January 31, 2026 Page 1 of 1",
                            "Statement period activity summary Account number: 1234567890",
                            "Beginning balance on 1/1 $100.00",
                            "Ending balance on 1/31 $120.00",
                        )
                        + table_page(
                            ("Date", "Description", "Additions", "Subtractions", "balance"),
                            (("1/5", "Deposit", "$20.00", "", "$120.00"),),
                            (20, 100, 400, 600, 800),
                        ),
                    )
                ),
            ),
            FamilySource(
                "synchrony-table-pilot-definition.json",
                pdf_document(
                    (
                        text_page(
                            "amazon.syf.com",
                            "Account Number ending in 1234",
                            "Previous Balance as of 01/01/2026 $100.00",
                            "New Balance as of 01/31/2026 $110.00",
                        ),
                        table_page(
                            ("Date", "Reference", "Description", "Amount"),
                            (("01/02", "REF", "SHOP", "$10.00"),),
                            (20, 100, 200, 800),
                        ),
                    )
                ),
            ),
        )
    )
    bank_header = text_page(
        "LLeevveellUUpp SSaavviinnggss",
        "Statement Begin Date: 01/01/2026",
        "Statement End Date: 01/31/2026",
        "Account Number: 1234567890",
        "Balance + Deposits + Paid - Withdrawals - Charge = Balance",
        "$100.00 $0.00 $10.00 $0.00 $0.00 $110.00",
        "Previous Statement Date: 12/31/2025 Average Statement Balance: $100.00",
        "Interest Earned $10.00",
    )
    bank_table = table_page(
        ("Date", "Description", "Withdrawal", "(-)", "Deposit", "(+)", "Balance"),
        (),
        (20, 100, 400, 480, 600, 660, 800),
    )
    # Deliberately clipped monetary tails, paired with their full same-page text.
    tails = (
        ("01/01", "Balance Forward", "", "", "$100.00"),
        ("01/05", "Interest Paid", "", "$10.00", "$110.00"),
        ("ious Sta", "tement Date: 12/31/2025", "Average Statem", "ent Balance: $100.00", ""),
        ("", "$100.00 $0.00", "$10.00", "$0.00", "$0.00 $110.00"),
        ("rest Ear", "ned $10.00", "", "", ""),
        ("", "Savings 1234567890 $110.00", "4.00%", "$10.00 $0.00", ""),
    )
    bank_table += tuple(
        (x, 680 - index * 20, value)
        for index, row in enumerate(tails)
        for x, value in zip((20, 100, 400, 600, 800), row, strict=True)
        if value
    )
    cases.append(FamilySource("lendingclub-table-pilot-definition.json", pdf_document((bank_header + bank_table,))))
    prefix = b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
    cases.extend(
        (
            FamilySource(
                "mohela-account-history-definition.json",
                prefix
                + b"Date,Description,Principal,Interest,Fees,Total,\n10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,\n",
                ".csv",
            ),
            FamilySource(
                "mohela-pilot-definition.json",
                prefix
                + b"Date,LoanName,Description,Principal,Interest,Fees,Total,UnpaidPrincipalBalanceValue,\n10/01/2026,123-1 Loan A,Payment,-$80.00,-$20.00,$0.00,-$100.00,$900.00,\n10/02/2026,456-2 Loan B,Payment,-$50.00,$0.00,$0.00,-$50.00,Unavailable,\n",
                ".csv",
            ),
        )
    )
    return tuple(cases)


def occu_annotation_source() -> bytes:
    """The same two-account facts with real first-page widget date locations."""
    from devtools.parser_engine_pilot.test_occu_bank_lines import lines

    evidence = lines(annotation=True)
    page = text_page("Oregon Community Credit Union MemberNumber", *(line.raw for line in evidence.lines))
    return pdf_document((page,), annotations=(("FROM_DATE", "01/01/26"), ("TO_DATE", "01/31/26")))
