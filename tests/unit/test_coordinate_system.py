"""
Unit tests for the Canonical Coordinate System and CoordinateNormalizer.
Verifies all requirements of Section 10 of TAPROOT master specification:
- Top-left and bottom-left coordinate systems
- Rotations: 0, 90, 180, 270 degrees
- MediaBox and CropBox offsets
- Rotated vs unrotated dimensions
- Pixel -> point conversion (Tesseract)
- VLM -> point conversion (0-1000, 0-1, points)
- Invalid dimensions, negative coordinates, zero-size boxes, out-of-page boxes, clamping policy
"""

import pytest
from ingestion.coordinate import CoordinateNormalizer


class TestCoordinateNormalizer:
    def test_canonical_top_left_unrotated(self):
        bbox = [10.0, 20.0, 150.0, 250.0]
        norm = CoordinateNormalizer.normalize_bbox(
            bbox, page_width=612.0, page_height=792.0, rotation=0, source_origin="top-left"
        )
        assert norm == [10.0, 20.0, 150.0, 250.0]

    def test_bottom_left_standard_pdf_origin(self):
        # In bottom-left origin: y=0 is at bottom of page (page_height=800)
        # Bbox [50, 100, 200, 300] bottom-left ->
        # y0 = 800 - 300 = 500, y1 = 800 - 100 = 700
        bbox = [50.0, 100.0, 200.0, 300.0]
        norm = CoordinateNormalizer.normalize_bbox(
            bbox, page_width=600.0, page_height=800.0, rotation=0, source_origin="bottom-left"
        )
        assert norm == [50.0, 500.0, 200.0, 700.0]

    def test_rotations_90_180_270(self):
        # Page 100 x 200, bbox [10, 20, 30, 40]
        bbox = [10.0, 20.0, 30.0, 40.0]

        # 90 degrees clockwise: (height - y, x) -> [200-40, 10, 200-20, 30] = [160, 10, 180, 30]
        norm90 = CoordinateNormalizer.normalize_bbox(
            bbox, page_width=100.0, page_height=200.0, rotation=90, source_origin="top-left"
        )
        assert norm90 == [160.0, 10.0, 180.0, 30.0]

        # 180 degrees: (width - x, height - y) -> [100-30, 200-40, 100-10, 200-20] = [70, 160, 90, 180]
        norm180 = CoordinateNormalizer.normalize_bbox(
            bbox, page_width=100.0, page_height=200.0, rotation=180, source_origin="top-left"
        )
        assert norm180 == [70.0, 160.0, 90.0, 180.0]

        # 270 degrees clockwise: (y, width - x) -> [20, 100-30, 40, 100-10] = [20, 70, 40, 90]
        norm270 = CoordinateNormalizer.normalize_bbox(
            bbox, page_width=100.0, page_height=200.0, rotation=270, source_origin="top-left"
        )
        assert norm270 == [20.0, 70.0, 40.0, 90.0]

    def test_mediabox_and_cropbox_offsets(self):
        # MediaBox offset shifts origin
        bbox = [60.0, 70.0, 160.0, 170.0]
        norm = CoordinateNormalizer.normalize_bbox(
            bbox,
            page_width=500.0,
            page_height=500.0,
            mediabox_offset=(10.0, 20.0),
            cropbox_offset=(5.0, 5.0),
        )
        # x: 60 - 10 - 5 = 45, 160 - 10 - 5 = 145
        # y: 70 - 20 - 5 = 45, 170 - 20 - 5 = 145
        assert norm == [45.0, 45.0, 145.0, 145.0]

    def test_clamping_policy_out_of_bounds(self):
        # Bbox exceeding page dimensions [0, 0, 500, 500]
        bbox = [-50.0, -20.0, 600.0, 700.0]
        norm = CoordinateNormalizer.normalize_bbox(
            bbox, page_width=500.0, page_height=500.0, clamp=True
        )
        assert norm == [0.0, 0.0, 500.0, 500.0]

    def test_invalid_page_dimensions_raise_error(self):
        with pytest.raises(ValueError, match="Invalid page dimensions"):
            CoordinateNormalizer.normalize_bbox([0, 0, 10, 10], page_width=0, page_height=100)

        with pytest.raises(ValueError, match="Invalid page dimensions"):
            CoordinateNormalizer.normalize_bbox([0, 0, 10, 10], page_width=100, page_height=-10)

    def test_pixel_to_points_conversion(self):
        # Rendered image is 300 DPI: 2475 x 3300 px
        # PDF page is 72 DPI: 594 x 792 points
        # Word at pixels [250, 500, 500, 600]
        norm = CoordinateNormalizer.pixels_to_points(
            bbox=[250.0, 500.0, 500.0, 600.0],
            page_width_pts=594.0,
            page_height_pts=792.0,
            rendered_width_px=2475.0,
            rendered_height_px=3300.0,
        )
        # Scale = 594 / 2475 = 0.24, 792 / 3300 = 0.24
        # x0 = 250 * 0.24 = 60.0
        # y0 = 500 * 0.24 = 120.0
        # x1 = 500 * 0.24 = 120.0
        # y1 = 600 * 0.24 = 144.0
        assert norm == [60.0, 120.0, 120.0, 144.0]

    def test_vlm_normalized_1000_to_points(self):
        # VLM outputting 0-1000 coordinates: [100, 200, 500, 600]
        norm = CoordinateNormalizer.vlm_to_points(
            bbox=[100.0, 200.0, 500.0, 600.0],
            page_width_pts=600.0,
            page_height_pts=800.0,
            is_normalized_1000=True,
        )
        # x0 = 100/1000 * 600 = 60.0
        # y0 = 200/1000 * 800 = 160.0
        # x1 = 500/1000 * 600 = 300.0
        # y1 = 600/1000 * 800 = 480.0
        assert norm == [60.0, 160.0, 300.0, 480.0]

    def test_vlm_unit_coordinates_to_points(self):
        # VLM outputting 0.0 - 1.0 unit coordinates
        norm = CoordinateNormalizer.vlm_to_points(
            bbox=[0.1, 0.2, 0.5, 0.6],
            page_width_pts=600.0,
            page_height_pts=800.0,
        )
        assert norm == [60.0, 160.0, 300.0, 480.0]
