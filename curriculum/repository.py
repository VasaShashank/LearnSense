"""
Persistence for the canonical curriculum (Person 2).

Follows the repository conventions already used across the platform
(``storage/repositories.py``): one class per aggregate, a ``base_dir`` defaulting
to ``storage/<plural_snake_case>``, JSON files named after their id, and atomic
writes so a crash can never leave a truncated graph behind.

No new infrastructure is introduced: this is JSON on disk, exactly like learning
contexts, sessions and question banks.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from curriculum.models import CurriculumGraph

logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_id(raw: str) -> str:
    """Filesystem-safe, collision-resistant rendering of an identifier."""
    cleaned = _SAFE_ID_RE.sub("_", str(raw or "")).strip("._")
    return cleaned or "unnamed"


class CurriculumRepository:
    """JSON-backed store for graphs, snapshots, review records and provenance."""

    def __init__(self, base_dir: str = "storage/curriculum"):
        self.base_dir = Path(base_dir)
        self.graphs_dir = self.base_dir / "graphs"
        self.versions_dir = self.base_dir / "versions"
        self.reviews_dir = self.base_dir / "reviews"
        self.provenance_dir = self.base_dir / "provenance"
        self.mappings_dir = self.base_dir / "mappings"
        for directory in (
            self.graphs_dir,
            self.versions_dir,
            self.reviews_dir,
            self.provenance_dir,
            self.mappings_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ atomic
    def _write(self, path: Path, payload: Any) -> Path:
        from storage.repositories import _atomic_write_json

        return _atomic_write_json(path, payload, path.parent)

    # ------------------------------------------------------------------ graphs
    def graph_path(self, curriculum_id: str) -> Path:
        return self.graphs_dir / f"{_safe_id(curriculum_id)}.json"

    def save_graph(self, graph: CurriculumGraph) -> Path:
        return self._write(self.graph_path(graph.curriculum_id), graph.model_dump(mode="json"))

    def load_graph(self, curriculum_id: str) -> Optional[CurriculumGraph]:
        path = self.graph_path(curriculum_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return CurriculumGraph.model_validate(json.load(handle))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Discarding unreadable curriculum graph %s: %s", path, exc)
            return None

    def list_curriculum_ids(self) -> List[str]:
        return sorted(path.stem for path in self.graphs_dir.glob("*.json"))

    def delete_graph(self, curriculum_id: str) -> bool:
        path = self.graph_path(curriculum_id)
        if path.exists():
            path.unlink()
            return True
        return False

    # ---------------------------------------------------------------- versions
    def version_path(self, version_id: str) -> Path:
        return self.versions_dir / f"{_safe_id(version_id)}.json"

    def save_snapshot(self, snapshot: Any) -> Path:
        """``snapshot`` is a ``curriculum.versioning.CurriculumSnapshot``."""
        return self._write(self.version_path(snapshot.version.version_id), snapshot.model_dump(mode="json"))

    def load_snapshot(self, version_id: str) -> Optional[Any]:
        from curriculum.versioning import CurriculumSnapshot

        path = self.version_path(version_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return CurriculumSnapshot.model_validate(json.load(handle))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Discarding unreadable curriculum snapshot %s: %s", path, exc)
            return None

    def list_snapshots(self, curriculum_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Version metadata (without the graph payload) for listing UIs."""
        from curriculum.versioning import CurriculumVersion

        summaries: List[Dict[str, Any]] = []
        for path in sorted(self.versions_dir.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                version = CurriculumVersion.model_validate(data.get("version") or {})
            except (json.JSONDecodeError, OSError, ValueError) as exc:
                logger.warning("Skipping unreadable snapshot %s: %s", path, exc)
                continue
            if curriculum_id and version.curriculum_id != curriculum_id:
                continue
            summaries.append(version.model_dump(mode="json"))
        return sorted(summaries, key=lambda item: item.get("version_id", ""))

    # ----------------------------------------------------------------- reviews
    def reviews_path(self, curriculum_id: str) -> Path:
        return self.reviews_dir / f"{_safe_id(curriculum_id)}.json"

    def save_reviews(self, curriculum_id: str, records: List[Dict[str, Any]]) -> Path:
        return self._write(self.reviews_path(curriculum_id), records)

    def load_reviews(self, curriculum_id: str) -> List[Dict[str, Any]]:
        path = self.reviews_path(curriculum_id)
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Discarding unreadable review ledger %s: %s", path, exc)
            return []
        return data if isinstance(data, list) else []

    # -------------------------------------------------------------- provenance
    def provenance_path(self, curriculum_id: str) -> Path:
        return self.provenance_dir / f"{_safe_id(curriculum_id)}.json"

    def save_provenance(self, curriculum_id: str, records: List[Dict[str, Any]]) -> Path:
        return self._write(self.provenance_path(curriculum_id), records)

    def load_provenance(self, curriculum_id: str) -> List[Dict[str, Any]]:
        path = self.provenance_path(curriculum_id)
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Discarding unreadable provenance ledger %s: %s", path, exc)
            return []
        return data if isinstance(data, list) else []

    # ------------------------------------------------------------- mapping runs
    def mapping_path(self, curriculum_id: str, run_id: str) -> Path:
        return self.mappings_dir / f"{_safe_id(curriculum_id)}__{_safe_id(run_id)}.json"

    def save_mapping_result(self, curriculum_id: str, run_id: str, payload: Dict[str, Any]) -> Path:
        return self._write(self.mapping_path(curriculum_id, run_id), payload)

    def load_mapping_results(self, curriculum_id: str) -> List[Dict[str, Any]]:
        """Every stored mapping run for a curriculum, in deterministic order."""
        results: List[Dict[str, Any]] = []
        prefix = f"{_safe_id(curriculum_id)}__"
        for path in sorted(self.mappings_dir.glob(f"{_safe_id(curriculum_id)}__*.json")):
            if not path.stem.startswith(prefix):
                continue
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    results.append(json.load(handle))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping unreadable mapping run %s: %s", path, exc)
        return results
