"""
Canonical Coordinate System Normalizer for Taproot Phase 1.
Standardizes bounding boxes from disparate engines, MediaBox/CropBox offsets,
and page rotation flags (0°, 90°, 180°, 270°) into Top-Left Points Canonical Space [x0, y0, x1, y1].
Matches Section 3.11 & Section 11 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from typing import List, Tuple, Union
import fitz  # PyMuPDF


class CoordinateNormalizer:
    @staticmethod
    def normalize_bbox(
        bbox: List[float],
        page_width: float,
        page_height: float,
        rotation: int = 0,
        source_origin: str = "top-left",  # "top-left" or "bottom-left" (standard PDF)
    ) -> List[float]:
        """
        Transforms bounding box [x0, y0, x1, y1] into canonical top-left points coordinates.
        Ensures x0 <= x1 and y0 <= y1, rounded to 2 decimal places.
        """
        if len(bbox) != 4:
            raise ValueError(f"Expected bbox of length 4 [x0, y0, x1, y1], got {bbox}")

        x0, y0, x1, y1 = [float(v) for v in bbox]

        # 1. Flip Y if source is bottom-left (standard PDF coordinates)
        if source_origin == "bottom-left":
            new_y0 = page_height - y1
            new_y1 = page_height - y0
            y0, y1 = new_y0, new_y1

        # 2. Apply Page Rotation Transformation if page is rotated
        if rotation in (90, 180, 270):
            x0, y0, x1, y1 = CoordinateNormalizer._apply_rotation(
                x0, y0, x1, y1, page_width, page_height, rotation
            )

        # 3. Canonical order [min_x, min_y, max_x, max_y]
        min_x = round(min(x0, x1), 2)
        min_y = round(min(y0, y1), 2)
        max_x = round(max(x0, x1), 2)
        max_y = round(max(y0, y1), 2)

        return [min_x, min_y, max_x, max_y]

    @staticmethod
    def _apply_rotation(
        x0: float, y0: float, x1: float, y1: float,
        width: float, height: float, rotation: int
    ) -> Tuple[float, float, float, float]:
        if rotation == 90:
            # 90 degrees clockwise
            return y0, width - x1, y1, width - x0
        elif rotation == 180:
            # 180 degrees
            return width - x1, height - y1, width - x0, height - y0
        elif rotation == 270:
            # 270 degrees clockwise (90 counter-clockwise)
            return height - y1, x0, height - y0, x1
        return x0, y0, x1, y1

    @staticmethod
    def fitz_rect_to_canonical(
        rect: Union[fitz.Rect, Tuple[float, float, float, float]],
        page_width: float,
        page_height: float,
        rotation: int = 0,
    ) -> List[float]:
        """Convert PyMuPDF Rect object to canonical top-left points bounding box."""
        if isinstance(rect, fitz.Rect):
            raw_bbox = [rect.x0, rect.y0, rect.x1, rect.y1]
        else:
            raw_bbox = list(rect)
        return CoordinateNormalizer.normalize_bbox(
            raw_bbox, page_width, page_height, rotation=rotation, source_origin="top-left"
        )
