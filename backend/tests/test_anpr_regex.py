import pytest
from app.inference.anpr import normalize_and_validate_plate, clean_text


class TestPlateNormalizationAndRegex:
    def test_clean_text(self):
        assert clean_text("KA-05 NB 4912") == "KA05NB4912"
        assert clean_text("dl.01_ab-1234") == "DL01AB1234"
        assert clean_text("  MH 12   DE 5678 ") == "MH12DE5678"

    def test_valid_indian_plates_direct_match(self):
        valid_samples = [
            "KA05NB4912",
            "DL01AB1234",
            "MH12DE5678",
            "HR26DQ5551",
            "UP32AA1111",
            "WB02B1234",
            "TN07CD9876",
            "GJ01EF4321",
            "RJ14GH7777",
            "PB65XY8888",
        ]
        for plate in valid_samples:
            result = normalize_and_validate_plate(plate)
            assert result == plate, f"Expected {plate} to match, got {result}"

    def test_plates_with_spaces_and_hyphens(self):
        assert normalize_and_validate_plate("KA-05-NB-4912") == "KA05NB4912"
        assert normalize_and_validate_plate("DL 01 AB 1234") == "DL01AB1234"
        assert normalize_and_validate_plate("MH-12 DE.5678") == "MH12DE5678"

    def test_ocr_confusion_character_repair(self):
        # S read instead of 5 in district digits: KA0SNB4912 -> KA05NB4912
        assert normalize_and_validate_plate("KA0SNB4912") == "KA05NB4912"

        # O read instead of 0 in district / number digits
        assert normalize_and_validate_plate("KAO5NB4912") == "KA05NB4912"
        assert normalize_and_validate_plate("DL01AB123O") == "DL01AB1230"

        # I/L read instead of 1 in registration number
        assert normalize_and_validate_plate("HR26DQ555I") == "HR26DQ5551"
        assert normalize_and_validate_plate("HR26DQ555L") == "HR26DQ5551"

        # B read instead of 8 in registration number
        assert normalize_and_validate_plate("MH12DE567B") == "MH12DE5678"

    def test_invalid_plates_rejected(self):
        invalid_samples = [
            "INVALID_PLATE",
            "ZZ99ZZ9999",  # ZZ is not a valid Indian state code
            "12345678",
            "ABCDEFG",
            "KA",
            "KA05",
            "KA05NB4912345",  # Too long
            "",
            "HELLO WORLD",
        ]
        for sample in invalid_samples:
            assert normalize_and_validate_plate(sample) is None, f"Expected {sample} to be rejected"
