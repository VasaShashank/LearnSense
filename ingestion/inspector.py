"""
Cheap Page Inspector for Taproot Phase 1.
Renders low-DPI previews (150 DPI) and extracts signals (ink density, character count,
garbage ratio, image coverage ratio, vector path count) to classify page_type for escalation routing.
Matches Section 10 & 15 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from typing import Dict, Any, Tuple, List
import fitz  # PyMuPDF
import numpy as np


class PageInspectionMetrics:
    def __init__(
        self,
        page_index: int,
        width: float,
        height: float,
        orientation: str,  # "portrait" or "landscape"
        rotation_applied: int,
        char_count: int,
        garbage_ratio: float,
        ink_ratio: float,
        image_coverage_ratio: float,
        vector_path_count: int,
        page_type: str,  # "native", "scanned", "hybrid", "blank", "near_blank"
        preview_png_bytes: bytes,
    ):
        self.page_index = page_index
        self.width = width
        self.height = height
        self.orientation = orientation
        self.rotation_applied = rotation_applied
        self.char_count = char_count
        self.garbage_ratio = garbage_ratio
        self.ink_ratio = ink_ratio
        self.image_coverage_ratio = image_coverage_ratio
        self.vector_path_count = vector_path_count
        self.page_type = page_type
        self.preview_png_bytes = preview_png_bytes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page_index": self.page_index,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "rotation_applied": self.rotation_applied,
            "char_count": self.char_count,
            "garbage_ratio": round(self.garbage_ratio, 4),
            "ink_ratio": round(self.ink_ratio, 4),
            "image_coverage_ratio": round(self.image_coverage_ratio, 4),
            "vector_path_count": self.vector_path_count,
            "page_type": self.page_type,
        }


class PageInspector:
    def __init__(
        self,
        preview_dpi: int = 150,
        blank_ink_threshold: float = 0.001,
        scanned_image_coverage_threshold: float = 0.60,
        garbled_text_ratio_threshold: float = 0.15,
    ):
        self.preview_dpi = preview_dpi
        self.blank_ink_threshold = blank_ink_threshold
        self.scanned_image_coverage_threshold = scanned_image_coverage_threshold
        self.garbled_text_ratio_threshold = garbled_text_ratio_threshold

    def inspect_page(self, page: fitz.Page, page_index: int) -> PageInspectionMetrics:
        rect = page.rect
        width, height = rect.width, rect.height
        rotation = page.rotation
        orientation = "landscape" if width > height else "portrait"

        # 1. Render 150 DPI preview & calculate ink density
        zoom = self.preview_dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        preview_bytes = pix.tobytes("png")

        # Calculate ink ratio using numpy array from pixmap samples
        img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
        if pix.n >= 3:
            # Grayscale conversion
            gray = np.dot(img_np[..., :3], [0.2989, 0.5870, 0.1140])
        else:
            gray = img_np[..., 0]

        # Non-white pixels (ink) < 250
        ink_pixels = np.sum(gray < 250)
        total_pixels = gray.size
        ink_ratio = float(ink_pixels / total_pixels) if total_pixels > 0 else 0.0

        # 2. Extract native text signals
        text = page.get_text("text")
        char_count = len(text)
        garbage_ratio = self._calculate_garbage_ratio(text)

        # 3. Calculate image coverage ratio
        image_coverage_ratio = self._calculate_image_coverage(page, width * height)

        # 4. Count vector path drawings
        drawings = page.get_drawings()
        vector_path_count = len(drawings)

        # 5. Classify Page Type according to Section 15 threshold rules
        page_type = self._classify_page_type(
            char_count=char_count,
            garbage_ratio=garbage_ratio,
            ink_ratio=ink_ratio,
            image_coverage_ratio=image_coverage_ratio,
            vector_path_count=vector_path_count,
        )

        return PageInspectionMetrics(
            page_index=page_index,
            width=width,
            height=height,
            orientation=orientation,
            rotation_applied=rotation,
            char_count=char_count,
            garbage_ratio=garbage_ratio,
            ink_ratio=ink_ratio,
            image_coverage_ratio=image_coverage_ratio,
            vector_path_count=vector_path_count,
            page_type=page_type,
            preview_png_bytes=preview_bytes,
        )

    def _calculate_garbage_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        trash_count = 0
        for char in text:
            code = ord(char)
            # Unicode replacement character U+FFFD or Private Use Area (PUA) or non-printable control chars
            if code == 0xFFFD or (0xE000 <= code <= 0xF8FF) or (code < 32 and char not in "\n\r\t"):
                trash_count += 1
        return float(trash_count / len(text))

    def _calculate_image_coverage(self, page: fitz.Page, page_area: float) -> float:
        if page_area <= 0:
            return 0.0
        total_image_area = 0.0
        image_list = page.get_images(full=True)
        if not image_list:
            return 0.0

        for img in image_list:
            # Get image bounding box
            try:
                rects = page.get_image_rects(img[0])
                for r in rects:
                    total_image_area += r.width * r.height
            except Exception:
                pass

        return min(1.0, float(total_image_area / page_area))

    def _classify_page_type(
        self,
        char_count: int,
        garbage_ratio: float,
        ink_ratio: float,
        image_coverage_ratio: float,
        vector_path_count: int,
    ) -> str:
        # Rule 1: Blank / Near-Blank
        if ink_ratio < self.blank_ink_threshold and char_count < 10 and vector_path_count < 5:
            return "blank"

        # Rule 2: Scanned / Garbled text
        if char_count < 50 and image_coverage_ratio >= self.scanned_image_coverage_threshold:
            return "scanned"

        if char_count >= 50 and garbage_ratio >= self.garbled_text_ratio_threshold:
            return "scanned"  # Route garbled text layer pages to OCR

        # Rule 3: Hybrid (text + significant raster images)
        if char_count >= 50 and image_coverage_ratio >= 0.25 and garbage_ratio < self.garbled_text_ratio_threshold:
            return "hybrid"

        # Rule 4: Native Digital Text
        if char_count >= 50 and garbage_ratio < self.garbled_text_ratio_threshold:
            return "native"

        # Default fallback
        return "native" if char_count > 0 else "scanned"
