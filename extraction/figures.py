"""
Figures, Diagrams, and Caption Association Extractor for Taproot Phase 1.
Extracts embedded raster images via PyMuPDF, clusters OpenCV vector drawing paths into diagram assets,
filters out small decorative icons/logos, and associates nearby 'Figure X' caption blocks.
Matches Section 12 & Section 19 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

import re
from typing import Dict, Any, List, Tuple, Optional
import fitz  # PyMuPDF
from ingestion.coordinate import CoordinateNormalizer
from schemas.document import AssetTypeEnum, BlockTypeEnum, DocumentAsset, DocumentBlock


class FigureExtractor:
    def __init__(self, min_image_size_px: int = 50, caption_proximity_pts: float = 50.0):
        self.min_image_size_px = min_image_size_px
        self.caption_proximity_pts = caption_proximity_pts

    def extract_page_figures_and_diagrams(
        self,
        page: fitz.Page,
        page_index: int,
        page_width: float,
        page_height: float,
        document_id: str,
        blocks: List[DocumentBlock],
    ) -> Tuple[List[DocumentAsset], List[DocumentBlock]]:
        """
        Extracts raster figures and vector drawing clusters.
        Associates nearby caption blocks ('Figure X...') with extracted assets via caption_block_id.
        """
        extracted_assets: List[DocumentAsset] = []
        fig_counter = 1

        # 1. Extract Embedded Raster Images
        image_info_list = page.get_images(full=True)
        for img_info in image_info_list:
            xref = img_info[0]
            base_image = page.parent.extract_image(xref)
            if not base_image:
                continue

            width = base_image.get("width", 0)
            height = base_image.get("height", 0)
            image_bytes = base_image.get("image", b"")

            # Filter out small decorative logos or bullet icons (<50px)
            is_decorative = bool(width < self.min_image_size_px or height < self.min_image_size_px)

            # Locate bounding box of image on page
            rects = page.get_image_rects(xref)
            raw_bbox = list(rects[0]) if rects else [0.0, 0.0, page_width, page_height]
            canonical_bbox = CoordinateNormalizer.normalize_bbox(raw_bbox, page_width, page_height)

            asset_id = f"ast_fig_{page_index:02d}_{fig_counter:02d}"
            filename = f"{asset_id}.png"
            uri = f"documents/{document_id}/assets/{filename}"
            sha256 = fitz.get_sha256(image_bytes)

            asset = DocumentAsset(
                asset_id=asset_id,
                type=AssetTypeEnum.FIGURE,
                page_index=page_index,
                bbox=canonical_bbox,
                uri=uri,
                sha256=sha256,
                is_decorative=is_decorative,
            )

            # Associate Caption Block if present nearby
            caption_block = self._find_nearby_caption(canonical_bbox, blocks)
            if caption_block:
                asset.caption_block_id = caption_block.block_id
                caption_block.type = BlockTypeEnum.CAPTION
                caption_block.role = "caption"
                caption_block.asset_ids.append(asset_id)

            extracted_assets.append(asset)
            fig_counter += 1

        # 2. Extract Vector Diagram Clusters (dense vector drawing paths > 15)
        drawings = page.get_drawings()
        if len(drawings) >= 15:
            vector_bbox = self._calculate_vector_cluster_bbox(drawings, page_width, page_height)
            if vector_bbox:
                asset_id = f"ast_vec_{page_index:02d}_{fig_counter:02d}"
                crop_rect = fitz.Rect(vector_bbox[0], vector_bbox[1], vector_bbox[2], vector_bbox[3])
                pix = page.get_pixmap(clip=crop_rect, dpi=200)
                img_bytes = pix.tobytes("png")
                sha256 = fitz.get_sha256(img_bytes)

                filename = f"{asset_id}.png"
                uri = f"documents/{document_id}/assets/{filename}"

                vec_asset = DocumentAsset(
                    asset_id=asset_id,
                    type=AssetTypeEnum.FIGURE,
                    page_index=page_index,
                    bbox=vector_bbox,
                    uri=uri,
                    sha256=sha256,
                    is_decorative=False,
                )

                caption_block = self._find_nearby_caption(vector_bbox, blocks)
                if caption_block:
                    vec_asset.caption_block_id = caption_block.block_id
                    caption_block.type = BlockTypeEnum.CAPTION
                    caption_block.role = "caption"
                    caption_block.asset_ids.append(asset_id)

                extracted_assets.append(vec_asset)

        return extracted_assets, blocks

    def _find_nearby_caption(
        self, asset_bbox: List[float], blocks: List[DocumentBlock]
    ) -> Optional[DocumentBlock]:
        """Locates text blocks starting with 'Figure X', 'Fig. Y' within 50pt distance above/below asset."""
        ax0, ay0, ax1, ay1 = asset_bbox

        for block in blocks:
            text = block.content.text.strip()
            if re.match(r"^(Figure|Fig\.|Table)\s+[0-9A-Za-z]+", text, re.IGNORECASE):
                bx0, by0, bx1, by1 = block.bbox
                # Distance above or below
                if abs(by0 - ay1) <= self.caption_proximity_pts or abs(ay0 - by1) <= self.caption_proximity_pts:
                    return block
        return None

    def _calculate_vector_cluster_bbox(self, drawings: List[Dict[str, Any]], page_width: float, page_height: float) -> Optional[List[float]]:
        min_x, min_y = page_width, page_height
        max_x, max_y = 0.0, 0.0
        count = 0

        for d in drawings:
            rect = d.get("rect")
            if rect:
                min_x = min(min_x, rect.x0)
                min_y = min(min_y, rect.y0)
                max_x = max(max_x, rect.x1)
                max_y = max(max_y, rect.y1)
                count += 1

        if count >= 15 and max_x > min_x and max_y > min_y:
            return CoordinateNormalizer.normalize_bbox([min_x, min_y, max_x, max_y], page_width, page_height)
        return None
