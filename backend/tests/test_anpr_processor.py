import cv2
import numpy as np
import pytest
from app.inference.anpr import ANPRProcessor


def create_synthetic_plate_image(plate_text="KA05NB4912", width=360, height=120):
    """Generates a realistic synthetic Indian license plate image for testing."""
    # White background plate
    img = np.ones((height, width, 3), dtype=np.uint8) * 255

    # Black border
    cv2.rectangle(img, (4, 4), (width - 5, height - 5), (0, 0, 0), 3)

    # Blue IND badge on left
    cv2.rectangle(img, (8, 8), (45, height - 9), (180, 50, 0), -1)
    cv2.putText(img, "IND", (12, height // 2 + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

    # Plate text in bold black
    cv2.putText(
        img,
        plate_text,
        (55, height // 2 + 15),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1,
        (0, 0, 0),
        3,
        cv2.LINE_AA,
    )
    return img


class TestANPRProcessor:
    @pytest.fixture(scope="class")
    def anpr(self):
        return ANPRProcessor(confidence_threshold=0.50)

    def test_anpr_reads_synthetic_plate(self, anpr):
        plate_img = create_synthetic_plate_image("KA05NB4912")
        result = anpr.process(plate_img)

        assert result is not None, "ANPR failed to read synthetic plate image"
        assert result["plate_text"] == "KA05NB4912"
        assert result["confidence"] > 0.50
        assert "latency_ms" in result

    def test_anpr_empty_or_invalid_crop_returns_none(self, anpr):
        # Empty array
        assert anpr.process(np.zeros((0, 0, 3), dtype=np.uint8)) is None
        # Too small image
        assert anpr.process(np.ones((10, 10, 3), dtype=np.uint8) * 255) is None
        # Plain black background (no text)
        blank = np.zeros((100, 200, 3), dtype=np.uint8)
        assert anpr.process(blank) is None
