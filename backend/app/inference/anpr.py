"""
IBVAP ANPR (Automatic Number Plate Recognition) Module using PaddleOCR.

Design:
- Uses PaddleOCR text detection and recognition on cropped vehicle regions.
- CPU inference mode explicitly to match lightweight edge requirements.
- Applies standard Indian license plate format validation and OCR error recovery heuristics.
- Standard Indian Format: State code (2 letters) + District code (1-2 digits) + Series (0-3 letters) + Number (4 digits).
  e.g., KA05NB4912, DL01AB1234, MH12DE5678, HR26DQ5551.
"""
import os
# Disable MKLDNN/oneDNN to avoid Windows PIR attribute runtime errors with PaddlePaddle 3.x
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_DISABLE_MKLDNN"] = "1"

import re
import logging
import time
from typing import Optional, Dict, Any, List, Tuple
import cv2
import numpy as np

logger = logging.getLogger("ibvap.inference.anpr")

# Standard Indian License Plate regex
# 2-letter State code + 1-2 digit District code (01-99 or 1-9) + optional 0-3 letter Series + 4-digit Number
INDIAN_PLATE_REGEX = re.compile(r"^[A-Z]{2}(?:[0-9]{2}|[1-9])[A-Z]{0,3}[0-9]{4}$")

# Indian State/UT Codes for validation
INDIAN_STATE_CODES = {
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN", "GA", "GJ", "HR",
    "HP", "JH", "JK", "KA", "KL", "LA", "LD", "MP", "MH", "MN", "ML", "MZ", "NL",
    "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK", "UA", "UP", "WB"
}

DIGIT_FIXES = {'O': '0', 'Q': '0', 'D': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'B': '8', 'G': '6'}
LETTER_FIXES = {'0': 'O', '1': 'I', '5': 'S', '8': 'B', '6': 'G', '2': 'Z'}


def clean_text(raw: str) -> str:
    """Removes spaces, hyphens, and non-alphanumeric noise, converting to uppercase."""
    return re.sub(r"[^A-Za-z0-9]", "", raw).upper()


def normalize_and_validate_plate(candidate: str) -> Optional[str]:
    """
    Validates and normalizes candidate plate text against standard Indian plate format.
    Applies smart OCR character confusion fixes (e.g. S->5 in digit positions, 0->O in letter positions).
    """
    clean = clean_text(candidate)
    if not clean or len(clean) < 7 or len(clean) > 11:
        return None

    # 1. Heuristic repair for common OCR confusion (e.g. KA0SNB4912 -> KA05NB4912)
    # Expected structure: [2 letters] + [1 or 2 digits] + [0-3 letters] + [4 digits]
    prefix_len = len(clean) - 4
    if prefix_len >= 3:
        prefix = clean[:prefix_len]
        suffix = clean[prefix_len:]

        # Suffix must be 4 digits
        fixed_suffix = "".join(DIGIT_FIXES.get(c, c) for c in suffix)
        state_code = "".join(LETTER_FIXES.get(c, c) for c in prefix[:2])

        if fixed_suffix.isdigit() and len(fixed_suffix) == 4 and state_code.isalpha() and len(state_code) == 2:
            remainder = prefix[2:]
            for dist_len in (2, 1):
                if len(remainder) >= dist_len:
                    dist_part = remainder[:dist_len]
                    series_part = remainder[dist_len:]

                    fixed_dist = "".join(DIGIT_FIXES.get(c, c) for c in dist_part)
                    fixed_series = "".join(LETTER_FIXES.get(c, c) for c in series_part)

                    if fixed_dist.isdigit() and (fixed_series.isalpha() or not fixed_series) and len(fixed_series) <= 3:
                        candidate_fixed = f"{state_code}{fixed_dist}{fixed_series}{fixed_suffix}"
                        if INDIAN_PLATE_REGEX.match(candidate_fixed) and state_code in INDIAN_STATE_CODES:
                            return candidate_fixed

    # 2. Direct match check
    if INDIAN_PLATE_REGEX.match(clean):
        if clean[:2] in INDIAN_STATE_CODES:
            return clean

    return None


class ANPRProcessor:
    def __init__(self, confidence_threshold: float = 0.50):
        self.confidence_threshold = confidence_threshold
        self._ocr = None
        self._init_error = None

    @staticmethod
    def _apply_cpu_compatibility():
        """Ensure Paddle CPU predictor does not crash on Windows due to oneDNN/PIR instruction mismatches."""
        try:
            import paddle.inference as p_inf
            if not getattr(p_inf, "_ibvap_cpu_patched", False):
                orig_create_pred = p_inf.create_predictor

                def patched_create_pred(config):
                    if hasattr(config, "disable_onednn"):
                        config.disable_onednn()
                    if hasattr(config, "disable_mkldnn"):
                        config.disable_mkldnn()
                    if hasattr(config, "enable_new_ir"):
                        config.enable_new_ir(False)
                    return orig_create_pred(config)

                p_inf.create_predictor = patched_create_pred
                p_inf._ibvap_cpu_patched = True
        except Exception as e:
            logger.debug(f"[ANPRProcessor] CPU compatibility hook: {e}")

    def _get_ocr(self):
        """Lazy-load PaddleOCR in CPU mode."""
        if self._ocr is not None:
            return self._ocr
        if self._init_error is not None:
            return None

        try:
            self._apply_cpu_compatibility()
            from paddleocr import PaddleOCR
            # Initialize in CPU mode without angle classifier to keep inference fast
            self._ocr = PaddleOCR(use_angle_cls=False, lang="en")
            logger.info("[ANPRProcessor] PaddleOCR loaded successfully in CPU mode.")
            return self._ocr
        except Exception as e:
            self._init_error = str(e)
            logger.warning(f"[ANPRProcessor] PaddleOCR failed to initialize: {e}")
            return None

    def process(self, vehicle_crop: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Runs text detection and recognition on cropped vehicle region.

        Args:
            vehicle_crop: BGR image crop of detected vehicle.

        Returns:
            Dict with {plate_text, confidence, raw_text, bbox} if valid plate found, else None.
        """
        if vehicle_crop is None or vehicle_crop.size == 0:
            return None

        h, w = vehicle_crop.shape[:2]
        if h < 20 or w < 30:
            return None

        ocr = self._get_ocr()
        if ocr is None:
            return None

        t0 = time.perf_counter()
        try:
            # Run OCR on crop (PaddleOCR 3.x uses ocr(crop), older versions accepted cls=False)
            try:
                results = ocr.ocr(vehicle_crop)
            except TypeError:
                results = ocr.ocr(vehicle_crop, cls=False)
        except Exception as e:
            logger.debug(f"[ANPRProcessor] OCR inference error: {e}")
            return None

        latency_ms = (time.perf_counter() - t0) * 1000

        if not results:
            return None

        best_match = None
        highest_conf = 0.0

        # Extract text entries across PaddleOCR versions
        candidates: List[Tuple[str, float, Any]] = []

        first_elem = results[0]
        # PaddleOCR 3.x / paddlex dict result format: [{'rec_texts': [...], 'rec_scores': [...], 'rec_boxes': [...]}]
        if isinstance(first_elem, dict) and "rec_texts" in first_elem:
            rec_texts = first_elem.get("rec_texts", [])
            rec_scores = first_elem.get("rec_scores", [])
            rec_polys = first_elem.get("rec_polys", [None] * len(rec_texts))
            for text, score, poly in zip(rec_texts, rec_scores, rec_polys):
                candidates.append((str(text), float(score), poly))
        # PaddleOCR 2.x list result format: [[[box, (text, score)], ...]]
        elif isinstance(first_elem, (list, tuple)):
            for line in first_elem:
                if not line or len(line) < 2:
                    continue
                box = line[0]
                text_conf = line[1]
                if not text_conf or len(text_conf) < 2:
                    continue
                candidates.append((str(text_conf[0]), float(text_conf[1]), box))

        for raw_text, conf, box in candidates:
            validated_plate = normalize_and_validate_plate(raw_text)

            if validated_plate and conf >= self.confidence_threshold:
                if conf > highest_conf:
                    highest_conf = conf
                    best_match = {
                        "plate_text": validated_plate,
                        "confidence": round(conf, 3),
                        "raw_text": raw_text,
                        "crop_bbox": box.tolist() if hasattr(box, "tolist") else box,
                        "latency_ms": round(latency_ms, 1),
                    }

        if best_match:
            logger.info(
                f"[ANPRProcessor] Read plate '{best_match['plate_text']}' "
                f"(raw='{best_match['raw_text']}', conf={best_match['confidence']}) in {latency_ms:.1f}ms"
            )

        return best_match
