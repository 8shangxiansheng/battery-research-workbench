"""Tests for Feature Definition Registry V2 (BRW-013X V2 §39)."""

from __future__ import annotations

from battery_workbench.features.definitions_v2 import (
    FD_DEFINITIONS,
    FORMULA_POLICY_VERSION,
    FORMULA_SOURCE_ID,
    TD_DEFINITIONS,
    default_registry,
)


class TestRegistryContents:
    def test_19_td_definitions(self):
        assert len(TD_DEFINITIONS) == 19

    def test_14_fd_definitions(self):
        assert len(FD_DEFINITIONS) == 14

    def test_all_have_bilingual_names(self):
        for d in (*TD_DEFINITIONS, *FD_DEFINITIONS):
            assert d.display_name_en
            assert d.display_name_zh
            assert d.display_name_en != d.display_name_zh

    def test_all_reference_formula_source(self):
        for d in (*TD_DEFINITIONS, *FD_DEFINITIONS):
            assert d.formula_source_id == FORMULA_SOURCE_ID
            assert d.formula_policy_version == FORMULA_POLICY_VERSION

    def test_td_family_codes_in_order(self):
        expected = [
            "TDM", "TDSTD", "TDRMS2", "TDMAV", "TDS", "TDK", "TDV",
            "TDMax", "TDMin", "TDPP", "TDEI", "TDWC", "TDSAVR",
            "TDMSR", "TDMAR", "TDMRR", "TDHSK", "TDKSR", "TDHMER",
        ]
        assert [d.code for d in TD_DEFINITIONS] == expected

    def test_fd_family_codes_in_order(self):
        expected = [
            "FDM", "FDV", "FDS", "FDK", "FDAF", "FDSD", "FDRMS",
            "FDSR", "FDCF", "FDFSDR", "FDFS", "FDFK", "FDEQ", "FDFWM",
        ]
        assert [d.code for d in FD_DEFINITIONS] == expected


class TestAliasPolicy:
    """§10 — do not blindly alias."""

    def test_tdrms2_is_not_aliased_to_waveform_rms(self):
        reg = default_registry()
        assert reg.get("TDRMS2").existing_alias is None

    def test_tdei_is_not_aliased_to_energy_sum_sq(self):
        reg = default_registry()
        assert reg.get("TDEI").existing_alias is None

    def test_semantic_identical_features_aliased(self):
        reg = default_registry()
        assert reg.get("TDM").existing_alias == "waveform_mean_a_u"
        assert reg.get("TDSTD").existing_alias == "waveform_std_a_u"
        assert reg.get("TDMax").existing_alias == "waveform_max_a_u"
        assert reg.get("TDMin").existing_alias == "waveform_min_a_u"
        assert reg.get("TDPP").existing_alias == "waveform_p2p_a_u"


class TestStatusLifecycle:
    def test_default_tdk_tdv_parity_pending(self):
        reg = default_registry()
        assert reg.get("TDK").definition_status == "DEFINED_NOT_VALIDATED"
        assert reg.get("TDK").parity_status == "MATLAB_PARITY_REQUIRED"
        assert reg.get("TDV").definition_status == "DEFINED_NOT_VALIDATED"

    def test_others_validated_after_golden(self):
        reg = default_registry()
        for code in reg.codes():
            if code in ("TDK", "TDV"):
                continue
            assert reg.get(code).definition_status == "DEFINED_AND_VALIDATED"

    def test_promote_validated(self):
        reg = default_registry()
        reg.promote_validated("TDK")
        assert reg.get("TDK").definition_status == "DEFINED_AND_VALIDATED"


class TestCatalogue:
    def test_catalogue_bilingual_api_shape(self):
        reg = default_registry()
        cat = reg.catalogue()
        assert len(cat) == 33
        entry = next(e for e in cat if e["code"] == "TDSTD")
        assert entry["display_name_en"] == "Standard Deviation"
        assert entry["display_name_zh"] == "标准差"
        assert entry["family"] == "TD"
        assert entry["units"]
        assert entry["formula_source_id"] == FORMULA_SOURCE_ID
        assert entry["definition_status"] in (
            "DEFINED_NOT_VALIDATED", "DEFINED_AND_VALIDATED"
        )

    def test_no_duplicate_codes(self):
        reg = default_registry()
        assert len(reg.codes()) == len(set(reg.codes())) == 33


class TestFDSpectralTransformRequirement:
    def test_fd_requires_spectral_transform(self):
        for d in FD_DEFINITIONS:
            assert "spectral_transform_id" in d.required_inputs

    def test_td_does_not_require_spectral_transform(self):
        for d in TD_DEFINITIONS:
            assert "spectral_transform_id" not in d.required_inputs
