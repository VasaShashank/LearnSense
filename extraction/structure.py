"""
Educational Structure Tagging Engine for Taproot Phase 1.
Structurally classifies Table of Contents (TOC), Glossaries, Bibliographies/References,
Footnotes, Sidebars, Exercises, and Worked Examples without performing Phase 2 semantic interpretation.
Matches Section 12 & Section 20 of TAPROOT_PHASE_1_MASTER_IMPLEMENTATION_PLAN.md.
"""

import re
from typing import List
from schemas.document import BlockTypeEnum, DocumentBlock


class EducationalStructureTagger:
    def __init__(self):
        pass

    def tag_page_structures(
        self,
        blocks: List[DocumentBlock],
        page_height: float,
    ) -> List[DocumentBlock]:
        """
        Scans page blocks and applies structural educational tags (role & type).
        """
        for block in blocks:
            text = block.content.text.strip()
            if not text:
                continue

            y0, y1 = block.bbox[1], block.bbox[3]

            # 1. Footnote Tagging (Bottom 15% margin band starting with superscript or symbol/digit)
            if y0 >= page_height * 0.85 and re.match(r"^([\*\d†‡§]+|\(\d+\))\s+[A-Z]", text):
                block.type = BlockTypeEnum.FOOTNOTE
                block.role = "footnote"
                continue

            # 2. Table of Contents Entry (. . . . . dot leaders trailing page number)
            if re.search(r"(\.{3,}|…)\s*\d+\s*$", text) or re.match(r"^Contents$|^Table of Contents$", text, re.IGNORECASE):
                block.type = BlockTypeEnum.TOC_ENTRY
                block.role = "toc"
                continue

            # 3. Glossary Term Definition (Bold term prefix or term : definition pattern)
            if re.match(r"^[A-Z][a-zA-Z0-9\s\-]{2,30}\s*[:\-—]\s+[A-Z]", text) and len(text) < 250:
                block.role = "glossary_entry"
                continue

            # 4. Bibliography / Reference ([1] Author or Author (2022))
            if re.match(r"^(\[\d+\]|\d+\.)\s+[A-Z][a-z]+,", text) or re.match(r"^References$|^Bibliography$", text, re.IGNORECASE):
                block.role = "bibliography"
                continue

            # 5. Worked Example / Exercise (Example 1.2, Exercise 3, Problem 4)
            if re.match(r"^(Example|Worked Example)\s+\d+(\.\d+)*", text, re.IGNORECASE):
                block.role = "worked_example"
                continue
            elif re.match(r"^(Exercise|Problem|Practice Question)\s+\d+(\.\d+)*", text, re.IGNORECASE):
                block.role = "exercise"
                continue

            # 6. Sidebar / Callout Box (Note:, Remember:, Warning:)
            if re.match(r"^(Note|Remember|Key Point|Tip|Warning):\s+", text, re.IGNORECASE):
                block.type = BlockTypeEnum.SIDEBAR
                block.role = "sidebar"
                continue

        return blocks
