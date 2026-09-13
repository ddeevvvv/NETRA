"""
IBVAP Tracker — ByteTrack wrapper via supervision library.

Design choice — supervision's ByteTrack vs. official ByteTrack repo:
  We use `supervision.tracker.byte_tracker.ByteTrack` because:
  1. It is pip-installable with no C++ build step (critical for Windows + Docker).
  2. The official ByteTrack repo requires a manual C++ CUDA extension that is
     brittle on Windows and fails inside multi-arch Docker images.
  3. supervision's implementation is algorithmically identical to the reference
     paper and produces stable, persistent track IDs across frames.
  4. It runs fine at 5 FPS — the C++ speedup matters mainly at 30+ FPS.

Note: supervision marked ByteTrack as deprecated in v0.28 (targeting removal
in v0.31) in favour of their new tracking API. We import directly from the
internal module path to avoid the deprecation proxy, and will migrate when
supervision v0.31 is released.
"""
import logging
import warnings
from typing import List, Dict, Any

import numpy as np
import supervision as sv

# Import directly from internal path to bypass the deprecated proxy wrapper.
# If supervision upgrades break this, fall back to: from supervision import ByteTracker
from supervision.tracker.byte_tracker.core import ByteTrack as _ByteTrack

logger = logging.getLogger("ibvap.inference.tracker")

# COCO classes kept — mirrors detector.py; imported here to avoid circular deps
_COCO_KEEP = {
    0: "person",
    2: "car",
    3: "motorcycle",
    5: "bus",
    7: "truck",
}


class Tracker:
    def __init__(
        self,
        track_activation_threshold: float = 0.25,
        lost_track_buffer: int = 30,
        minimum_matching_threshold: float = 0.8,
        frame_rate: int = 5,
    ):
        """
        Args:
            track_activation_threshold: Minimum confidence to activate a new track.
            lost_track_buffer: Frames to keep a lost track alive before dropping it.
            minimum_matching_threshold: IoU threshold for det→track association.
            frame_rate: Target FPS — used to tune the Kalman filter velocity estimates.
        """
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            self._bt = _ByteTrack(
                track_activation_threshold=track_activation_threshold,
                lost_track_buffer=lost_track_buffer,
                minimum_matching_threshold=minimum_matching_threshold,
                frame_rate=frame_rate,
            )
        logger.info(
            f"[Tracker] ByteTrack init — "
            f"activation_thresh={track_activation_threshold}, "
            f"lost_buffer={lost_track_buffer}, "
            f"frame_rate={frame_rate}"
        )

    def update(
        self,
        detections: List[Dict[str, Any]],
        frame: np.ndarray,
    ) -> List[Dict[str, Any]]:
        """
        Args:
            detections: List of dicts from Detector.detect() with keys:
                        bbox, confidence, class_id, object_class.
            frame: BGR frame (shape used for context only, pixels ignored).

        Returns:
            List of {track_id, object_class, bbox, confidence} dicts.
            track_id is stable across frames for the same physical object.
        """
        if not detections:
            # Must still call update so the Kalman filter ages out lost tracks.
            empty = sv.Detections.empty()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                self._bt.update_with_detections(empty)
            return []

        # Convert our dict format → supervision Detections dataclass
        xyxy = np.array([d["bbox"] for d in detections], dtype=np.float32)
        confs = np.array([d["confidence"] for d in detections], dtype=np.float32)
        class_ids = np.array([d["class_id"] for d in detections], dtype=int)

        sv_dets = sv.Detections(
            xyxy=xyxy,
            confidence=confs,
            class_id=class_ids,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            tracked = self._bt.update_with_detections(sv_dets)

        results = []
        for i in range(len(tracked)):
            track_id = int(tracked.tracker_id[i]) if tracked.tracker_id is not None and len(tracked.tracker_id) > i else -1
            cls_id = int(tracked.class_id[i]) if tracked.class_id is not None and len(tracked.class_id) > i else -1
            conf = float(tracked.confidence[i]) if tracked.confidence is not None and len(tracked.confidence) > i else 0.0
            bbox = tracked.xyxy[i].tolist()

            obj_class = _COCO_KEEP.get(cls_id, f"class_{cls_id}")

            results.append({
                "track_id": track_id,
                "object_class": obj_class,
                "bbox": bbox,
                "confidence": round(conf, 4),
            })

        return results
