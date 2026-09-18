import os
import cv2
import numpy as np
import pytest

from app.inference.face_detector import FaceDetector


@pytest.fixture
def face_detector():
    return FaceDetector(confidence_threshold=0.5, min_bbox_area=200)


def test_face_detector_detect_on_sample_image(face_detector):
    """Assert at least one face is detected above threshold on a test image with a clear face."""
    sample_path = os.path.join(os.path.dirname(__file__), "sample_person.jpg")
    assert os.path.exists(sample_path), f"Test image missing: {sample_path}"

    frame = cv2.imread(sample_path)
    assert frame is not None, "Failed to load sample test image"

    detections = face_detector.detect(frame)
    assert len(detections) >= 1, "Expected at least one face detection in sample image"

    for det in detections:
        assert "bbox" in det
        assert "confidence" in det
        assert "object_class" in det
        assert det["object_class"] == "face"
        assert det["confidence"] >= 0.5
        assert len(det["bbox"]) == 4
        x1, y1, x2, y2 = det["bbox"]
        assert x2 > x1
        assert y2 > y1
        assert (x2 - x1) * (y2 - y1) >= face_detector.min_bbox_area


def test_face_detector_empty_and_blank_frame(face_detector):
    """Assert blank and invalid frames return empty lists gracefully."""
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    detections = face_detector.detect(blank)
    assert detections == []

    assert face_detector.detect(None) == []
    assert face_detector.detect(np.array([])) == []


def test_face_detector_threshold_filtering():
    """Assert confidence and bbox area filters operate correctly."""
    strict_detector = FaceDetector(confidence_threshold=0.999, min_bbox_area=1000000)
    sample_path = os.path.join(os.path.dirname(__file__), "sample_person.jpg")
    frame = cv2.imread(sample_path)

    detections = strict_detector.detect(frame)
    assert len(detections) == 0
