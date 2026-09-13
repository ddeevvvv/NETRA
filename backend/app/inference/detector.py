"""
IBVAP Detector — YOLOv8 inference wrapper.

Design choices:
- Uses ultralytics (YOLOv8) because it provides a clean Python API, handles
  model download automatically, and works identically on CPU and CUDA.
- Model: yolov8n (nano) by default for CPU-constrained edge deployment.
  To swap to a larger model on a GPU node, change MODEL_NAME to "yolov8s.pt",
  "yolov8m.pt", or "yolov8l.pt" — no other code changes needed.
- Filters only COCO classes relevant to AGENTS.md: person + 4 vehicle types.
- Min-bbox filter suppresses tiny detections that are likely noise from distant
  objects or compression artifacts.
"""
import logging
import time
from typing import List, Dict, Any, Optional

import cv2
import numpy as np
import torch
from ultralytics import YOLO

logger = logging.getLogger("ibvap.inference.detector")

# COCO class indices kept per AGENTS.md scope
_COCO_KEEP = {
    0: "person",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}

# NOTE: Change to "yolov8s.pt" / "yolov8m.pt" when a GPU is available
MODEL_NAME = "yolov8n.pt"


class Detector:
    def __init__(
        self,
        model_name: str = MODEL_NAME,
        confidence_threshold: float = 0.5,
        min_bbox_area: int = 800,   # pixels² — suppress tiny distant objects
    ):
        self.confidence_threshold = confidence_threshold
        self.min_bbox_area = min_bbox_area

        # Auto-detect device
        if torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"

        logger.info(f"[Detector] Loading {model_name} on device={self.device}")
        t0 = time.perf_counter()
        self.model = YOLO(model_name)
        self.model.to(self.device)
        load_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"[Detector] Model loaded in {load_ms:.0f}ms on {self.device.upper()}")

    def detect(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """
        Run YOLOv8 inference on a BGR frame.
        Returns list of dicts: {bbox, confidence, class_id, object_class}.
        """
        t0 = time.perf_counter()
        results = self.model(frame, verbose=False, conf=self.confidence_threshold, device=self.device)
        latency_ms = (time.perf_counter() - t0) * 1000

        detections = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls_id = int(box.cls[0])
                if cls_id not in _COCO_KEEP:
                    continue
                conf = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                # Minimum bounding-box area filter
                area = (x2 - x1) * (y2 - y1)
                if area < self.min_bbox_area:
                    continue

                detections.append({
                    "bbox": [x1, y1, x2, y2],
                    "confidence": round(conf, 4),
                    "class_id": cls_id,
                    "object_class": _COCO_KEEP[cls_id],
                    "latency_ms": round(latency_ms, 1),
                })

        return detections
