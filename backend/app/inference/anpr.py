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


from concurrent.futures import ProcessPoolExecutor

_ocr_worker_instance = None


def _process_crop_in_worker(vehicle_crop: np.ndarray) -> List[Tuple[str, float, Any]]:
    global _ocr_worker_instance
    if _ocr_worker_instance is None:
        import os
        os.environ["FLAGS_use_mkldnn"] = "0"
        os.environ["PADDLE_DISABLE_MKLDNN"] = "1"
        os.environ["OMP_NUM_THREADS"] = "1"
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        from paddleocr import PaddleOCR
        _ocr_worker_instance = PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="en",
        )

    try:
        results = _ocr_worker_instance.ocr(vehicle_crop)
    except Exception:
        return []

    candidates = []
    if not results:
        return candidates

    first_elem = results[0]
    if isinstance(first_elem, dict) and "rec_texts" in first_elem:
        rec_texts = first_elem.get("rec_texts", [])
        rec_scores = first_elem.get("rec_scores", [])
        rec_polys = first_elem.get("rec_polys", [None] * len(rec_texts))
        for text, score, poly in zip(rec_texts, rec_scores, rec_polys):
            poly_list = poly.tolist() if hasattr(poly, "tolist") else poly
            candidates.append((str(text), float(score), poly_list))
    elif isinstance(first_elem, (list, tuple)):
        for line in first_elem:
            if not line or len(line) < 2:
                continue
            box = line[0]
            text_conf = line[1]
            if not text_conf or len(text_conf) < 2:
                continue
            box_list = box.tolist() if hasattr(box, "tolist") else box
            candidates.append((str(text_conf[0]), float(text_conf[1]), box_list))

    return candidates


class ANPRProcessor:
    def __init__(self, confidence_threshold: float = 0.50):
        self.confidence_threshold = confidence_threshold
        self._executor: Optional[ProcessPoolExecutor] = None

    def _get_executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(max_workers=1)
        return self._executor

    def process(self, vehicle_crop: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Runs text detection and recognition on cropped vehicle region in a separate process.

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

        t0 = time.perf_counter()
        try:
            ex = self._get_executor()
            future = ex.submit(_process_crop_in_worker, vehicle_crop)
            candidates = future.result(timeout=2.0)
        except Exception as e:
            logger.debug(f"[ANPRProcessor] OCR inference error: {e}")
            return None

        latency_ms = (time.perf_counter() - t0) * 1000

        if not candidates:
            return None

        best_match = None
        highest_conf = 0.0

        for raw_text, conf, box in candidates:
            validated_plate = normalize_and_validate_plate(raw_text)

            if validated_plate and conf >= self.confidence_threshold:
                if conf > highest_conf:
                    highest_conf = conf
                    best_match = {
                        "plate_text": validated_plate,
                        "confidence": round(conf, 3),
                        "raw_text": raw_text,
                        "crop_bbox": box,
                        "latency_ms": round(latency_ms, 1),
                    }

        if best_match:
            logger.info(
                f"[ANPRProcessor] Read plate '{best_match['plate_text']}' "
                f"(raw='{best_match['raw_text']}', conf={best_match['confidence']}) in {latency_ms:.1f}ms"
            )

        return best_match

