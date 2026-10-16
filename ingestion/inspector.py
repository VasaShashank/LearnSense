"""
Cheap Page Inspector for Taproot Phase 1.
Renders low-DPI previews (150 DPI) and extracts signals (ink density, character count,
garbage ratio, image coverage ratio, vector path count) to classify page_type for escalation routing.
Matches Section 10 & 15 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

import logging
from typing import Dict, Any, Tuple, List
import fitz  # PyMuPDF
import numpy as np

logger = logging.getLogger("LearnSense.Inspector")


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
        visual_complexity_score: float = 0.0,
        requires_vlm: bool = False,
        vlm_reason: str = "",
        page_type_confidence: float = 1.0,
        classification_reason: str = "",
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
        self.visual_complexity_score = visual_complexity_score
        self.requires_vlm = requires_vlm
        self.vlm_reason = vlm_reason
        self.page_type_confidence = page_type_confidence
        self.classification_reason = classification_reason

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
            "page_type_confidence": round(self.page_type_confidence, 2),
            "classification_reason": self.classification_reason,
            "visual_complexity_score": round(self.visual_complexity_score, 4),
            "requires_vlm": self.requires_vlm,
            "vlm_reason": self.vlm_reason,
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

        # 1. Render tiny 50-DPI thumbnail for ink density (fast – ~6KB vs 2MB at 150 DPI)
        #    Only render the 150-DPI preview on demand; the thumbnail doubles as the preview
        #    for the classification step.
        thumb_dpi = 50
        thumb_zoom = thumb_dpi / 72.0
        thumb_mat = fitz.Matrix(thumb_zoom, thumb_zoom)
        pix = page.get_pixmap(matrix=thumb_mat, alpha=False)
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
        page_type, page_type_conf, page_type_reason = self._classify_page_type(
            char_count=char_count,
            garbage_ratio=garbage_ratio,
            ink_ratio=ink_ratio,
            image_coverage_ratio=image_coverage_ratio,
            vector_path_count=vector_path_count,
        )

        # 6. Evaluate visual complexity and VLM escalation signals
        visual_complexity = 0.0
        requires_vlm = False
        vlm_reason = ""

        if vector_path_count > 35 and image_coverage_ratio >= 0.15:
            visual_complexity = min(1.0, 0.4 + (vector_path_count / 100.0) * 0.3 + image_coverage_ratio * 0.3)
            requires_vlm = True
            vlm_reason = "Complex vector graphics and diagram structures detected"
        elif garbage_ratio >= self.garbled_text_ratio_threshold and char_count >= 50:
            visual_complexity = min(1.0, 0.6 + garbage_ratio * 0.4)
            requires_vlm = True
            vlm_reason = "Garbled digital text layer requires visual reasoning"
        elif image_coverage_ratio >= 0.40 and char_count < 100 and ink_ratio > 0.05:
            visual_complexity = min(1.0, 0.5 + image_coverage_ratio * 0.5)
            requires_vlm = True
            vlm_reason = "Dense visual figure / diagram page"

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
            visual_complexity_score=visual_complexity,
            requires_vlm=requires_vlm,
            vlm_reason=vlm_reason,
            page_type_confidence=page_type_conf,
            classification_reason=page_type_reason,
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
            except (ValueError, KeyError, fitz.FileDataError) as exc:
                logger.debug("Failed to calculate image rect for %s: %s", img, exc)

        return min(1.0, float(total_image_area / page_area))

    def _classify_page_type(
        self,
        char_count: int,
        garbage_ratio: float,
        ink_ratio: float,
        image_coverage_ratio: float,
        vector_path_count: int,
    ) -> Tuple[str, float, str]:
        # Rule 1: Blank / Near-Blank
        if ink_ratio < self.blank_ink_threshold and char_count < 10 and vector_path_count < 5:
            return "blank", 0.98, "Below blank ink, character, and vector path thresholds"

        # Rule 2: Usable native text with low or high image coverage
        if char_count > 0 and garbage_ratio < self.garbled_text_ratio_threshold:
            if image_coverage_ratio >= 0.25:
                return "hybrid", 0.90, f"Native text with high image coverage ({image_coverage_ratio:.2f})"
            return "native", 0.95, f"Clean native text ({char_count} chars, garbage_ratio={garbage_ratio:.3f})"

        # Rule 3: True scanned page — no native text, mostly image area
        if char_count == 0 and image_coverage_ratio >= self.scanned_image_coverage_threshold:
            return "scanned", 0.95, f"Zero native characters with high image coverage ({image_coverage_ratio:.2f})"

        # Rule 4: Garbled text layer → OCR
        if char_count >= 50 and garbage_ratio >= self.garbled_text_ratio_threshold:
            return "scanned", 0.90, f"Garbled text layer (garbage_ratio={garbage_ratio:.3f} >= threshold)"

        # Rule 5: Explicit deterministic boundary rule (§2 #7) with reported confidence and reason
        if char_count > 0:
            conf = round(max(0.60, 1.0 - garbage_ratio), 2)
            return "native", conf, f"Borderline native text: {char_count} chars, garbage_ratio={garbage_ratio:.3f}"
        conf = round(max(0.60, image_coverage_ratio), 2)
        return "scanned", conf, f"No native text: image_coverage={image_coverage_ratio:.2f}"
