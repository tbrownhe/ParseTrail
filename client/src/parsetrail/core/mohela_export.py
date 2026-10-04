"""Lossless MOHELA activity evidence; never manufacture statement endpoints."""

import csv
import hashlib
import io
import re
from collections import Counter, defaultdict
from datetime import datetime

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_store import encoded
from parsetrail.core.money import parse_money, to_minor_units

RULE = "mohela-detailed-export-1"
COLUMNS = ("Date", "LoanName", "Description", "Principal", "Interest", "Fees", "Total", "UnpaidPrincipalBalanceValue")


def identity(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def read_export(data: bytes):
    """Keep source signs, zero components, duplicate occurrences and unknown balances."""
    source = hashlib.sha256(data).hexdigest()
    try:
        array = list(csv.reader(io.StringIO(data.decode("utf-8-sig")), strict=True))
    except (UnicodeError, csv.Error) as exc:
        raise LedgerError("Invalid MOHELA CSV encoding or structure.") from exc
    if not array or not array[0]:
        raise LedgerError("Empty MOHELA export.")
    headers = list(array[0])
    headers[0] = headers[0].split(">")[-1]
    if headers not in (list(COLUMNS), [*COLUMNS, ""]):
        raise LedgerError("Use the detailed MOHELA export with loan identities and unpaid principal balances.")
    rows, names, seen = [], {}, Counter()
    for number, values in enumerate(array[1:], 2):
        if not values or not any(values):
            continue
        if len(values) != len(headers) or (headers[-1] == "" and values[-1]):
            raise LedgerError("MOHELA row width or trailing column is invalid.")
        raw = dict(zip(COLUMNS, values[: len(COLUMNS)], strict=True))
        try:
            when = datetime.strptime(raw["Date"], "%m/%d/%Y").date()
            if when.strftime("%m/%d/%Y") != raw["Date"]:
                raise ValueError("date")
            match = re.fullmatch(r"(\d+-\d+) (.+)", raw["LoanName"])
            if not match or not raw["Description"].strip():
                raise ValueError("identity")
            loan = match[1]
            if loan in names and names[loan] != raw["LoanName"]:
                raise ValueError("conflicting loan names")
            names[loan] = raw["LoanName"]
            amounts = {}
            for field in (*COLUMNS[3:7], "UnpaidPrincipalBalanceValue"):
                value = raw[field]
                if field == "UnpaidPrincipalBalanceValue" and value == "Unavailable":
                    amounts[field] = None
                    continue
                if not re.fullmatch(r"-?\$(?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2}", value):
                    raise ValueError("money")
                amounts[field] = to_minor_units(parse_money(value))
            if amounts["Principal"] + amounts["Interest"] + amounts["Fees"] != amounts["Total"]:
                raise ValueError("component equation")
        except (TypeError, ValueError) as exc:
            raise LedgerError(f"MOHELA row {number} has invalid identity, date or component amounts.") from exc
        row = {
            "loan_id": loan,
            "loan_name": raw["LoanName"],
            "date": str(when),
            "description": raw["Description"],
            "principal_minor": amounts["Principal"],
            "interest_minor": amounts["Interest"],
            "fees_minor": amounts["Fees"],
            "total_minor": amounts["Total"],
            "reported_principal_minor": amounts["UnpaidPrincipalBalanceValue"],
            "raw": raw,
            "row_number": number,
        }
        fingerprint = identity(raw)
        row["id"] = identity([source, fingerprint, seen[fingerprint]])
        seen[fingerprint] += 1
        rows.append(row)
    if not rows:
        raise LedgerError("MOHELA export contains no activity.")
    return {
        "rule": RULE,
        "source_sha256": source,
        "rows": rows,
        "activity_start": min(r["date"] for r in rows),
        "activity_end": max(r["date"] for r in rows),
        "coverage_verified": False,
        "balance_reconciled": False,
        "reported_as_of": None,
    }


def loan_summary(export):
    loans = defaultdict(list)
    for row in export["rows"]:
        loans[row["loan_id"]].append(row)
    result = []
    for loan, rows in sorted(loans.items()):
        known = [r for r in rows if r["reported_principal_minor"] is not None]
        latest = max((r["date"] for r in known), default=None)
        observations = [r for r in known if r["date"] == latest]
        balances = {r["reported_principal_minor"] for r in observations}
        balance = next(iter(balances)) if len(balances) == 1 else None
        net = sum(r["principal_minor"] for r in rows if latest is None or r["date"] <= latest)
        result.append(
            {
                "loan_id": loan,
                "loan_name": rows[0]["loan_name"],
                "row_count": len(rows),
                "balance_date": latest,
                "reported_principal_minor": balance,
                "balance_conflict": len(balances) > 1,
                "net_listed_principal_minor": net,
                "unexplained_minor": None if balance is None else balance - net,
                "balance_rows": [r["id"] for r in observations],
                "coverage_verified": False,
                "reconciled": False,
            }
        )
    return result


def store_export_evidence(connection, plan):
    """Optional immutable evidence tables in a newly built ledger database."""
    if not plan.get("activity_exports"):
        return ()
    definitions = {
        "ActivityExports": "id TEXT PRIMARY KEY REFERENCES SourceFiles(id), payload TEXT NOT NULL",
        "ActivityExportRows": "id TEXT PRIMARY KEY, export_id TEXT NOT NULL REFERENCES ActivityExports(id), loan_id TEXT NOT NULL, payload TEXT NOT NULL",
        "ExportCategoryBindings": "legacy_id INTEGER PRIMARY KEY, category_id INTEGER NOT NULL REFERENCES CategoryDefinitions(id), export_id TEXT NOT NULL REFERENCES ActivityExports(id), payload TEXT NOT NULL",
        "SupersededSourceEvidence": "source_id TEXT PRIMARY KEY REFERENCES SourceFiles(id), payload TEXT NOT NULL",
    }
    for name, columns in definitions.items():
        connection.execute(f"CREATE TABLE {name}({columns})")
    for fid, export in plan["activity_exports"].items():
        connection.execute("INSERT INTO ActivityExports VALUES(?,?)", (fid, encoded(export)))
        connection.executemany(
            "INSERT INTO ActivityExportRows VALUES(?,?,?,?)",
            [(r["id"], fid, r["loan_id"], encoded(r)) for r in export["rows"]],
        )
    connection.executemany(
        "INSERT INTO ExportCategoryBindings VALUES(?,?,?,?)",
        [(b["legacy_id"], b["category_id"], b["export_id"], encoded(b)) for b in plan["export_category_bindings"]],
    )
    connection.executemany(
        "INSERT INTO SupersededSourceEvidence VALUES(?,?)",
        [(fid, encoded(value)) for fid, value in plan["superseded_source_evidence"].items()],
    )
    return tuple(definitions)
