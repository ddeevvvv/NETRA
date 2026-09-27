"""
IBVAP Evidence Exporter — Generates self-contained, official evidence packages
(PDF reports with embedded forensic frames & ZIP bundles with metadata)
for incident clusters, single events, or vehicle tracking timelines.
"""

import io
import os
import re
import json
import base64
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage,
    KeepTogether,
    HRFlowable,
)


def _decode_image_data(snapshot_uri: Optional[str]) -> Optional[io.BytesIO]:
    """
    Safely resolves a snapshot URI (base64 data URI, local path, or raw base64)
    into a valid BytesIO stream verified by PIL. Returns None if invalid or unavailable.
    """
    if not snapshot_uri or not isinstance(snapshot_uri, str):
        return None

    snapshot_uri = snapshot_uri.strip()
    if not snapshot_uri:
        return None

    try:
        # 1. Base64 data URI (e.g. data:image/jpeg;base64,....)
        if snapshot_uri.startswith("data:image"):
            b64_part = snapshot_uri.split(",", 1)[-1]
            raw_bytes = base64.b64decode(b64_part)
            bio = io.BytesIO(raw_bytes)
            img = PILImage.open(bio)
            img.verify()
            bio.seek(0)
            return bio

        # 2. Raw base64 string
        if len(snapshot_uri) > 100 and not snapshot_uri.startswith("http") and not snapshot_uri.startswith("/"):
            try:
                raw_bytes = base64.b64decode(snapshot_uri)
                bio = io.BytesIO(raw_bytes)
                img = PILImage.open(bio)
                img.verify()
                bio.seek(0)
                return bio
            except Exception:
                pass

        # 3. Local file path
        if os.path.exists(snapshot_uri):
            with open(snapshot_uri, "rb") as f:
                raw_bytes = f.read()
            bio = io.BytesIO(raw_bytes)
            img = PILImage.open(bio)
            img.verify()
            bio.seek(0)
            return bio

        # 4. HTTP/HTTPS URL
        if snapshot_uri.startswith("http://") or snapshot_uri.startswith("https://"):
            import httpx
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(snapshot_uri)
                if resp.status_code == 200:
                    bio = io.BytesIO(resp.content)
                    img = PILImage.open(bio)
                    img.verify()
                    bio.seek(0)
                    return bio
    except Exception:
        return None

    return None


def generate_evidence_pdf(
    title: str,
    package_type: str,  # "INCIDENT_CLUSTER", "VEHICLE_TRACKING", "SINGLE_EVENT"
    summary_meta: Dict[str, Any],
    events: List[Dict[str, Any]],
    generated_by: str = "Operator",
) -> bytes:
    """
    Assembles an official, multi-page PDF Evidence Package with:
    - Official IBVAP Header & Classification
    - Executive Incident Summary & Scope
    - Forensics & Telemetry Metrics Table
    - Constituent Events / Sighting Timeline
    - Embedded Frame Evidence (or explicit 'no snapshot available' notices)
    - Chain of Custody & SHA-256 Integrity Verification Block
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    c_primary = colors.HexColor("#0f172a")     # Slate 900
    c_accent = colors.HexColor("#0284c7")      # Cyan / Sky 600
    c_danger = colors.HexColor("#dc2626")      # Red 600
    c_warning = colors.HexColor("#d97706")     # Amber 600
    c_dark = colors.HexColor("#1e293b")        # Slate 800
    c_muted = colors.HexColor("#64748b")       # Slate 500
    c_border = colors.HexColor("#e2e8f0")      # Slate 200
    c_bg_light = colors.HexColor("#f8fafc")    # Slate 50
    c_bg_subtle = colors.HexColor("#f1f5f9")   # Slate 100

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=c_primary,
    )
    sub_style = ParagraphStyle(
        "DocSub",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=c_accent,
    )
    h2_style = ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=c_primary,
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=c_dark,
    )
    mono_style = ParagraphStyle(
        "DocMono",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=8,
        leading=10,
        textColor=c_dark,
    )
    alert_style = ParagraphStyle(
        "DocAlert",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=c_danger,
    )
    missing_style = ParagraphStyle(
        "DocMissing",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=10,
        textColor=c_muted,
    )

    story = []

    # ── 1. Official Header & Classification Banner ──────────────────────────
    gen_time_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_id = f"EVD-{hashlib.sha256(f'{title}-{gen_time_utc}-{len(events)}'.encode()).hexdigest()[:12].upper()}"

    header_data = [
        [
            Paragraph("<b>NETRA — IBVAP Evidence Record</b><br/><font size='7.5' color='#64748b'>INTELLIGENT BORDER VIDEO ANALYTICS PLATFORM · SIH 2026</font>", title_style),
            Paragraph(f"<b>PACKAGE ID:</b> {report_id}<br/><b>GENERATED:</b> {gen_time_utc}<br/><b>STATUS:</b> EXPORT RECORD", sub_style),
        ]
    ]

    t_header = Table(header_data, colWidths=[330, 210])
    t_header.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(t_header)
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=1.5, color=c_primary, spaceBefore=2, spaceAfter=8))

    # ── 2. Executive Incident / Investigation Summary ───────────────────────
    story.append(Paragraph("1. EXECUTIVE INVESTIGATION SUMMARY", h2_style))

    desc_text = summary_meta.get("description") or f"Forensic evidence export for {package_type.lower().replace('_', ' ')}."
    severity_val = summary_meta.get("severity", "INFO")

    summary_rows = [
        [
            Paragraph("<b>Scope / Target:</b>", body_style),
            Paragraph(f"<b>{title}</b>", body_style),
            Paragraph("<b>Classification:</b>", body_style),
            Paragraph(f"<font color='{'#dc2626' if severity_val=='CRITICAL' else '#d97706' if severity_val=='HIGH' else '#0284c7'}'><b>{severity_val}</b></font>", body_style),
        ],
        [
            Paragraph("<b>Primary Camera:</b>", body_style),
            Paragraph(f"{summary_meta.get('camera_id', 'Multi-Camera / Network')}", body_style),
            Paragraph("<b>Total Events:</b>", body_style),
            Paragraph(f"{len(events)} recorded detection{'s' if len(events)!=1 else ''}", body_style),
        ],
        [
            Paragraph("<b>Zone / Sector:</b>", body_style),
            Paragraph(f"{summary_meta.get('zone_id') or 'General Coverage'}", body_style),
            Paragraph("<b>Ack Status:</b>", body_style),
            Paragraph(f"{summary_meta.get('unacked_count', 0)} pending / {len(events) - summary_meta.get('unacked_count', 0)} acknowledged", body_style),
        ],
        [
            Paragraph("<b>Time Range:</b>", body_style),
            Paragraph(f"{summary_meta.get('first_event_at', '—')} to {summary_meta.get('last_event_at', '—')}", body_style),
            Paragraph("<b>Exported By:</b>", body_style),
            Paragraph(f"{generated_by}", body_style),
        ],
    ]

    # Additional metadata if vehicle plate
    if summary_meta.get("plate_number"):
        summary_rows.append([
            Paragraph("<b>Plate Number:</b>", body_style),
            Paragraph(f"<b>{summary_meta['plate_number']}</b>", body_style),
            Paragraph("<b>Watchlist Status:</b>", body_style),
            Paragraph(f"{summary_meta.get('watchlist_status', 'Standard Read')}", alert_style if 'MATCH' in str(summary_meta.get('watchlist_status', '')) else body_style),
        ])

    t_summary = Table(summary_rows, colWidths=[95, 175, 95, 175])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), c_bg_light),
        ('BOX', (0, 0), (-1, -1), 0.75, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, c_border),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 6))

    # Narrative callout
    narrative_p = Paragraph(f"<b>Incident Brief:</b> {desc_text}", body_style)
    t_narrative = Table([[narrative_p]], colWidths=[540])
    t_narrative.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), c_bg_subtle),
        ('BOX', (0, 0), (-1, -1), 0.5, c_accent),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_narrative)
    story.append(Spacer(1, 10))

    # ── 3. Forensic Event & Telemetry Log Table ─────────────────────────────
    story.append(Paragraph("2. CONSTITUENT EVENT & DETECTION TELEMETRY", h2_style))

    table_headers = [
        Paragraph("<b>#</b>", body_style),
        Paragraph("<b>Timestamp (UTC)</b>", body_style),
        Paragraph("<b>Camera</b>", body_style),
        Paragraph("<b>Type / Rule</b>", body_style),
        Paragraph("<b>Severity</b>", body_style),
        Paragraph("<b>Object / Track</b>", body_style),
        Paragraph("<b>Confidence</b>", body_style),
        Paragraph("<b>Ack</b>", body_style),
    ]
    event_table_data = [table_headers]

    for idx, ev in enumerate(events, 1):
        ts_str = str(ev.get("timestamp") or "")[:19].replace("T", " ")
        cam_id = ev.get("camera_id") or "UNKNOWN"
        evt_type = ev.get("type") or "EVENT"
        sev = ev.get("severity") or "INFO"
        obj = ev.get("object_type") or "—"
        tid = f"#{ev.get('track_id')}" if ev.get("track_id") is not None else "—"
        conf = f"{int(ev.get('confidence', 0) * 100)}%" if ev.get("confidence") is not None else "—"
        acked = "Yes" if ev.get("acknowledged") else "Pending"

        sev_color = "#dc2626" if sev == "CRITICAL" else "#d97706" if sev == "HIGH" else "#0284c7" if sev == "WARNING" else "#1e293b"

        event_table_data.append([
            Paragraph(str(idx), body_style),
            Paragraph(ts_str, mono_style),
            Paragraph(cam_id, body_style),
            Paragraph(evt_type, body_style),
            Paragraph(f"<font color='{sev_color}'><b>{sev}</b></font>", body_style),
            Paragraph(f"{obj} ({tid})", body_style),
            Paragraph(conf, body_style),
            Paragraph(acked, body_style),
        ])

    t_events = Table(event_table_data, colWidths=[20, 110, 65, 110, 60, 85, 45, 45])
    t_events.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), c_dark),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 0.75, c_border),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, c_border),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_events)
    story.append(Spacer(1, 10))

    # ── 4. Visual Evidence Frames / Snapshots ───────────────────────────────
    story.append(Paragraph("3. VISUAL EVIDENCE FRAMES & FORENSIC SNAPSHOTS", h2_style))
    story.append(Paragraph("<font size='7.5' color='#64748b'>Constituent frame captures, bounding box crops, and detection evidence. If a frame was not captured due to camera offline state or telemetry recording, it is explicitly indicated below.</font>", body_style))
    story.append(Spacer(1, 6))

    for idx, ev in enumerate(events, 1):
        ev_id = ev.get("id") or f"EV-{idx}"
        evidence_dict = ev.get("evidence") or {}
        snap_uri = evidence_dict.get("snapshot_uri") or ev.get("snapshot_uri")
        img_bio = _decode_image_data(snap_uri)

        ts_str = str(ev.get("timestamp") or "")[:19].replace("T", " ")
        cam_id = ev.get("camera_id") or "UNKNOWN"
        evt_type = ev.get("type") or "EVENT"
        meta = ev.get("event_metadata") or ev.get("metadata") or {}

        # Build details text
        details_lines = [
            f"<b>Item #{idx}: {evt_type} on {cam_id}</b>",
            f"<b>Timestamp:</b> {ts_str} UTC | <b>Track ID:</b> #{ev.get('track_id', 'N/A')}",
            f"<b>Detection Confidence:</b> {int(ev.get('confidence', 0)*100)}% | <b>Zone:</b> {ev.get('zone_id') or 'N/A'}",
        ]
        if meta.get("license_plate") or meta.get("plate_text"):
            details_lines.append(f"<b>Plate Read:</b> {meta.get('license_plate') or meta.get('plate_text')} | <b>List:</b> {meta.get('list_type') or 'N/A'}")
        if meta.get("notes"):
            details_lines.append(f"<b>Notes:</b> {meta.get('notes')}")

        details_p = Paragraph("<br/>".join(details_lines), body_style)

        if img_bio:
            # Embedded real image
            try:
                # Scale image nicely to max width ~220, max height ~130
                rl_img = RLImage(img_bio, width=2.4*inch, height=1.4*inch)
                card_data = [[rl_img, details_p]]
                t_card = Table(card_data, colWidths=[185, 355])
                t_card.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), c_bg_light),
                    ('BOX', (0, 0), (-1, -1), 0.5, c_border),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ]))
                story.append(KeepTogether([t_card, Spacer(1, 6)]))
            except Exception:
                # Fallback to honest degradation if rendering fails
                missing_box = Paragraph("<b>[ NO SNAPSHOT AVAILABLE ]</b><br/><font color='#64748b'>Frame render failed or image format unparseable.</font>", missing_style)
                t_card = Table([[missing_box, details_p]], colWidths=[185, 355])
                t_card.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), c_bg_light),
                    ('BOX', (0, 0), (-1, -1), 0.5, c_border),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ]))
                story.append(KeepTogether([t_card, Spacer(1, 6)]))
        else:
            # Honest degradation: no snapshot available
            missing_box = Paragraph(
                "<b>[ NO SNAPSHOT AVAILABLE ]</b><br/>"
                "<font color='#64748b'>No frame capture was recorded for this detection event (camera stream offline or telemetry metadata record).</font>",
                missing_style,
            )
            t_card = Table([[missing_box, details_p]], colWidths=[185, 355])
            t_card.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), c_bg_light),
                ('BOX', (0, 0), (-1, -1), 0.5, c_border),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ]))
            story.append(KeepTogether([t_card, Spacer(1, 6)]))

    # ── 5. Chain of Custody & Cryptographic Verification ────────────────────
    story.append(Spacer(1, 6))
    story.append(Paragraph("4. CHAIN OF CUSTODY & INTEGRITY VERIFICATION", h2_style))

    # Generate sha256 checksum over the raw metadata
    manifest_raw = json.dumps({
        "report_id": report_id,
        "title": title,
        "summary": summary_meta,
        "event_count": len(events),
        "events": [{k: v for k, v in ev.items() if k != "evidence"} for ev in events],
    }, sort_keys=True, default=str)
    sha256_hash = hashlib.sha256(manifest_raw.encode()).hexdigest()

    chain_text = (
        f"<b>Digital Evidence Hash (SHA-256):</b><br/>"
        f"<font face='Courier' size='7.5'>{sha256_hash}</font><br/><br/>"
        f"<b>Audit & Verification:</b> This document is an automated evidence record generated by NETRA "
        f"(Intelligent Border Video Analytics Platform). All timestamps are synchronized to UTC. Detections originate "
        f"from edge video inference and zone analytics. Operator acknowledgment actions are logged immutably in PostgreSQL."
    )

    t_chain = Table([[Paragraph(chain_text, body_style)]], colWidths=[540])
    t_chain.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), c_bg_subtle),
        ('BOX', (0, 0), (-1, -1), 0.5, c_dark),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_chain)

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_evidence_zip(
    title: str,
    package_type: str,
    summary_meta: Dict[str, Any],
    events: List[Dict[str, Any]],
    generated_by: str = "Operator",
) -> bytes:
    """
    Generates a downloadable ZIP evidence archive containing:
    - metadata.json: Full structured JSON dump
    - summary.txt: Formatted text summary
    - snapshots/: Directory of extracted snapshot JPGs
    - report.pdf: Complete PDF package
    """
    import zipfile

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Metadata JSON
        manifest = {
            "title": title,
            "package_type": package_type,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "exported_by": generated_by,
            "summary": summary_meta,
            "total_events": len(events),
            "events": events,
        }
        zf.writestr("metadata.json", json.dumps(manifest, indent=2, default=str))

        # 2. Text Summary
        txt_summary = [
            f"IBVAP EVIDENCE PACKAGE — {title}",
            f"Package Type: {package_type}",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Exported By: {generated_by}",
            "=" * 60,
            f"Description: {summary_meta.get('description', 'N/A')}",
            f"Severity: {summary_meta.get('severity', 'INFO')}",
            f"Camera: {summary_meta.get('camera_id', 'All')}",
            f"Zone: {summary_meta.get('zone_id', 'All')}",
            f"Total Events: {len(events)}",
            "=" * 60,
            "EVENT LOG:",
        ]
        for idx, ev in enumerate(events, 1):
            txt_summary.append(
                f"[{idx}] {ev.get('timestamp')} | {ev.get('camera_id')} | {ev.get('type')} | "
                f"Sev: {ev.get('severity')} | Conf: {ev.get('confidence')} | Track: {ev.get('track_id')}"
            )
        zf.writestr("summary.txt", "\n".join(txt_summary))

        # 3. Snapshot images
        for idx, ev in enumerate(events, 1):
            evidence_dict = ev.get("evidence") or {}
            snap_uri = evidence_dict.get("snapshot_uri") or ev.get("snapshot_uri")
            img_bio = _decode_image_data(snap_uri)
            if img_bio:
                zf.writestr(f"snapshots/event_{idx:02d}_{ev.get('id', 'snap')}.jpg", img_bio.getvalue())

        # 4. Include generated PDF inside the ZIP
        try:
            pdf_bytes = generate_evidence_pdf(
                title=title,
                package_type=package_type,
                summary_meta=summary_meta,
                events=events,
                generated_by=generated_by,
            )
            zf.writestr(f"evidence_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.pdf", pdf_bytes)
        except Exception:
            pass

    zip_bytes = zip_buf.getvalue()
    zip_buf.close()
    return zip_bytes
