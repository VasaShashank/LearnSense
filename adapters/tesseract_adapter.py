"""
Tesseract OCR Engine Adapter with OpenCV Image Preprocessing for LearnSense.

NO-FALLBACK POLICY (§1.2 #1, §2 #3):
- Missing Tesseract binary raises OCRUnavailableError.
- Missing language pack raises OCRLanguageMissingError.
- Corrupted/unreadable image raises OCRImageError.
- Never silently returns [] on engine or language errors.
- Preflight startup check validates binary and languages.

Configuration (authoritative):
- TESSERACT_CMD: path to tesseract binary or command name (default: "tesseract").
- OCR_LANGUAGES: comma-separated language codes (default: "eng,hin").
- OCR_DESKEW_ENABLED: whether to rotate skewed pages (default: "true").
- OCR_DESKEW_ANGLE_THRESHOLD: minimum angle to trigger rotation in degrees (default: 0.5).
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import pytesseract

from phase3.errors import (
    OCRImageError,
    OCRLanguageMissingError,
    OCRUnavailableError,
)

logger = logging.getLogger("LearnSense.TesseractAdapter")


class TesseractOCRAdapter:
    """Authoritative adapter for Tesseract OCR execution and image preprocessing."""

    def __init__(
        self,
        default_languages: Optional[List[str]] = None,
        deskew_enabled: Optional[bool] = None,
        deskew_angle_threshold: Optional[float] = None,
    ):
        configured_langs = os.environ.get("OCR_LANGUAGES", "").strip()
        if default_languages is not None:
            self.languages = default_languages
        elif configured_langs:
            self.languages = [lang.strip() for lang in configured_langs.split(",") if lang.strip()]
        else:
            self.languages = ["eng", "hin"]

        self.lang_str = "+".join(self.languages)

        # Deskew configuration
        if deskew_enabled is not None:
            self.deskew_enabled = deskew_enabled
        else:
            self.deskew_enabled = os.environ.get("OCR_DESKEW_ENABLED", "true").strip().lower() in ("1", "true", "yes")

        if deskew_angle_threshold is not None:
            self.deskew_angle_threshold = deskew_angle_threshold
        else:
            try:
                self.deskew_angle_threshold = float(os.environ.get("OCR_DESKEW_ANGLE_THRESHOLD", "0.5"))
            except ValueError:
                self.deskew_angle_threshold = 0.5

        # Configure Tesseract binary path
        self._sync_tesseract_cmd()

    @classmethod
    def get_tesseract_cmd(cls) -> str:
        cmd = os.environ.get("TESSERACT_CMD", "").strip()
        if cmd:
            return cmd
        which = shutil.which("tesseract")
        return which or "tesseract"

    @classmethod
    def _sync_tesseract_cmd(cls) -> str:
        cmd = cls.get_tesseract_cmd()
        pytesseract.pytesseract.tesseract_cmd = cmd
        return cmd

    @classmethod
    def is_available(cls) -> bool:
        cls._sync_tesseract_cmd()
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    @classmethod
    def get_installed_languages(cls) -> List[str]:
        cls._sync_tesseract_cmd()
        try:
            return pytesseract.get_languages()
        except Exception:
            return []

    def preprocess_image(self, image_bytes: bytes) -> np.ndarray:
        """
        OpenCV image preprocessing pipeline:
        1. Decode bytes to OpenCV BGR image.
        2. Convert to Grayscale.
        3. Estimate deskew angle using ink contours; rotate if safe and above threshold.
        4. Apply Otsu automatic global thresholding for high contrast.
        """
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise OCRImageError("Failed to decode image bytes into OpenCV image")

        # 1. Convert to Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2. Deskew estimation (only rotate when enabled and angle exceeds threshold)
        if self.deskew_enabled:
            angle = self._get_deskew_angle(gray)
            if abs(angle) > self.deskew_angle_threshold:
                gray = self._rotate_image(gray, angle)

        # 3. Otsu automatic global thresholding (§5: not "adaptive thresholding")
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    @staticmethod
    def is_available() -> bool:
        """Checks if pytesseract and Tesseract binary are operational."""
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def ocr_image(
        self,
        image_bytes: bytes,
        languages: Optional[List[str]] = None,
        psm: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Executes Tesseract OCR on preprocessed image bytes, returning word/line bounding boxes,
        extracted text strings, and confidence scores.

        Fails loudly with typed exceptions if Tesseract binary, language packs, or images fail.
        """
        self._sync_tesseract_cmd()
        thresh_img = self.preprocess_image(image_bytes)
        selected_langs = languages or self.languages
        lang = "+".join(selected_langs)
        config = f"--psm {psm} -l {lang}"

        try:
            data = pytesseract.image_to_data(
                thresh_img, config=config, output_type=pytesseract.Output.DICT
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise OCRUnavailableError(
                f"Tesseract OCR binary not found at '{pytesseract.pytesseract.tesseract_cmd}'. "
                "Install Tesseract OCR and set TESSERACT_CMD or add it to system PATH.",
                details={"cmd": pytesseract.pytesseract.tesseract_cmd, "cause": str(exc)},
            ) from exc
        except pytesseract.TesseractError as exc:
            err_msg = str(exc)
            if "traineddata" in err_msg.lower() or "language" in err_msg.lower():
                raise OCRLanguageMissingError(
                    f"Tesseract language data missing for '{lang}': {err_msg}",
                    details={"languages": selected_langs, "cause": err_msg},
                ) from exc
            raise OCRUnavailableError(
                f"Tesseract OCR execution failed: {err_msg}",
                details={"languages": selected_langs, "config": config, "cause": err_msg},
            ) from exc
        except Exception as exc:
            if isinstance(exc, (OCRUnavailableError, OCRLanguageMissingError, OCRImageError)):
                raise
            # Check availability to distinguish binary-missing from internal errors
            if not self.is_available():
                raise OCRUnavailableError(
                    f"Tesseract OCR is not available: {exc}",
                    details={"cause": str(exc)},
                ) from exc
            raise OCRUnavailableError(
                f"Tesseract OCR execution encountered an error: {exc}",
                details={"cause": str(exc)},
            ) from exc

        results = []
        n_boxes = len(data.get("text", []))

        for i in range(n_boxes):
            text = str(data["text"][i]).strip()
            raw_conf = data["conf"][i]
            try:
                conf = float(raw_conf)
            except (ValueError, TypeError):
                continue

            # Confidence: Tesseract -1 indicates block/line/paragraph bounding boxes without text
            if text and conf >= 0:
                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                results.append({
                    "text": text,
                    "bbox": [float(x), float(y), float(x + w), float(y + h)],
                    "confidence": conf / 100.0,  # Normalize 0.0 - 1.0
                    "engine_confidence": conf,
                })

        return results

    def _get_deskew_angle(self, gray: np.ndarray) -> float:
        try:
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
        rotated = cv2.warpAffine(
            image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
        return rotated
