"""
IBVAP FaceDetector — Lightweight face detection module.

Design choices:
- Stage 7 scope: Face DETECTION only (bounding boxes on faces).
  No facial recognition, embeddings, or watchlist matching.
- Edge-first & zero-dependency: Uses OpenCV's built-in DNN face detector
  (res10_300x300_ssd Caffe model) if available, with automatic fallback
  to OpenCV's built-in Haar Cascade classifier (cv2.data.haarcascades)
  so it runs completely offline without external package installations.
- Consistent API: returns a list of dicts with keys:
  'bbox' ([x1, y1, x2, y2]), 'confidence', 'class_id', 'object_class' ("face"), 'latency_ms'.
- Supports confidence_threshold (default 0.5) and min_bbox_area filter.
"""
import logging
import os
import time
from typing import List, Dict, Any, Optional

import cv2
import numpy as np

logger = logging.getLogger("ibvap.inference.face_detector")


class FaceDetector:
    def __init__(
        self,
        confidence_threshold: float = 0.5,
        min_bbox_area: int = 400,   # pixels² — suppress tiny false positives
        model_dir: Optional[str] = None,
    ):
        self.confidence_threshold = confidence_threshold
        self.min_bbox_area = min_bbox_area
        self.backend = "haar"
        self.net = None
        self.cascade = None

        # Determine paths for DNN model
        if model_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_dir = os.path.join(base_dir, "models", "face_detector")

        proto_path = os.path.join(model_dir, "deploy.prototxt")
        model_path = os.path.join(model_dir, "res10_300x300_ssd_iter_140000.caffemodel")

        # 1. Try OpenCV DNN face detector if model weights exist
        if os.path.isfile(proto_path) and os.path.isfile(model_path):
            try:
                self.net = cv2.dnn.readNetFromCaffe(proto_path, model_path)
                self.backend = "dnn"
                logger.info(f"[FaceDetector] Loaded OpenCV DNN Face Detector from {model_dir}")
            except Exception as e:
                logger.warning(f"[FaceDetector] Failed to load Caffe DNN model: {e}")

        # 2. Fallback to OpenCV Haar Cascade (ships natively with opencv-python)
        if self.net is None:
            cascade_dir = getattr(cv2.data, "haarcascades", "")
            cascade_file = os.path.join(cascade_dir, "haarcascade_frontalface_default.xml")
            if os.path.isfile(cascade_file):
                self.cascade = cv2.CascadeClassifier(cascade_file)
                self.backend = "haar"
                logger.info(f"[FaceDetector] Using built-in Haar Cascade from {cascade_file}")
            else:
                logger.warning(f"[FaceDetector] Haar cascade not found at {cascade_file}")

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Run face detection inference on a BGR frame.
        Returns list of dicts: {bbox, confidence, class_id, object_class, latency_ms}.
        """
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        if h == 0 or w == 0:
            return []

        t0 = time.perf_counter()
        detections: List[Dict[str, Any]] = []

        if self.backend == "dnn" and self.net is not None:
            blob = cv2.dnn.blobFromImage(
                cv2.resize(frame, (300, 300)),
                1.0,
                (300, 300),
                (104.0, 177.0, 123.0)
            )
            self.net.setInput(blob)
            out = self.net.forward()

            for i in range(out.shape[2]):
                conf = float(out[0, 0, i, 2])
                if conf < self.confidence_threshold:
                    continue

                x1 = float(max(0, min(w, out[0, 0, i, 3] * w)))
                y1 = float(max(0, min(h, out[0, 0, i, 4] * h)))
                x2 = float(max(0, min(w, out[0, 0, i, 5] * w)))
                y2 = float(max(0, min(h, out[0, 0, i, 6] * h)))

                area = (x2 - x1) * (y2 - y1)
                if area < self.min_bbox_area:
                    continue

                detections.append({
                    "bbox": [x1, y1, x2, y2],
                    "confidence": round(conf, 4),
                    "class_id": 0,
                    "object_class": "face",
                })

        elif self.cascade is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            try:
                rects, _, weights = self.cascade.detectMultiScale3(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=7,
                    minSize=(48, 48),
                    outputRejectLevels=True
                )
            except Exception:
                rects = self.cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=7,
                    minSize=(48, 48)
                )
                weights = [10.0] * len(rects)

            for idx, (x, y, bw, bh) in enumerate(rects):
                x1, y1 = float(x), float(y)
                x2, y2 = float(x + bw), float(y + bh)
                area = bw * bh
                if area < self.min_bbox_area:
                    continue

                raw_w = float(weights[idx]) if idx < len(weights) else 10.0
                if raw_w < 6.0:  # Suppress low-stage / weakly supported candidate windows
                    continue
                # Map classifier weight to confidence in [0.5, 0.98]
                conf = min(0.98, max(0.5, float(1.0 / (1.0 + np.exp(-raw_w / 4.0)))))
                if conf < self.confidence_threshold:
                    continue

                detections.append({
                    "bbox": [x1, y1, x2, y2],
                    "confidence": round(conf, 4),
                    "class_id": 0,
                    "object_class": "face",
                })

        latency_ms = (time.perf_counter() - t0) * 1000
        for d in detections:
            d["latency_ms"] = round(latency_ms, 1)

        return detections
