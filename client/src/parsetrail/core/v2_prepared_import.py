"""One operation's private, bounded source-to-evidence preparation authority."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_bounded_pdf_text import pdf_decode_operation
from parsetrail.core.v2_format_recognition import (
    CatalogImportError,
    ImportCancelled,
    _recognize_catalog_source,
    candidate_from_evidence,
    selected_definition,
    validate_catalog_evidence,
)
from parsetrail.core.v2_import_accounts import _profile_identity, build_import_account_review, prepare_import_accounts
from parsetrail.core.v2_profile_store import ProfileFormatError
from parsetrail.core.v2_source_pipeline import MAX_EVIDENCE_BYTES, build_source_evidence


class PreparedImportSession:
    """Own private outputs until one apply attempt or explicit disposal.

    Public review and decision objects contain only bounded presentation data and
    an operation identifier. They never retain this owner, source bytes, or full
    evidence. Canonical evidence bytes share one aggregate pipeline-sized budget.
    Only the selected output is reconstructed as a complete frozen model.
    """

    __slots__ = (
        "_source",
        "_catalog",
        "_suffix",
        "_recognition",
        "_review",
        "_plan",
        "_selection",
        "_format_profile",
        "_definition",
        "_evidence",
        "_outputs",
        "_output_bytes",
        "_operation_id",
        "_phase",
    )

    def __init__(self, source, *, catalog, suffix, cancelled=None):
        self._source = source
        self._catalog = deepcopy(catalog)
        self._suffix = suffix
        self._recognition = None
        self._review = None
        self._plan = None
        self._selection = None
        self._format_profile = None
        self._definition = None
        self._evidence = None
        self._outputs = {}
        self._output_bytes = 0
        self._operation_id = uuid4().hex
        self._phase = "preparing"
        try:
            # This scope ends before the UI receives a preview. Decoded pages
            # are released while bounded canonical evidence remains owned here.
            with pdf_decode_operation():
                self._recognition = _recognize_catalog_source(
                    source,
                    catalog=self._catalog,
                    suffix=suffix,
                    cancelled=cancelled,
                    collect=self._collect,
                    parse=build_source_evidence,
                )
            if not self._recognition.candidates:
                raise CatalogImportError("catalog_no_match")
            self._phase = "recognized"
        except BaseException:
            self.close()
            raise

    def _collect(self, definition, evidence):
        content = evidence.model_dump_json().encode("utf-8")
        if self._output_bytes + len(content) > MAX_EVIDENCE_BYTES:
            raise CatalogImportError("import_preparation_size_limit")
        self._outputs[definition.identity.parser_id] = (content, hashlib.sha256(content).digest())
        self._output_bytes += len(content)

    def __enter__(self):
        self._require("recognized")
        return self

    def __exit__(self, *_exception):
        self.close()

    def _require(self, phase):
        if self._phase != phase:
            raise ProfileFormatError("import_preparation_unavailable")

    def review(self, store, *, preferences=None, recovery_notice=""):
        """Bind the core-built review to this operation's physical profile/basis."""
        self._require("recognized")
        self._review = replace(
            build_import_account_review(store, self._recognition, self._catalog, preferences),
            recovery_notice=recovery_notice,
            operation_id=self._operation_id,
        )
        self._phase = "reviewed"
        return deepcopy(self._review)

    def select(self, plan, *, cancelled=None):
        """Validate caller choices using private complete recognition, without parsing."""
        self._require("reviewed")
        if cancelled is not None and cancelled():
            raise ImportCancelled("cancelled")
        if plan.operation_id != self._operation_id:
            raise ProfileFormatError("import_preparation_operation_mismatch")
        expected = prepare_import_accounts(self._review, plan.choices, plan.selection.parser_id, plan.new_accounts)
        if expected != plan:
            raise ProfileFormatError("import_account_format_changed")
        self._plan = deepcopy(expected)
        self._select_output(self._plan.selection, self._plan.candidate, cancelled)

    def format_review(self, store):
        """Bind a legacy explicit-format preview to its physical profile."""
        self._require("recognized")
        self._format_profile = _profile_identity(store)
        self._phase = "format_reviewed"
        return deepcopy(self._recognition)

    def select_format(self, selection, *, cancelled=None):
        self._require("format_reviewed")
        candidate = next((item for item in self._recognition.candidates if item.parser_id == selection.parser_id), None)
        if candidate is None or self._recognition.selection(selection.parser_id) != selection:
            raise CatalogImportError("catalog_selection_mismatch")
        self._select_output(deepcopy(selection), candidate, cancelled)

    def _select_output(self, selection, candidate, cancelled):
        if cancelled is not None and cancelled():
            raise ImportCancelled("cancelled")
        definition = selected_definition(self._source, catalog=self._catalog, suffix=self._suffix, selection=selection)
        content, digest = self._outputs[selection.parser_id]
        if hashlib.sha256(content).digest() != digest:
            raise ProfileFormatError("import_account_format_changed")
        evidence = SourceEvidence.model_validate_json(content)
        validate_catalog_evidence(evidence, selection.source_sha256, definition)
        if candidate_from_evidence(definition, evidence, self._catalog) != candidate:
            raise ProfileFormatError("import_account_format_changed")
        if cancelled is not None and cancelled():
            raise ImportCancelled("cancelled")
        self._definition = definition.content
        self._evidence = evidence
        self._selection = selection
        self._phase = "selected"

    def claim(self, catalog, plan):
        """Consume authority for exactly one apply attempt, retaining private data until close."""
        self._require("selected")
        if (
            self._plan is None
            or catalog != self._catalog
            or plan != self._plan
            or plan.operation_id != self._operation_id
        ):
            raise ProfileFormatError("import_account_format_changed")
        self._validate_selected_output()
        self._phase = "applying"
        return self._recognition, self._plan, self._catalog

    def claim_format(self, store, catalog, selection):
        self._require("selected")
        if self._plan is not None or selection != self._selection:
            raise CatalogImportError("catalog_selection_mismatch")
        if catalog != self._catalog:
            raise CatalogImportError("catalog_selection_catalog_changed")
        self.validate_format_profile(store)
        self._validate_selected_output()
        self._phase = "applying"
        return self._selection

    def validate_format_profile(self, store):
        if _profile_identity(store) != self._format_profile:
            raise ProfileFormatError("import_account_profile_changed")

    def _validate_selected_output(self):
        content, digest = self._outputs[self._selection.parser_id]
        if (
            type(self._evidence) is not SourceEvidence
            or hashlib.sha256(content).digest() != digest
            or self._evidence.model_dump_json().encode("utf-8") != content
        ):
            raise ProfileFormatError("import_account_format_changed")

    def validate_apply(self, *, catalog, plan=None, selection=None):
        self._require("applying")
        if catalog != self._catalog or plan != self._plan or (selection is not None and selection != self._selection):
            raise ProfileFormatError("import_account_format_changed")
        definition = selected_definition(
            self._source, catalog=self._catalog, suffix=self._suffix, selection=self._selection
        )
        if self._definition != definition.content:
            raise ProfileFormatError("import_account_format_changed")
        self._validate_selected_output()

    @property
    def source(self):
        self._require("applying")
        return self._source

    @property
    def definition(self):
        self._require("applying")
        return self._definition

    @property
    def suffix(self):
        self._require("applying")
        return self._suffix

    @property
    def evidence(self):
        self._require("applying")
        return self._evidence

    def close(self):
        """Drop all operation-owned source/output/catalog/review references."""
        self._phase = "closed"
        self._source = None
        self._catalog = None
        self._suffix = None
        self._recognition = None
        self._review = None
        self._plan = None
        self._selection = None
        self._format_profile = None
        self._definition = None
        self._evidence = None
        self._outputs.clear()
        self._output_bytes = 0
        self._operation_id = None
