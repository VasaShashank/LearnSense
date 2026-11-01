# Person 2 — Curriculum Migration & Knowledge Graph Deprecation Architecture

**Role:** Person 2 — Knowledge Graph, Curriculum, and Content Management  
**Curriculum Version Target:** `2026.jee.v1` (JEE Main 2027)  
**Date:** November 1, 2026  

---

## 1. Migration Purpose

As part of the Person 2 curriculum expansion and P1 academic remediation, several legacy concepts in the canonical JEE curriculum specification required deduplication, refactoring, or splitting into modular nodes.

To prevent breaking external dependencies (including Person 3's trained AKT neural checkpoint, historical learner mastery profiles, and diagnostic session records), LearnSense implements an immutable **ID Mapping & Concept Deprecation Policy**.

---

## 2. Graph ID Policy & Deprecation Specification

### 2.1 Deprecation Invariant
1. **Never Delete Frozen Canonical IDs:** Once assigned (`cc_<sha256[:16]>`), a concept record is never deleted from `CurriculumGraph.concepts`.
2. **Lifecycle Status Transition:** Concepts marked obsolete have `concept.status = ConceptLifecycleStatus.DEPRECATED`.
3. **Traversal Exclusion:** Active traversals, prerequisite validation, learning sequence synthesis, and diagnostic test generation query `graph.concepts` filtering out `status == 'deprecated'`.
4. **Forwarding Resolution (`CurriculumGraph.resolve_id`):**
   - Merged concepts (`relation: "merged_into"`) forward from `old_id` to `current_id`.
   - Replaced concepts (`relation: "replaced_by"`) forward from `old_id` to `current_id`.
   - Split concepts (`relation: "split_into"`) declare a list of target `current_ids`.
   - Removed concepts resolve to `None`.

---

## 3. P1 Migration Records

### 3.1 Conic Sections Consolidation

| Attribute | Legacy Value | Remediated / Successor Value |
|:---|:---|:---|
| **Concept ID** | `cc_566dd708e45bdf97` | `cc_3d26d1722cc57f40` |
| **Concept Name** | `Coordinate Geometry: Conics` | `Conic Sections (Parabola, Ellipse, Hyperbola)` |
| **Chapter ID** | `ch_coordinate_geometry_conics` (deprecated) | `ch_conic_sections` |
| **Lifecycle Status** | `deprecated` | `active` |
| **Relation in `id_map`** | `merged_into` $\to$ `cc_3d26d1722cc57f40` | Successor node |
| **Prerequisites** | Removed `Conics -> Straight Lines` inverted link | `Straight Lines` $\to$ `Circles` $\to$ `Conic Sections`; `Quadratic Equations` $\to$ `Conic Sections` |

### 3.2 Optics Modular Splitting

| Attribute | Legacy Macro Concept | Split Successor 1 (Ray) | Split Successor 2 (Wave) |
|:---|:---|:---|:---|
| **Concept ID** | `cc_a0f8c26d421e9c83` | `cc_d70ece71bc616b7b` | `cc_3c10e1bef7c6bb38` |
| **Concept Name** | `Ray and Wave Optics` | `Ray Optics and Optical Instruments` | `Wave Optics and Wave Phenomena` |
| **Chapter ID** | `ch_ray_and_wave_optics` (deprecated) | `ch_ray_optics` | `ch_wave_optics` |
| **Lifecycle Status** | `deprecated` | `active` | `active` |
| **Relation in `id_map`** | `split_into` $\to$ `["cc_d70ece71bc616b7b", "cc_3c10e1bef7c6bb38"]` | Modular component | Modular component |
| **Prerequisites** | Removed invalid `Kinematics -> Optics` dependency | `Waves` $\to$ `Ray Optics` | `Ray Optics` $\to$ `Wave Optics` |

---

## 4. Crosswalk Remapping

In `curriculum/data/jee_main_2027_crosswalk.json`, syllabus items previously referencing deprecated concepts were retargeted:
- `syl_math_u10_01` (Conic Sections syllabus item) $\to$ `cc_3d26d1722cc57f40` (`Conic Sections`, exact match).
- `syl_phy_u16_01` (Ray Optics syllabus item) $\to$ `cc_d70ece71bc616b7b` (`Ray Optics and Optical Instruments`, exact match).
- `syl_phy_u16_02` (Wave Optics syllabus item) $\to$ `cc_3c10e1bef7c6bb38` (`Wave Optics and Wave Phenomena`, exact match).

---

## 5. Backward Compatibility Impact Assessment

1. **Person 3 Simulator Bridge:**
   - Simulator concept `MAT_CON` seamlessly resolves to `cc_3d26d1722cc57f40` via `id_map`.
   - Simulator concept `PHY_OPT` seamlessly resolves to `cc_d70ece71bc616b7b` via `id_map`.
   - Full 62-dimensional AKT vectors translate with 100% completion rate without runtime exceptions.
2. **Learner State Profiles:**
   - Historical mastery records referencing `cc_566dd708e45bdf97` or `cc_a0f8c26d421e9c83` forward automatically during state evaluation.
3. **Graph Integrity:**
   - Active canonical graph is 100% cycle-free, strictly verified by `CurriculumGraphValidator`.
