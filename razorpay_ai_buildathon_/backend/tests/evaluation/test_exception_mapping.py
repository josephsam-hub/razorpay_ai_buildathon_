"""
Tests — exception_mapping.py: semantic E-code bridge.
"""

from __future__ import annotations

import pytest

from app.core.evaluation.exception_mapping import (
    CALIBRATION_SEEDS,
    CORRUPTION_MAPPINGS,
    EVALUATION_SEEDS,
    HOLDOUT_SEED,
    assert_not_holdout,
    classify_seed,
    codes_intersect,
    get_expected_rec_codes,
    get_mapping,
    is_expected_decision,
)


class TestMappingCoverage:
    def test_all_eight_generator_types_mapped(self):
        expected = {
            "missing_settlement", "missing_bank_entry", "missing_ledger_entry",
            "amount_mismatch", "date_mismatch", "duplicate_bank_entry",
            "settlement_fee_variance", "orphan_bank_entry",
        }
        assert set(CORRUPTION_MAPPINGS.keys()) == expected

    def test_every_mapping_has_at_least_one_rec_code(self):
        for gen_type, m in CORRUPTION_MAPPINGS.items():
            assert len(m.expected_rec_codes) >= 1, \
                f"{gen_type} has no expected rec: codes"

    def test_all_rec_codes_use_prefix(self):
        for gen_type, m in CORRUPTION_MAPPINGS.items():
            for code in m.expected_rec_codes:
                assert code.startswith("rec:"), \
                    f"{gen_type} code '{code}' missing 'rec:' prefix"

    def test_gen_codes_are_e001_through_e008(self):
        gen_codes = {m.gen_code for m in CORRUPTION_MAPPINGS.values()}
        assert gen_codes == {"E001", "E002", "E003", "E004", "E005", "E006", "E007", "E008"}


class TestSpecificMappings:
    def test_e001_missing_settlement_maps_to_rec_e001(self):
        codes = get_expected_rec_codes("missing_settlement")
        assert "rec:E001" in codes

    def test_e002_missing_bank_entry_maps_to_rec_e001(self):
        codes = get_expected_rec_codes("missing_bank_entry")
        assert "rec:E001" in codes

    def test_e003_missing_ledger_maps_to_rec_e001(self):
        codes = get_expected_rec_codes("missing_ledger_entry")
        assert "rec:E001" in codes

    def test_e004_amount_mismatch_maps_to_rec_e002(self):
        codes = get_expected_rec_codes("amount_mismatch")
        assert "rec:E002" in codes

    def test_e005_date_mismatch_maps_to_rec_e004(self):
        codes = get_expected_rec_codes("date_mismatch")
        assert "rec:E004" in codes

    def test_e006_duplicate_maps_to_rec_e003(self):
        codes = get_expected_rec_codes("duplicate_bank_entry")
        assert "rec:E003" in codes

    def test_e007_fee_variance_maps_to_rec_e002(self):
        """E007 is the known-gap corruption type — mapped to rec:E002."""
        codes = get_expected_rec_codes("settlement_fee_variance")
        assert "rec:E002" in codes

    def test_e007_notes_document_known_gap(self):
        m = get_mapping("settlement_fee_variance")
        assert "KNOWN GAP" in m.notes or "Phase 3.1" in m.notes

    def test_e008_orphan_maps_to_rec_e008(self):
        codes = get_expected_rec_codes("orphan_bank_entry")
        assert "rec:E008" in codes

    def test_unknown_gen_type_returns_empty(self):
        codes = get_expected_rec_codes("nonexistent_type")
        assert codes == []

    def test_get_mapping_unknown_returns_none(self):
        assert get_mapping("made_up_type") is None


class TestCodesIntersect:
    def test_matching_codes(self):
        assert codes_intersect(["rec:E002", "rec:E004"], "amount_mismatch") is True

    def test_no_intersection(self):
        assert codes_intersect(["rec:E003"], "amount_mismatch") is False

    def test_empty_engine_codes(self):
        assert codes_intersect([], "amount_mismatch") is False

    def test_unknown_gen_type(self):
        assert codes_intersect(["rec:E001"], "unknown_type") is False


class TestIsExpectedDecision:
    def test_correct_decision(self):
        assert is_expected_decision("missing_settlement", "ABSTAIN") is True

    def test_abstain_always_correct_for_corrupt(self):
        """Conservative abstain on any corrupt record is acceptable."""
        for gen_type in CORRUPTION_MAPPINGS:
            assert is_expected_decision(gen_type, "ABSTAIN") is True

    def test_wrong_decision(self):
        assert is_expected_decision("amount_mismatch", "AUTO_MATCH") is False

    def test_unknown_type(self):
        assert is_expected_decision("unknown", "HUMAN_REVIEW") is False


class TestSeedClassification:
    def test_calibration_seeds(self):
        for s in CALIBRATION_SEEDS:
            assert classify_seed(s) == "calibration"

    def test_evaluation_seeds(self):
        for s in EVALUATION_SEEDS:
            assert classify_seed(s) == "evaluation"

    def test_holdout_seed(self):
        assert classify_seed(HOLDOUT_SEED) == "holdout"

    def test_unknown_seed(self):
        assert classify_seed(12345) == "unknown"

    def test_holdout_guard_raises(self):
        with pytest.raises(ValueError, match="holdout"):
            assert_not_holdout(HOLDOUT_SEED)

    def test_non_holdout_does_not_raise(self):
        assert_not_holdout(42)   # should not raise
        assert_not_holdout(100)
