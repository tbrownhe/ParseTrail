"""An unidentified-institution choice cannot become a named matching identity."""

import pytest
from parsetrail.core.v2_institutions import Institution, merge_institutions
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore


@pytest.mark.parametrize(
    "name",
    [
        "Unknown",
        "NOT IDENTIFIED",
        "Institution not identified",
        "INSTITUTION  NOT  IDENTIFIED",
        "Choose an institution…",
        "Choose an institution...",
    ],
)
def test_unknown_and_required_placeholder_names_cannot_be_managed_identities(tmp_path, name):
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        before = store.institutions()
        record = Institution("institution_not_identified", name)
        with pytest.raises(ValueError, match="institution_invalid"):
            merge_institutions(before, (record,))
        with pytest.raises(ProfileFormatError, match="institution_invalid"):
            store.register_institution(record)
        assert store.institutions() == before and not store.connection.in_transaction
