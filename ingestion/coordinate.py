"""
Canonical Coordinate System Normalizer for LearnSense / Taproot.
Standardizes bounding boxes from disparate engines (PyMuPDF, Tesseract, VLM),
MediaBox/CropBox offsets, and page rotation flags (0°, 90°, 180°, 270°) into
Top-Left Points Canonical Space [x0, y0, x1, y1].
Adheres to Section 10 of TAPROOT master specification.
"""

from typing import List, Sequence, Tuple, Union
import fitz  # PyMuPDF


class CoordinateNormalizer:
    @staticmethod
    def normalize_bbox(
        bbox: Sequence[float],
        page_width: float,
        page_height: float,
        rotation: int = 0,
        source_origin: str = "top-left",  # "top-left" or "bottom-left" (standard PDF)
        mediabox_offset: Tuple[float, float] = (0.0, 0.0),
        cropbox_offset: Tuple[float, float] = (0.0, 0.0),
        clamp: bool = True,
    ) -> List[float]:
        """
        Transforms bounding box [x0, y0, x1, y1] into canonical top-left points coordinates.
        Ensures x0 <= x1 and y0 <= y1, applies MediaBox/CropBox offsets, handles page rotation,
        and enforces clamping policy within page boundaries.
        """
        if page_width <= 0 or page_height <= 0:
            raise ValueError(f"Invalid page dimensions: width={page_width}, height={page_height} must be positive.")

        if len(bbox) != 4:
            raise ValueError(f"Expected bbox of length 4 [x0, y0, x1, y1], got {bbox}")

        try:
            x0, y0, x1, y1 = [float(v) for v in bbox]
        except (ValueError, TypeError) as exc:
            raise ValueError(f"BBox elements must be numeric: {bbox}") from exc

        # 1. Apply MediaBox/CropBox offsets if present
        # MediaBox offset shifts origin
        mb_x, mb_y = mediabox_offset
        cb_x, cb_y = cropbox_offset
        x0 = x0 - mb_x - cb_x
        x1 = x1 - mb_x - cb_x
        y0 = y0 - mb_y - cb_y
        y1 = y1 - mb_y - cb_y

        # 2. Flip Y if source is bottom-left (standard PDF coordinates)
        if source_origin == "bottom-left":
            new_y0 = page_height - y1
            new_y1 = page_height - y0
            y0, y1 = new_y0, new_y1

        # 3. Apply Page Rotation Transformation if page is rotated
        bound_w = page_height if rotation in (90, 270) else page_width
        bound_h = page_width if rotation in (90, 270) else page_height

        if rotation in (90, 180, 270):
            x0, y0, x1, y1 = CoordinateNormalizer._apply_rotation(
                x0, y0, x1, y1, page_width, page_height, rotation
            )

        # 4. Canonical order [min_x, min_y, max_x, max_y]
        min_x = min(x0, x1)
        min_y = min(y0, y1)
        max_x = max(x0, x1)
        max_y = max(y0, y1)

        # 5. Clamping policy: clamp to [0, 0, bound_w, bound_h]
        if clamp:
            min_x = max(0.0, min(bound_w, min_x))
            min_y = max(0.0, min(bound_h, min_y))
            max_x = max(0.0, min(bound_w, max_x))
            max_y = max(0.0, min(bound_h, max_y))

        # Enforce ordering
        if min_x > max_x:
            min_x, max_x = max_x, min_x
        if min_y > max_y:
            min_y, max_y = max_y, min_y

        return [round(min_x, 2), round(min_y, 2), round(max_x, 2), round(max_y, 2)]

    @staticmethod
    def _apply_rotation(
        x0: float, y0: float, x1: float, y1: float,
        width: float, height: float, rotation: int
    ) -> Tuple[float, float, float, float]:
        if rotation == 90:
            # 90 degrees clockwise: (x, y) -> (height - y, x)
            return height - y1, x0, height - y0, x1
        elif rotation == 180:
            # 180 degrees: (x, y) -> (width - x, height - y)
            return width - x1, height - y1, width - x0, height - y0
        elif rotation == 270:
            # 270 degrees clockwise (90 counter-clockwise): (x, y) -> (y, width - x)
            return y0, width - x1, y1, width - x0
        return x0, y0, x1, y1

    @staticmethod
    def pixels_to_points(
        bbox: Sequence[float],
        page_width_pts: float,
        page_height_pts: float,
        rendered_width_px: float,
        rendered_height_px: float,
        rotation: int = 0,
        clamp: bool = True,
    ) -> List[float]:
        """
        Converts pixel coordinates (e.g. from Tesseract OCR) to canonical PDF points:
        x_points = x_pixels * page_width_points / rendered_width_pixels
        y_points = y_pixels * page_height_points / rendered_height_pixels
        """
        if rendered_width_px <= 0 or rendered_height_px <= 0:
            raise ValueError(f"Invalid rendered dimensions: {rendered_width_px}x{rendered_height_px}")
        if page_width_pts <= 0 or page_height_pts <= 0:
            raise ValueError(f"Invalid page points dimensions: {page_width_pts}x{page_height_pts}")
        if len(bbox) != 4:
            raise ValueError(f"Expected bbox of length 4, got {bbox}")

        scale_x = page_width_pts / rendered_width_px
        scale_y = page_height_pts / rendered_height_px

        pts_bbox = [
            bbox[0] * scale_x,
            bbox[1] * scale_y,
            bbox[2] * scale_x,
            bbox[3] * scale_y,
        ]

        return CoordinateNormalizer.normalize_bbox(
            pts_bbox,
            page_width=page_width_pts,
            page_height=page_height_pts,
            rotation=rotation,
            source_origin="top-left",
            clamp=clamp,
        )

    @staticmethod
    def vlm_to_points(
        bbox: Sequence[float],
        page_width_pts: float,
        page_height_pts: float,
        is_normalized_1000: bool = False,
        clamp: bool = True,
    ) -> List[float]:
        """
        Normalizes VLM bounding box coordinates into canonical PDF points space.
        Handles:
        - 0-1000 normalized coordinates (e.g. [y0, x0, y1, x1] or [x0, y0, x1, y1])
        - 0-1 unit coordinates
        - raw pixel / point coordinates
        """
        if len(bbox) != 4:
            raise ValueError(f"Expected bbox of length 4, got {bbox}")

        vals = [float(v) for v in bbox]

        # Check if coordinates are 0-1000 normalized
        if is_normalized_1000 or (max(vals) <= 1000 and any(v > 1.0 for v in vals) and page_width_pts > 1000):
            # Already scaled or 0-1000
            x0 = (vals[0] / 1000.0) * page_width_pts
            y0 = (vals[1] / 1000.0) * page_height_pts
            x1 = (vals[2] / 1000.0) * page_width_pts
            y1 = (vals[3] / 1000.0) * page_height_pts
            pts_bbox = [x0, y0, x1, y1]
        elif max(vals) <= 1.0 and min(vals) >= 0.0 and (page_width_pts > 10.0 or page_height_pts > 10.0):
            # 0-1 unit coordinates
            pts_bbox = [
                vals[0] * page_width_pts,
                vals[1] * page_height_pts,
                vals[2] * page_width_pts,
                vals[3] * page_height_pts,
            ]
        else:
            pts_bbox = list(vals)

        return CoordinateNormalizer.normalize_bbox(
            pts_bbox,
            page_width=page_width_pts,
            page_height=page_height_pts,
            source_origin="top-left",
            clamp=clamp,
        )

    @staticmethod
    def fitz_rect_to_canonical(
        rect: Union[fitz.Rect, Tuple[float, float, float, float]],
        page_width: float,
        page_height: float,
        rotation: int = 0,
        clamp: bool = True,
    ) -> List[float]:
        """Convert PyMuPDF Rect object to canonical top-left points bounding box."""
        if isinstance(rect, fitz.Rect):
            raw_bbox = [rect.x0, rect.y0, rect.x1, rect.y1]
        else:
            raw_bbox = list(rect)
        return CoordinateNormalizer.normalize_bbox(
            raw_bbox, page_width, page_height, rotation=rotation, source_origin="top-left", clamp=clamp
        )
