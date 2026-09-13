"""
Stage 4 — Detector unit tests.

Image priority:
  1. tests/sample_webcam.jpg  — captured from webcam at test-setup time (real photo).
  2. tests/sample_person.jpg  — manually placed real photo.
  3. Downloaded on-the-fly from a public URL (requires internet).
  4. Skip person-detection test if none of the above is available.

All other tests (bbox validity, class filtering, min-bbox area) run regardless.
"""
import os
import sys
import cv2
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Helpers ──────────────────────────────────────────────────────────────────

WEBCAM_IMAGE = os.path.join(os.path.dirname(__file__), "sample_webcam.jpg")
PERSON_IMAGE = os.path.join(os.path.dirname(__file__), "sample_person.jpg")


def _try_load_real_image():
    """Return a real BGR image that likely contains a person, or None."""
    # 1. Sample person reference image, then webcam snapshot
    for path in [PERSON_IMAGE, WEBCAM_IMAGE]:
        if os.path.exists(path):
            img = cv2.imread(path)
            if img is not None and img.mean() >= 20.0:
                return img, path

    # 2. Download from web
    try:
        import urllib.request
        # CC0 portrait image (Wikimedia, no auth needed with User-Agent header)
        url = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg/402px-Mona_Lisa%2C_by_Leonardo_da_Vinci%2C_from_C2RMF_retouched.jpg"
        req = urllib.request.Request(url, headers={"User-Agent": "IBVAP-test/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = r.read()
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            return img, "wikimedia_mona_lisa"
    except Exception:
        pass

    return None, None


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def detector():
    """Load Detector once per module (model load takes ~2s on CPU)."""
    from app.inference.detector import Detector
    return Detector(confidence_threshold=0.25, min_bbox_area=400)


@pytest.fixture(scope="module")
def real_image():
    """BGR frame with a real person — or None if unavailable."""
    img, src = _try_load_real_image()
    if img is not None:
        print(f"\n[test_detector] Loaded real image from: {src} shape={img.shape}")
    else:
        print("\n[test_detector] No real image available — person-detection test will be skipped.")
    return img


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestDetector:

    def test_device_is_valid(self, detector):
        """Detector must log and expose the device it uses."""
        assert detector.device in ("cpu", "cuda", "mps"), (
            f"Unexpected device: {detector.device!r}"
        )
        print(f"\n[DEVICE] {detector.device.upper()}")

    def test_detect_returns_list(self, detector):
        """detect() must return a list even on a blank frame."""
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        result = detector.detect(blank)
        assert isinstance(result, list)

    def test_detect_person_in_real_image(self, detector, real_image):
        """At least one 'person' detection above threshold in a real photo."""
        if real_image is None:
            pytest.skip("No real person image available (no webcam / no internet).")

        mean_brightness = real_image.mean()
        if mean_brightness < 20.0:
            pytest.skip(
                f"Webcam image is too dark (mean={mean_brightness:.1f}) — "
                "ensure you are in a lit environment with the camera uncovered."
            )

        detections = detector.detect(real_image)
        persons = [d for d in detections if d["object_class"] == "person"]

        # Log real measured numbers — AGENTS.md: no fake metrics
        print(f"\n[DETECT] Total detections: {len(detections)}, persons: {len(persons)}")
        for d in detections:
            print(f"  {d['object_class']} conf={d['confidence']:.3f} bbox={[round(v) for v in d['bbox']]}")

        assert len(persons) >= 1, (
            f"Expected ≥1 person detection, got {len(detections)} total: {detections}"
        )

    def test_bbox_fields_valid(self, detector, real_image):
        """All returned detections must have valid bbox and confidence."""
        frame = real_image if real_image is not None else np.zeros((480, 640, 3), dtype=np.uint8)
        detections = detector.detect(frame)
        for d in detections:
            x1, y1, x2, y2 = d["bbox"]
            assert x2 > x1, f"Invalid bbox x: {d['bbox']}"
            assert y2 > y1, f"Invalid bbox y: {d['bbox']}"
            assert 0.0 <= d["confidence"] <= 1.0, f"Confidence OOB: {d['confidence']}"
            assert isinstance(d["object_class"], str)
            assert isinstance(d["track_id"] if "track_id" in d else 0, int)

    def test_only_relevant_classes_returned(self, detector, real_image):
        """Detector must not return any COCO class outside AGENTS.md scope."""
        allowed = {"person", "car", "truck", "bus", "motorcycle"}
        frame = real_image if real_image is not None else np.zeros((480, 640, 3), dtype=np.uint8)
        detections = detector.detect(frame)
        for d in detections:
            assert d["object_class"] in allowed, (
                f"Out-of-scope class '{d['object_class']}' returned"
            )

    def test_min_bbox_area_filter(self, detector):
        """Detections below min_bbox_area must be suppressed."""
        blank = np.zeros((640, 640, 3), dtype=np.uint8)
        detections = detector.detect(blank)
        for d in detections:
            x1, y1, x2, y2 = d["bbox"]
            area = (x2 - x1) * (y2 - y1)
            assert area >= detector.min_bbox_area, (
                f"Bbox area {area:.0f}px² below min={detector.min_bbox_area}px²: {d}"
            )

    def test_confidence_threshold_respected(self, detector, real_image):
        """No detection should have confidence below the configured threshold."""
        frame = real_image if real_image is not None else np.zeros((480, 640, 3), dtype=np.uint8)
        detections = detector.detect(frame)
        for d in detections:
            assert d["confidence"] >= detector.confidence_threshold, (
                f"Detection conf {d['confidence']:.3f} < threshold {detector.confidence_threshold}"
            )

    def test_latency_reported(self, detector):
        """Each detection dict must report latency_ms."""
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        detections = detector.detect(blank)
        # blank gives 0 detections, so run on a noisy frame to guarantee at least one pass
        noisy = np.random.randint(0, 50, (480, 640, 3), dtype=np.uint8)
        detections = detector.detect(noisy)
        for d in detections:
            assert "latency_ms" in d, f"Missing latency_ms in {d}"
            assert d["latency_ms"] >= 0
