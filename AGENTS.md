# IBVAP — Intelligent Border Video Analytics Platform

## What this project is
AI-based video analytics middleware that ingests existing IP-camera RTSP/ONVIF streams
and adds real-time human/vehicle detection+tracking, virtual-fence intrusion detection,
ANPR, face detection, night-mode handling, and human-acknowledged alerting — without
replacing existing NVR infrastructure. Built for SIH 2026.

## Architecture (do not deviate without asking)
Camera (RTSP/ONVIF) → Stream Ingestion → AI Inference (YOLOv8/11) → Tracking (ByteTrack)
→ Rules/Zone Engine → Event Engine → PostgreSQL + Object Storage → FastAPI → React Dashboard

## Tech stack (fixed — do not substitute without asking)
- AI/CV: Python, PyTorch, Ultralytics YOLO, OpenCV, ONNX Runtime
- Tracking: ByteTrack
- OCR/ANPR: PaddleOCR
- Face: RetinaFace (detection) + ArcFace/InsightFace (recognition)
- Backend: FastAPI
- DB: PostgreSQL
- Messaging: Redis pub/sub
- Frontend: React
- Deployment: Docker Compose

## Event schema (the single source of truth — every module must conform to this)
POST /api/v1/events
{
  "camera_id": "CAM-07", "type": "INTRUSION", "severity": "CRITICAL",
  "timestamp": "2026-09-11T12:52:03Z", "object_type": "person",
  "track_id": 17, "confidence": 0.94, "zone_id": "Z-01",
  "evidence": {"snapshot_uri": "...", "clip_uri": "..."},
  "metadata": {"direction": "NORTHBOUND"}
}


## Design principles (non-negotiable)
- Human-in-the-loop: no autonomous actions, every alert requires operator acknowledgment.
- Edge-first: system must run standalone without internet/central server connectivity.
- Explainable alerts: every alert must show which rule/zone/threshold fired it.
- Don't overclaim accuracy — log real measured numbers, no hardcoded fake metrics.

## Build style
- Work in small, testable stages. After each stage, run it and show me it actually works
  before moving to the next stage.
- Prefer editing/extending existing files over creating parallel/duplicate ones.
- Keep Docker Compose as the single way to run the whole stack locally.