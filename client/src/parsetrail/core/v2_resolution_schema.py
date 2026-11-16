"""Fresh-profile tables for reviewed unresolved money, identity and acquisition history."""

TABLES = {
    "UnresolvedTransferLegs": (
        ("event_id", "TEXT", 0, 1),
        ("row_id", "TEXT", 1, 0),
        ("source_sha256", "TEXT", 1, 0),
        ("account_id", "TEXT", 1, 0),
        ("movement_payload", "TEXT", 1, 0),
        ("entry_key", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "UnresolvedTransferActions": (
        ("action_id", "INTEGER", 0, 1),
        ("event_id", "TEXT", 1, 0),
        ("expected_version", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "TransferResolutionLinks": (
        ("link_id", "TEXT", 0, 1),
        ("outgoing_id", "TEXT", 1, 0),
        ("incoming_id", "TEXT", 1, 0),
        ("outgoing_version", "TEXT", 1, 0),
        ("incoming_version", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "TransferResolutionActions": (
        ("action_id", "INTEGER", 0, 1),
        ("link_id", "TEXT", 1, 0),
        ("expected_version", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "AccountImportOrigins": (
        ("account_id", "TEXT", 0, 1),
        ("source_sha256", "TEXT", 1, 0),
        ("institution_key", "TEXT", 0, 0),
        ("product_type", "TEXT", 0, 0),
        ("record_sha256", "TEXT", 1, 0),
    ),
    "ZeroAmountReviews": (
        ("revision_id", "INTEGER", 0, 1),
        ("row_id", "TEXT", 1, 0),
        ("source_sha256", "TEXT", 1, 0),
        ("account_id", "TEXT", 1, 0),
        ("category_id", "TEXT", 1, 0),
        ("purpose", "TEXT", 1, 0),
        ("prior_revision_id", "INTEGER", 0, 0),
        ("action", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "LoanOriginationEvents": (
        ("event_id", "TEXT", 0, 1),
        ("row_id", "TEXT", 1, 0),
        ("source_sha256", "TEXT", 1, 0),
        ("account_id", "TEXT", 1, 0),
        ("destination_account_id", "TEXT", 0, 0),
        ("bank_row_id", "TEXT", 0, 0),
        ("manifest", "TEXT", 1, 0),
        ("entry_versions", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "LoanOriginationActions": (
        ("action_id", "INTEGER", 0, 1),
        ("event_id", "TEXT", 1, 0),
        ("expected_version", "TEXT", 1, 0),
        ("reason", "TEXT", 1, 0),
        ("request_basis", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
    "LoanOriginationSourceUses": (
        ("event_id", "TEXT", 1, 1),
        ("entry_key", "TEXT", 1, 0),
        ("row_id", "TEXT", 1, 2),
        ("amount_minor", "INTEGER", 1, 0),
    ),
    "TangibleAssetValues": (
        ("revision_id", "INTEGER", 0, 1),
        ("account_id", "TEXT", 1, 0),
        ("value_date", "TEXT", 1, 0),
        ("amount_minor", "INTEGER", 1, 0),
        ("annual_rate_basis_points", "INTEGER", 0, 0),
        ("reason", "TEXT", 1, 0),
        ("record_sha256", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ),
}

FOREIGN_KEYS = {
    "UnresolvedTransferLegs": (
        ("entry_key", "JournalEntries", "key"),
        ("account_id", "Accounts", "id"),
        ("source_sha256", "Sources", "sha256"),
        ("row_id", "SourceObservations", "row_id"),
    ),
    "UnresolvedTransferActions": (("event_id", "UnresolvedTransferLegs", "event_id"),),
    "TransferResolutionLinks": (),
    "TransferResolutionActions": (("link_id", "TransferResolutionLinks", "link_id"),),
    "AccountImportOrigins": (("source_sha256", "Sources", "sha256"), ("account_id", "Accounts", "id")),
    "ZeroAmountReviews": (
        ("prior_revision_id", "ZeroAmountReviews", "revision_id"),
        ("category_id", "Accounts", "id"),
        ("account_id", "Accounts", "id"),
        ("source_sha256", "Sources", "sha256"),
        ("row_id", "SourceObservations", "row_id"),
    ),
    "LoanOriginationEvents": (
        ("bank_row_id", "SourceObservations", "row_id"),
        ("destination_account_id", "Accounts", "id"),
        ("account_id", "Accounts", "id"),
        ("source_sha256", "Sources", "sha256"),
        ("row_id", "SourceObservations", "row_id"),
    ),
    "LoanOriginationActions": (("event_id", "LoanOriginationEvents", "event_id"),),
    "LoanOriginationSourceUses": (
        ("row_id", "SourceObservations", "row_id"),
        ("entry_key", "JournalEntries", "key"),
        ("event_id", "LoanOriginationEvents", "event_id"),
    ),
    "TangibleAssetValues": (("account_id", "Accounts", "id"),),
}

SQL = """
CREATE TABLE UnresolvedTransferLegs (event_id TEXT PRIMARY KEY, row_id TEXT NOT NULL REFERENCES SourceObservations(row_id), source_sha256 TEXT NOT NULL REFERENCES Sources(sha256), account_id TEXT NOT NULL REFERENCES Accounts(id), movement_payload TEXT NOT NULL, entry_key TEXT NOT NULL REFERENCES JournalEntries(key), reason TEXT NOT NULL, request_basis TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE UnresolvedTransferActions (action_id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE REFERENCES UnresolvedTransferLegs(event_id), expected_version TEXT NOT NULL, reason TEXT NOT NULL, request_basis TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE TransferResolutionLinks (link_id TEXT PRIMARY KEY, outgoing_id TEXT NOT NULL, incoming_id TEXT NOT NULL, outgoing_version TEXT NOT NULL, incoming_version TEXT NOT NULL, reason TEXT NOT NULL, request_basis TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE TransferResolutionActions (action_id INTEGER PRIMARY KEY, link_id TEXT NOT NULL UNIQUE REFERENCES TransferResolutionLinks(link_id), expected_version TEXT NOT NULL, reason TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE AccountImportOrigins (account_id TEXT PRIMARY KEY REFERENCES Accounts(id), source_sha256 TEXT NOT NULL REFERENCES Sources(sha256), institution_key TEXT, product_type TEXT, record_sha256 TEXT NOT NULL);
CREATE TABLE ZeroAmountReviews (revision_id INTEGER PRIMARY KEY, row_id TEXT NOT NULL REFERENCES SourceObservations(row_id), source_sha256 TEXT NOT NULL REFERENCES Sources(sha256), account_id TEXT NOT NULL REFERENCES Accounts(id), category_id TEXT NOT NULL REFERENCES Accounts(id), purpose TEXT NOT NULL, prior_revision_id INTEGER REFERENCES ZeroAmountReviews(revision_id), action TEXT NOT NULL CHECK(action IN ('reviewed','withdrawn')), reason TEXT NOT NULL, request_basis TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE LoanOriginationEvents (event_id TEXT PRIMARY KEY, row_id TEXT NOT NULL REFERENCES SourceObservations(row_id), source_sha256 TEXT NOT NULL REFERENCES Sources(sha256), account_id TEXT NOT NULL REFERENCES Accounts(id), destination_account_id TEXT REFERENCES Accounts(id), bank_row_id TEXT REFERENCES SourceObservations(row_id), manifest TEXT NOT NULL, entry_versions TEXT NOT NULL, reason TEXT NOT NULL, request_basis TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE LoanOriginationActions (action_id INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE REFERENCES LoanOriginationEvents(event_id), expected_version TEXT NOT NULL, reason TEXT NOT NULL, request_basis TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE LoanOriginationSourceUses (event_id TEXT NOT NULL REFERENCES LoanOriginationEvents(event_id), entry_key TEXT NOT NULL REFERENCES JournalEntries(key), row_id TEXT NOT NULL REFERENCES SourceObservations(row_id), amount_minor INTEGER NOT NULL, PRIMARY KEY(event_id,row_id));
CREATE TABLE TangibleAssetValues (revision_id INTEGER PRIMARY KEY, account_id TEXT NOT NULL REFERENCES Accounts(id), value_date TEXT NOT NULL, amount_minor INTEGER NOT NULL, annual_rate_basis_points INTEGER, reason TEXT NOT NULL, record_sha256 TEXT NOT NULL, created_at TEXT NOT NULL);
"""
