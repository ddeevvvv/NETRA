import pytest
import time
from app.analytics.zone_engine import ZoneEngine, is_point_in_polygon


class TestPointInPolygon:
    def test_point_inside_rectangle(self):
        # Rectangle covering (0.4, 0.2) to (0.8, 0.8)
        polygon = [[0.4, 0.2], [0.8, 0.2], [0.8, 0.8], [0.4, 0.8]]
        assert is_point_in_polygon((0.6, 0.5), polygon) is True
        assert is_point_in_polygon((0.45, 0.25), polygon) is True

    def test_point_outside_rectangle(self):
        polygon = [[0.4, 0.2], [0.8, 0.2], [0.8, 0.8], [0.4, 0.8]]
        assert is_point_in_polygon((0.1, 0.1), polygon) is False
        assert is_point_in_polygon((0.9, 0.5), polygon) is False
        assert is_point_in_polygon((0.6, 0.9), polygon) is False

    def test_point_on_boundary_or_edge(self):
        polygon = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        assert is_point_in_polygon((0.5, 0.0), polygon) is True
        assert is_point_in_polygon((0.5, 0.5), polygon) is True

    def test_degenerate_polygon(self):
        assert is_point_in_polygon((0.5, 0.5), [[0.0, 0.0], [1.0, 1.0]]) is False
        assert is_point_in_polygon((0.5, 0.5), []) is False


class TestZoneEngineStateTransitions:
    @pytest.fixture
    def engine(self):
        return ZoneEngine(temporal_confirmation_frames=2, track_timeout_seconds=2.0)

    @pytest.fixture
    def restricted_zone(self):
        return {
            "id": "Z-01",
            "name": "Perimeter Restricted",
            "zone_type": "POLYGON",
            "polygon_coords": [[0.5, 0.1], [0.9, 0.1], [0.9, 0.9], [0.5, 0.9]],
            "restriction_level": "RESTRICTED",
            "dwell_threshold_seconds": 5.0,
        }

    @pytest.fixture
    def monitored_zone(self):
        return {
            "id": "Z-02",
            "name": "Buffer Area",
            "zone_type": "POLYGON",
            "polygon_coords": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.9], [0.1, 0.9]],
            "restriction_level": "MONITORED",
            "dwell_threshold_seconds": 10.0,
        }

    def test_reference_point_bottom_center(self, engine):
        # Frame 640x480, bbox [100, 100, 300, 400]
        # center_x = 200 -> norm_x = 200/640 = 0.3125
        # bottom_y = 400 -> norm_y = 400/480 = 0.8333
        norm_pt = engine.get_reference_point([100, 100, 300, 400], 640, 480)
        assert abs(norm_pt[0] - 0.3125) < 1e-4
        assert abs(norm_pt[1] - (400 / 480)) < 1e-4

    def test_temporal_confirmation_suppresses_single_frame(self, engine, restricted_zone):
        # Track 1 inside restricted zone on frame 1
        # In normalized coords (0.7, 0.5) inside Z-01: bbox center_x=700, bottom_y=500 in 1000x1000 frame
        tracks_frame_1 = [
            {"track_id": 1, "object_class": "person", "bbox": [650, 400, 750, 500], "confidence": 0.95}
        ]
        events_f1, active_f1 = engine.process_frame(
            camera_id="CAM-01",
            tracks=tracks_frame_1,
            frame_shape=(1000, 1000, 3),
            zones=[restricted_zone],
            current_time=100.0,
        )

        # Frame 1: count=1, not confirmed yet -> 0 events
        assert len(events_f1) == 0
        assert 1 not in active_f1

        # Frame 2: count=2 -> confirmed -> EMIT INTRUSION event!
        events_f2, active_f2 = engine.process_frame(
            camera_id="CAM-01",
            tracks=tracks_frame_1,
            frame_shape=(1000, 1000, 3),
            zones=[restricted_zone],
            current_time=100.2,
        )
        assert len(events_f2) == 1
        evt = events_f2[0]
        assert evt["type"] == "INTRUSION"
        assert evt["severity"] == "HIGH"
        assert evt["camera_id"] == "CAM-01"
        assert evt["track_id"] == 1
        assert evt["zone_id"] == "Z-01"
        assert evt["object_type"] == "person"
        assert 1 in active_f2

    def test_loitering_fires_once_after_dwell_threshold(self, engine, restricted_zone):
        track = [{"track_id": 1, "object_class": "person", "bbox": [650, 400, 750, 500], "confidence": 0.95}]
        # Frame 1 & 2: enter zone at t=100.0
        engine.process_frame("CAM-01", track, (1000, 1000, 3), [restricted_zone], current_time=100.0)
        engine.process_frame("CAM-01", track, (1000, 1000, 3), [restricted_zone], current_time=100.2)

        # Advance time to t=103.0 (3s dwell < 5s threshold) -> no loitering event
        events_f3, _ = engine.process_frame("CAM-01", track, (1000, 1000, 3), [restricted_zone], current_time=103.0)
        assert len(events_f3) == 0

        # Advance time to t=105.5 (5.5s dwell >= 5s threshold) -> EMIT LOITERING event!
        events_f4, _ = engine.process_frame("CAM-01", track, (1000, 1000, 3), [restricted_zone], current_time=105.5)
        assert len(events_f4) == 1
        assert events_f4[0]["type"] == "LOITERING"
        assert events_f4[0]["severity"] == "WARNING"
        assert events_f4[0]["metadata"]["dwell_time_seconds"] >= 5.0

        # Advance time to t=108.0 -> should NOT fire loitering again (only once per continuous dwell)
        events_f5, _ = engine.process_frame("CAM-01", track, (1000, 1000, 3), [restricted_zone], current_time=108.0)
        assert len(events_f5) == 0

    def test_zone_exit_and_reentry(self, engine, restricted_zone):
        # Enter zone
        track_in = [{"track_id": 1, "object_class": "person", "bbox": [650, 400, 750, 500], "confidence": 0.95}]
        engine.process_frame("CAM-01", track_in, (1000, 1000, 3), [restricted_zone], current_time=100.0)
        engine.process_frame("CAM-01", track_in, (1000, 1000, 3), [restricted_zone], current_time=100.2)

        # Move outside zone (norm_x = 0.2, norm_y = 0.5)
        track_out = [{"track_id": 1, "object_class": "person", "bbox": [150, 400, 250, 500], "confidence": 0.95}]
        events_exit, active_exit = engine.process_frame("CAM-01", track_out, (1000, 1000, 3), [restricted_zone], current_time=102.0)
        assert len(events_exit) == 1
        assert events_exit[0]["type"] == "ZONE_EXIT"
        assert events_exit[0]["severity"] == "INFO"
        assert 1 not in active_exit

        # Re-enter zone
        engine.process_frame("CAM-01", track_in, (1000, 1000, 3), [restricted_zone], current_time=105.0)
        events_reenter, _ = engine.process_frame("CAM-01", track_in, (1000, 1000, 3), [restricted_zone], current_time=105.2)
        assert len(events_reenter) == 1
        assert events_reenter[0]["type"] == "INTRUSION"

    def test_monitored_zone_emits_zone_entry(self, engine, monitored_zone):
        # Track 2 enters monitored zone (norm_x = 0.25, norm_y = 0.5)
        track = [{"track_id": 2, "object_class": "car", "bbox": [200, 400, 300, 500], "confidence": 0.92}]
        engine.process_frame("CAM-01", track, (1000, 1000, 3), [monitored_zone], current_time=200.0)
        events, _ = engine.process_frame("CAM-01", track, (1000, 1000, 3), [monitored_zone], current_time=200.2)
        assert len(events) == 1
        assert events[0]["type"] == "ZONE_ENTRY"
        assert events[0]["severity"] == "INFO"
        assert events[0]["object_type"] == "car"

    def test_track_timeout_generates_exit(self, engine, restricted_zone):
        track_in = [{"track_id": 99, "object_class": "person", "bbox": [650, 400, 750, 500], "confidence": 0.95}]
        engine.process_frame("CAM-01", track_in, (1000, 1000, 3), [restricted_zone], current_time=300.0)
        engine.process_frame("CAM-01", track_in, (1000, 1000, 3), [restricted_zone], current_time=300.2)

        # Track 99 disappears from subsequent frames, 3.0s later
        events_empty, _ = engine.process_frame("CAM-01", [], (1000, 1000, 3), [restricted_zone], current_time=303.5)
        assert len(events_empty) == 1
        assert events_empty[0]["type"] == "ZONE_EXIT"
        assert events_empty[0]["track_id"] == 99
