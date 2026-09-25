"""
Tesseract 5 OCR Engine Adapter with OpenCV Image Preprocessing for Taproot Phase 1.
Handles image deskewing, Otsu adaptive thresholding, and Tesseract C++/pytesseract execution
for English and Hindi OCR.
Matches Section 12 & Section 16 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

from typing import Dict, Any, List, Optional, Tuple
import cv2
import numpy as np
import pytesseract


class TesseractOCRAdapter:
    def __init__(self, default_languages: List[str] = None):
        self.languages = default_languages or ["eng", "hin"]
        self.lang_str = "+".join(self.languages)

    def preprocess_image(self, image_bytes: bytes) -> np.ndarray:
        """
        OpenCV image preprocessing pipeline:
        1. Decode bytes to OpenCV BGR image.
        2. Convert to Grayscale.
        3. Estimate deskew angle using Radon/minAreaRect ink contours; rotate if angle > 0.5°.
        4. Apply Otsu's adaptive thresholding for high contrast.
        """
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image bytes into OpenCV image")

        # 1. Convert to Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2. Deskew estimation
        angle = self._get_deskew_angle(gray)
        if abs(angle) > 0.5:
            gray = self._rotate_image(gray, angle)

        # 3. Otsu Adaptive Thresholding
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    def ocr_image(
        self,
        image_bytes: bytes,
        languages: Optional[List[str]] = None,
        psm: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Executes Tesseract OCR on preprocessed image bytes, returning word/line bounding boxes,
        extracted text strings, and confidence scores.
        """
        thresh_img = self.preprocess_image(image_bytes)
        lang = "+".join(languages) if languages else self.lang_str
        config = f"--psm {psm} -l {lang}"

        try:
            data = pytesseract.image_to_data(thresh_img, config=config, output_type=pytesseract.Output.DICT)
        except Exception:
            # Fallback if tesseract binary or language files are not installed in environment
            return []

        results = []
        n_boxes = len(data.get("text", []))

        for i in range(n_boxes):
            text = data["text"][i].strip()
            conf = float(data["conf"][i])

            if text and conf >= 0:
                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                results.append({
                    "text": text,
                    "bbox": [float(x), float(y), float(x + w), float(y + h)],
                    "confidence": conf / 100.0,  # Normalize 0.0 - 1.0
                })

        return results

    def _get_deskew_angle(self, gray: np.ndarray) -> float:
        try:
            # Invert ink for contour bounding box minAreaRect
            inv = cv2.bitwise_not(gray)
            pts = cv2.findNonZero(inv)
            if pts is None:
                return 0.0
            rect = cv2.minAreaRect(pts)
            angle = rect[-1]
            if angle < -45:
                angle = -(90 + angle)
            else:
                angle = -angle
            return angle
        except Exception:
            return 0.0

    def _rotate_image(self, image: np.ndarray, angle: float) -> np.ndarray:
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return rotated
