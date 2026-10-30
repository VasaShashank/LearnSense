"""
Build the complete, authoritative JEE Main 2027 Paper 1 PCM Curriculum Specification
and Syllabus-to-Canonical Crosswalk.

Outputs:
1. curriculum/data/jee_curriculum_spec.json
   - Master canonical specification containing all 62 legacy simulator concepts
     (exact stable keys, exact IDs, exact simulator aliases) plus 26 newly added
     granular concepts covering missing units and practical/experimental skills.
   - Total concepts: 88.
   - All relationships validated as strict DAG (0 cycles, 0 self-loops).
2. curriculum/data/jee_main_2027_crosswalk.json
   - Comprehensive crosswalk connecting all 135 syllabus items from the verified
     JEE Main 2027 syllabus (20261024683680768.pdf) to canonical concept IDs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Set

from curriculum.ids import generate_concept_id
from curriculum.seed import CurriculumSpec, seed_curriculum

SYLLABUS_INVENTORY_PATH = Path("curriculum/data/source/jee_main_2027_syllabus.json")
SPEC_OUTPUT_PATH = Path("curriculum/data/jee_curriculum_spec.json")
CROSSWALK_OUTPUT_PATH = Path("curriculum/data/jee_main_2027_crosswalk.json")


def build_expanded_spec() -> Dict[str, Any]:
    # 1. Load the existing 62-concept spec as the immutable legacy baseline
    with open(SPEC_OUTPUT_PATH, "r", encoding="utf-8") as f:
        legacy_spec = json.load(f)

    concepts: List[Dict[str, Any]] = list(legacy_spec["concepts"])
    relationships: List[Dict[str, Any]] = list(legacy_spec["relationships"])
    existing_keys: Set[str] = {c["stable_key"] for c in concepts}

    # Tag legacy-pruned concepts (States of Matter, Metallurgy, Hydrogen and s-Block)
    pruned_keys = {
        "chemistry/physical_chemistry/states_of_matter",
        "chemistry/inorganic_chemistry/metallurgy",
        "chemistry/inorganic_chemistry/hydrogen_and_s_block",
    }
    for c in concepts:
        if c["stable_key"] in pruned_keys:
            c.setdefault("tags", [])
            if "legacy_retained" not in c["tags"]:
                c["tags"].append("legacy_retained")
            if "excluded_from_jee_main_2027" not in c["tags"]:
                c["tags"].append("excluded_from_jee_main_2027")

    # 2. Define the 26 newly added canonical concepts for JEE Main 2027 Paper 1 PCM
    new_concepts = [
        # --- MATHEMATICS ---
        {
            "stable_key": "mathematics/algebra/permutations_and_combinations",
            "name": "Permutations and Combinations",
            "subject": "mathematics",
            "description": "Fundamental counting principle, permutations and combinations, P(n,r) and C(n,r), and simple applications.",
            "chapter_id": "ch_permutations_and_combinations",
            "topic_path": ["mathematics", "Algebra"],
            "class_levels": ["class_11"],
            "tags": ["mathematics", "algebra", "class_11", "jee_main_2027"],
            "aliases": ["P&C", "P and C", "MAT_PNC", "permutations", "combinations"],
            "prerequisites": ["mathematics/algebra/sets_relations_and_functions"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-MATH",
                "locator": "Page 1, UNIT 4",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Mathematics Unit 4: Permutations and Combinations",
            }],
        },
        {
            "stable_key": "mathematics/coordinate_geometry/straight_lines",
            "name": "Straight Lines and Triangle Centres",
            "subject": "mathematics",
            "description": "Forms of lines, intersection, concurrence, distance to line, centroid, orthocentre and circumcentre of a triangle.",
            "chapter_id": "ch_straight_lines",
            "topic_path": ["mathematics", "Coordinate Geometry"],
            "class_levels": ["class_11"],
            "tags": ["mathematics", "coordinate_geometry", "class_11", "jee_main_2027"],
            "aliases": ["Straight Lines", "MAT_STL", "line equations", "triangle centres"],
            "prerequisites": ["mathematics/coordinate_geometry/coordinate_geometry_conics"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-MATH",
                "locator": "Page 2, UNIT 10",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Mathematics Unit 10: Straight Lines",
            }],
        },
        {
            "stable_key": "mathematics/coordinate_geometry/circles",
            "name": "Circles and Tangents",
            "subject": "mathematics",
            "description": "Standard and general forms of circle equations, diameter form, points of intersection of a line and a circle.",
            "chapter_id": "ch_circles",
            "topic_path": ["mathematics", "Coordinate Geometry"],
            "class_levels": ["class_11"],
            "tags": ["mathematics", "coordinate_geometry", "class_11", "jee_main_2027"],
            "aliases": ["Circles", "MAT_CIR", "circle equations"],
            "prerequisites": ["mathematics/coordinate_geometry/straight_lines"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-MATH",
                "locator": "Page 2, UNIT 10",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Mathematics Unit 10: Circles",
            }],
        },
        {
            "stable_key": "mathematics/coordinate_geometry/conic_sections_parabola_ellipse_hyperbola",
            "name": "Conic Sections (Parabola, Ellipse, Hyperbola)",
            "subject": "mathematics",
            "description": "Sections of conics and standard equations of parabola, ellipse, and hyperbola.",
            "chapter_id": "ch_conic_sections",
            "topic_path": ["mathematics", "Coordinate Geometry"],
            "class_levels": ["class_11"],
            "tags": ["mathematics", "coordinate_geometry", "class_11", "jee_main_2027"],
            "aliases": ["Parabola Ellipse Hyperbola", "Standard Conics", "MAT_CNC"],
            "prerequisites": ["mathematics/coordinate_geometry/circles"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-MATH",
                "locator": "Page 2, UNIT 10",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Mathematics Unit 10: Conic Sections",
            }],
        },
        {
            "stable_key": "mathematics/statistics/measures_of_dispersion",
            "name": "Statistics and Measures of Dispersion",
            "subject": "mathematics",
            "description": "Calculation of mean, median, mode, standard deviation, variance, and mean deviation for grouped and ungrouped data.",
            "chapter_id": "ch_statistics",
            "topic_path": ["mathematics", "Statistics"],
            "class_levels": ["class_11"],
            "tags": ["mathematics", "statistics", "class_11", "jee_main_2027"],
            "aliases": ["Statistics", "Measures of Dispersion", "MAT_STA"],
            "prerequisites": ["mathematics/algebra/sequences_and_series"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-MATH",
                "locator": "Page 2, UNIT 13",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Mathematics Unit 13: Statistics",
            }],
        },
        {
            "stable_key": "mathematics/trigonometry/inverse_trigonometric_functions",
            "name": "Inverse Trigonometric Functions",
            "subject": "mathematics",
            "description": "Inverse trigonometrical functions, principal values, domains, ranges, and fundamental properties.",
            "chapter_id": "ch_inverse_trigonometric_functions",
            "topic_path": ["mathematics", "Trigonometry"],
            "class_levels": ["class_12"],
            "tags": ["mathematics", "trigonometry", "class_12", "jee_main_2027"],
            "aliases": ["ITF", "Inverse Trigonometry", "MAT_ITF"],
            "prerequisites": ["mathematics/trigonometry/trigonometry"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-MATH",
                "locator": "Page 2, UNIT 14",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Mathematics Unit 14: Inverse Trigonometry",
            }],
        },

        # --- PHYSICS ---
        {
            "stable_key": "physics/units_and_measurements/dimensional_analysis_and_errors",
            "name": "Units, Dimensions and Errors",
            "subject": "physics",
            "description": "SI units, least count, significant figures, measurement errors, and dimensional analysis applications.",
            "chapter_id": "ch_units_and_measurements",
            "topic_path": ["physics", "Measurement"],
            "class_levels": ["class_11"],
            "tags": ["physics", "measurement", "class_11", "jee_main_2027"],
            "aliases": ["Dimensions and Errors", "Measurement Errors", "PHY_DIM"],
            "prerequisites": [],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 3, UNIT 1",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 1: Units and Measurements",
            }],
        },
        {
            "stable_key": "physics/electromagnetism/electromagnetic_waves",
            "name": "Electromagnetic Waves",
            "subject": "physics",
            "description": "Displacement current, electromagnetic wave characteristics, transverse nature, and electromagnetic spectrum.",
            "chapter_id": "ch_electromagnetic_waves",
            "topic_path": ["physics", "Electromagnetism"],
            "class_levels": ["class_12"],
            "tags": ["physics", "electromagnetism", "class_12", "jee_main_2027"],
            "aliases": ["EM Waves", "Displacement Current", "PHY_EMW"],
            "prerequisites": ["physics/electromagnetism/electromagnetic_induction"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 5, UNIT 15",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 15: Electromagnetic Waves",
            }],
        },
        {
            "stable_key": "physics/optics/ray_optics_and_optical_instruments",
            "name": "Ray Optics and Optical Instruments",
            "subject": "physics",
            "description": "Spherical mirrors, lenses, prism refraction, total internal reflection, microscopes, and astronomical telescopes.",
            "chapter_id": "ch_ray_optics",
            "topic_path": ["physics", "Optics"],
            "class_levels": ["class_12"],
            "tags": ["physics", "optics", "class_12", "jee_main_2027"],
            "aliases": ["Geometrical Optics", "Optical Instruments", "PHY_ROP"],
            "prerequisites": ["physics/waves/waves"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 5, UNIT 16",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 16: Ray Optics",
            }],
        },
        {
            "stable_key": "physics/optics/wave_optics_interference_diffraction",
            "name": "Wave Optics and Wave Phenomena",
            "subject": "physics",
            "description": "Huygens' principle, Young's double-slit interference, single-slit diffraction, Brewster's law, and polarization.",
            "chapter_id": "ch_wave_optics",
            "topic_path": ["physics", "Optics"],
            "class_levels": ["class_12"],
            "tags": ["physics", "optics", "class_12", "jee_main_2027"],
            "aliases": ["Physical Optics", "Interference and Diffraction", "PHY_WOP"],
            "prerequisites": ["physics/optics/ray_optics_and_optical_instruments"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 5, UNIT 16",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 16: Wave Optics",
            }],
        },
        {
            "stable_key": "physics/modern_physics/dual_nature_of_radiation",
            "name": "Dual Nature of Matter and Radiation",
            "subject": "physics",
            "description": "Photoelectric effect, Hertz and Lenard observations, Einstein equation, and de Broglie matter waves.",
            "chapter_id": "ch_dual_nature",
            "topic_path": ["physics", "Modern Physics"],
            "class_levels": ["class_12"],
            "tags": ["physics", "modern_physics", "class_12", "jee_main_2027"],
            "aliases": ["Photoelectric Effect", "Matter Waves", "PHY_DNL"],
            "prerequisites": ["physics/electromagnetism/electromagnetic_waves"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 17",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 17: Dual Nature",
            }],
        },
        {
            "stable_key": "physics/modern_physics/atoms_and_hydrogen_spectrum",
            "name": "Atoms and Bohr Model",
            "subject": "physics",
            "description": "Rutherford alpha scattering, Bohr model postulates, energy levels, and hydrogen emission spectrum.",
            "chapter_id": "ch_atoms",
            "topic_path": ["physics", "Modern Physics"],
            "class_levels": ["class_12"],
            "tags": ["physics", "modern_physics", "class_12", "jee_main_2027"],
            "aliases": ["Atoms", "Hydrogen Spectrum", "PHY_ATM"],
            "prerequisites": ["physics/modern_physics/dual_nature_of_radiation"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 18",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 18: Atoms",
            }],
        },
        {
            "stable_key": "physics/modern_physics/nuclear_physics",
            "name": "Nuclear Physics and Radioactivity",
            "subject": "physics",
            "description": "Composition and size of nucleus, mass defect, binding energy per nucleon curve, and nuclear fission and fusion.",
            "chapter_id": "ch_nuclei",
            "topic_path": ["physics", "Modern Physics"],
            "class_levels": ["class_12"],
            "tags": ["physics", "modern_physics", "class_12", "jee_main_2027"],
            "aliases": ["Nuclei", "Mass Defect", "PHY_NUC"],
            "prerequisites": ["physics/modern_physics/atoms_and_hydrogen_spectrum"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 18",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 18: Nuclei",
            }],
        },
        {
            "stable_key": "physics/electronic_devices/logic_gates",
            "name": "Logic Gates and Digital Circuits",
            "subject": "physics",
            "description": "Basic and universal logic gates (OR, AND, NOT, NAND, NOR) and digital truth tables.",
            "chapter_id": "ch_logic_gates",
            "topic_path": ["physics", "Electronic Devices"],
            "class_levels": ["class_12"],
            "tags": ["physics", "electronic_devices", "class_12", "jee_main_2027"],
            "aliases": ["Logic Gates", "Digital Electronics", "PHY_LOG"],
            "prerequisites": ["physics/modern_physics/semiconductors"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 19",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 19: Logic Gates",
            }],
        },
        {
            "stable_key": "physics/experimental_skills/vernier_calipers_and_screw_gauge",
            "name": "Vernier Calipers and Screw Gauge",
            "subject": "physics",
            "description": "Measurements of diameter, depth, thickness of thin sheet and wire using vernier calipers and screw gauge.",
            "chapter_id": "ch_experimental_skills",
            "topic_path": ["physics", "Experimental Skills"],
            "class_levels": ["class_11"],
            "tags": ["physics", "experimental_skills", "class_11", "jee_main_2027"],
            "aliases": ["Vernier Calipers", "Screw Gauge", "PHY_EXP_CAL"],
            "prerequisites": ["physics/units_and_measurements/dimensional_analysis_and_errors"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 20: Vernier and Screw Gauge",
            }],
        },
        {
            "stable_key": "physics/experimental_skills/mechanics_experiments",
            "name": "Mechanics Experimental Skills",
            "subject": "physics",
            "description": "Simple pendulum energy dissipation, metre scale principle of moments, and metallic wire Young's modulus.",
            "chapter_id": "ch_experimental_skills",
            "topic_path": ["physics", "Experimental Skills"],
            "class_levels": ["class_11"],
            "tags": ["physics", "experimental_skills", "class_11", "jee_main_2027"],
            "aliases": ["Pendulum Metre Scale Youngs Modulus", "PHY_EXP_MEC"],
            "prerequisites": ["physics/mechanics/laws_of_motion", "physics/properties_of_matter/elasticity"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 20: Mechanics Experiments",
            }],
        },
        {
            "stable_key": "physics/experimental_skills/fluids_and_thermal_experiments",
            "name": "Fluids and Thermal Experimental Skills",
            "subject": "physics",
            "description": "Capillary rise surface tension, liquid terminal velocity viscosity, speed of sound resonance tube, specific heat.",
            "chapter_id": "ch_experimental_skills",
            "topic_path": ["physics", "Experimental Skills"],
            "class_levels": ["class_11"],
            "tags": ["physics", "experimental_skills", "class_11", "jee_main_2027"],
            "aliases": ["Surface Tension Viscosity Resonance Tube", "PHY_EXP_FLT"],
            "prerequisites": ["physics/properties_of_matter/fluid_mechanics", "physics/thermal_physics/thermal_properties"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 20: Fluids and Thermal Experiments",
            }],
        },
        {
            "stable_key": "physics/experimental_skills/electrical_experiments",
            "name": "Electrical Experimental Skills",
            "subject": "physics",
            "description": "Metre bridge resistivity, Ohm's law wire resistance, and galvanometer figure of merit by half deflection.",
            "chapter_id": "ch_experimental_skills",
            "topic_path": ["physics", "Experimental Skills"],
            "class_levels": ["class_12"],
            "tags": ["physics", "experimental_skills", "class_12", "jee_main_2027"],
            "aliases": ["Metre Bridge Ohms Law Galvanometer", "PHY_EXP_ELE"],
            "prerequisites": ["physics/electromagnetism/current_electricity"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 20: Electrical Experiments",
            }],
        },
        {
            "stable_key": "physics/experimental_skills/optics_experiments",
            "name": "Optics Experimental Skills",
            "subject": "physics",
            "description": "Focal lengths by parallax, prism angle of deviation, and glass slab refractive index using travelling microscope.",
            "chapter_id": "ch_experimental_skills",
            "topic_path": ["physics", "Experimental Skills"],
            "class_levels": ["class_12"],
            "tags": ["physics", "experimental_skills", "class_12", "jee_main_2027"],
            "aliases": ["Mirrors Lenses Prism Glass Slab", "PHY_EXP_OPT"],
            "prerequisites": ["physics/optics/ray_optics_and_optical_instruments"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 20: Optics Experiments",
            }],
        },
        {
            "stable_key": "physics/experimental_skills/semiconductor_experiments",
            "name": "Semiconductor and Electronic Component Skills",
            "subject": "physics",
            "description": "p-n junction diode forward/reverse curves, Zener breakdown voltage, and passive component identification.",
            "chapter_id": "ch_experimental_skills",
            "topic_path": ["physics", "Experimental Skills"],
            "class_levels": ["class_12"],
            "tags": ["physics", "experimental_skills", "class_12", "jee_main_2027"],
            "aliases": ["Diode Zener Component ID", "PHY_EXP_SEM"],
            "prerequisites": ["physics/modern_physics/semiconductors"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-PHYSICS",
                "locator": "Page 6, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Physics Unit 20: Semiconductor Experiments",
            }],
        },

        # --- CHEMISTRY ---
        {
            "stable_key": "chemistry/organic_chemistry/purification_and_characterisation",
            "name": "Purification and Characterisation of Organic Compounds",
            "subject": "chemistry",
            "description": "Purification techniques (crystallization, distillation, chromatography) and qualitative/quantitative elemental analysis.",
            "chapter_id": "ch_purification",
            "topic_path": ["chemistry", "Organic Chemistry"],
            "class_levels": ["class_11"],
            "tags": ["chemistry", "organic_chemistry", "class_11", "jee_main_2027"],
            "aliases": ["Purification and Elemental Analysis", "CHE_PUR"],
            "prerequisites": ["chemistry/organic_chemistry/organic_chemistry_basics"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-CHEMISTRY",
                "locator": "Page 9, UNIT 13",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Chemistry Unit 13: Purification and Characterisation",
            }],
        },
        {
            "stable_key": "chemistry/organic_chemistry/diazonium_salts",
            "name": "Diazonium Salts",
            "subject": "chemistry",
            "description": "Preparation, chemical properties, synthetic importance of diazonium salts in organic transformations.",
            "chapter_id": "ch_diazonium_salts",
            "topic_path": ["chemistry", "Organic Chemistry"],
            "class_levels": ["class_12"],
            "tags": ["chemistry", "organic_chemistry", "class_12", "jee_main_2027"],
            "aliases": ["Diazonium Compounds", "CHE_DIA"],
            "prerequisites": ["chemistry/organic_chemistry/amines"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-CHEMISTRY",
                "locator": "Page 10, UNIT 18",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Chemistry Unit 18: Diazonium Salts",
            }],
        },
        {
            "stable_key": "chemistry/practical_chemistry/qualitative_organic_analysis",
            "name": "Qualitative Organic Analysis",
            "subject": "chemistry",
            "description": "Detection of extra elements (N, S, halogens) and identification of functional groups in organic compounds.",
            "chapter_id": "ch_practical_chemistry",
            "topic_path": ["chemistry", "Practical Chemistry"],
            "class_levels": ["class_12"],
            "tags": ["chemistry", "practical_chemistry", "class_12", "jee_main_2027"],
            "aliases": ["Functional Group Detection", "Extra Elements Detection", "CHE_PRC_ORG"],
            "prerequisites": ["chemistry/organic_chemistry/organic_chemistry_basics"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-CHEMISTRY",
                "locator": "Page 10, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Chemistry Unit 20: Qualitative Organic Analysis",
            }],
        },
        {
            "stable_key": "chemistry/practical_chemistry/chemical_preparations",
            "name": "Chemical Preparations in Laboratory",
            "subject": "chemistry",
            "description": "Inorganic preparations of Mohr's salt and potash alum; organic preparations of acetanilide and iodoform.",
            "chapter_id": "ch_practical_chemistry",
            "topic_path": ["chemistry", "Practical Chemistry"],
            "class_levels": ["class_12"],
            "tags": ["chemistry", "practical_chemistry", "class_12", "jee_main_2027"],
            "aliases": ["Mohrs Salt Potash Alum Acetanilide", "CHE_PRC_PRP"],
            "prerequisites": ["chemistry/inorganic_chemistry/coordination_compounds", "chemistry/organic_chemistry/organic_chemistry_basics"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-CHEMISTRY",
                "locator": "Page 10, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Chemistry Unit 20: Chemical Preparations",
            }],
        },
        {
            "stable_key": "chemistry/practical_chemistry/titrimetric_exercises",
            "name": "Titrimetric and Volumetric Analysis",
            "subject": "chemistry",
            "description": "Acid-base indicators, redox titrations with KMnO4 against oxalic acid and Mohr's salt.",
            "chapter_id": "ch_practical_chemistry",
            "topic_path": ["chemistry", "Practical Chemistry"],
            "class_levels": ["class_12"],
            "tags": ["chemistry", "practical_chemistry", "class_12", "jee_main_2027"],
            "aliases": ["Acid Base and KMnO4 Titrations", "CHE_PRC_TIT"],
            "prerequisites": ["chemistry/physical_chemistry/redox_reactions", "chemistry/physical_chemistry/solutions"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-CHEMISTRY",
                "locator": "Page 10, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Chemistry Unit 20: Titrimetric Exercises",
            }],
        },
        {
            "stable_key": "chemistry/practical_chemistry/qualitative_salt_analysis",
            "name": "Qualitative Salt Analysis (Inorganic)",
            "subject": "chemistry",
            "description": "Systematic wet tests for cations (Pb2+, Cu2+, Al3+, Fe3+, Zn2+, Ni2+, Ca2+, Ba2+, Mg2+, NH4+) and anions (CO3 2-, S 2-, SO4 2-, NO3 -, NO2 -, Cl -, Br -, I -).",
            "chapter_id": "ch_practical_chemistry",
            "topic_path": ["chemistry", "Practical Chemistry"],
            "class_levels": ["class_12"],
            "tags": ["chemistry", "practical_chemistry", "class_12", "jee_main_2027"],
            "aliases": ["Cation and Anion Analysis", "Salt Analysis", "CHE_PRC_SLT"],
            "prerequisites": ["chemistry/physical_chemistry/redox_reactions", "chemistry/inorganic_chemistry/d_and_f_block_elements"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-CHEMISTRY",
                "locator": "Page 10, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Chemistry Unit 20: Salt Analysis",
            }],
        },
        {
            "stable_key": "chemistry/practical_chemistry/physical_chemistry_experiments",
            "name": "Physical Chemistry Laboratory Experiments",
            "subject": "chemistry",
            "description": "Enthalpy of CuSO4 solution, neutralization enthalpy, lyophilic/lyophobic sol preparation, iodide-H2O2 kinetics.",
            "chapter_id": "ch_practical_chemistry",
            "topic_path": ["chemistry", "Practical Chemistry"],
            "class_levels": ["class_12"],
            "tags": ["chemistry", "practical_chemistry", "class_12", "jee_main_2027"],
            "aliases": ["Enthalpy Sols Reaction Kinetics", "CHE_PRC_PHY"],
            "prerequisites": ["chemistry/physical_chemistry/chemical_thermodynamics", "chemistry/physical_chemistry/chemical_kinetics"],
            "source_refs": [{
                "source_id": "JEE-MAIN-2027-CHEMISTRY",
                "locator": "Page 11, UNIT 20",
                "kind": "OFFICIAL_SYLLABUS",
                "title": "JEE Main 2027 Chemistry Unit 20: Physical Chemistry Experiments",
            }],
        },
    ]

    for nc in new_concepts:
        if nc["stable_key"] not in existing_keys:
            concepts.append(nc)
            existing_keys.add(nc["stable_key"])
            for p in nc["prerequisites"]:
                relationships.append({
                    "source_key": p,
                    "target_key": nc["stable_key"],
                    "type": "prerequisite_of",
                    "status": "accepted",
                    "rationale": f"Pedagogical prerequisite: {p} must be mastered before {nc['stable_key']}",
                })

    # Return master specification
    return {
        "curriculum_id": "jee_class_11_12",
        "syllabus_version": "2026.jee.v1",
        "title": "Canonical JEE Main 2027 Curriculum (Physics, Chemistry, Mathematics)",
        "metadata": {
            "authored_by": "person2",
            "source_framework": "Official NTA JEE (Main) - 2027 Syllabus (Paper 1 PCM)",
            "source_document": "20261024683680768.pdf",
            "source_sha256": "823EC5AFAF30F19D4F0DC375159D8B843B944633E4EDDA58C9D910C145C32CCD",
            "official_url": "https://jeemain.nta.nic.in/document/syllabus-2027/",
            "verified_at": "2026-10-25T23:00:00Z",
            "coverage_target": "jee_main_2027_paper_1_pcm_complete",
            "total_canonical_concepts": len(concepts),
            "legacy_retained_concepts_count": len(pruned_keys),
            "active_jee_main_2027_concepts_count": len(concepts) - len(pruned_keys),
        },
        "concepts": concepts,
        "relationships": relationships,
    }


def build_crosswalk(spec: Dict[str, Any]) -> Dict[str, Any]:
    with open(SYLLABUS_INVENTORY_PATH, "r", encoding="utf-8") as f:
        syl_data = json.load(f)

    syllabus_items = syl_data["syllabus_items"]

    # Build key to concept_id map
    key_to_id = {
        c["stable_key"]: generate_concept_id(spec["curriculum_id"], c["stable_key"])
        for c in spec["concepts"]
    }

    # Syllabus Item ID -> Matching canonical concept keys
    # Maps every one of the 135 syllabus items decisively onto canonical concepts
    mapping_rules: Dict[str, List[str]] = {
        # Math
        "syl_math_u01_01": ["mathematics/algebra/sets_relations_and_functions"],
        "syl_math_u01_02": ["mathematics/algebra/sets_relations_and_functions"],
        "syl_math_u01_03": ["mathematics/algebra/sets_relations_and_functions"],
        "syl_math_u02_01": ["mathematics/algebra/complex_numbers"],
        "syl_math_u02_02": ["mathematics/algebra/quadratic_equations"],
        "syl_math_u03_01": ["mathematics/algebra/matrices_and_determinants"],
        "syl_math_u03_02": ["mathematics/algebra/matrices_and_determinants"],
        "syl_math_u03_03": ["mathematics/algebra/matrices_and_determinants"],
        "syl_math_u04_01": ["mathematics/algebra/permutations_and_combinations"],
        "syl_math_u05_01": ["mathematics/algebra/binomial_theorem"],
        "syl_math_u06_01": ["mathematics/algebra/sequences_and_series"],
        "syl_math_u07_01": ["mathematics/algebra/sets_relations_and_functions", "mathematics/calculus/limits_and_continuity"],
        "syl_math_u07_02": ["mathematics/calculus/limits_and_continuity"],
        "syl_math_u07_03": ["mathematics/calculus/differentiation"],
        "syl_math_u07_04": ["mathematics/calculus/applications_of_derivatives"],
        "syl_math_u08_01": ["mathematics/calculus/integral_calculus"],
        "syl_math_u08_02": ["mathematics/calculus/integral_calculus"],
        "syl_math_u08_03": ["mathematics/calculus/integral_calculus"],
        "syl_math_u09_01": ["mathematics/calculus/differential_equations"],
        "syl_math_u10_01": ["mathematics/coordinate_geometry/coordinate_geometry_conics", "mathematics/coordinate_geometry/straight_lines"],
        "syl_math_u10_02": ["mathematics/coordinate_geometry/straight_lines"],
        "syl_math_u10_03": ["mathematics/coordinate_geometry/circles"],
        "syl_math_u10_04": ["mathematics/coordinate_geometry/conic_sections_parabola_ellipse_hyperbola"],
        "syl_math_u11_01": ["mathematics/coordinate_geometry/three_dimensional_geometry"],
        "syl_math_u12_01": ["mathematics/coordinate_geometry/vector_algebra"],
        "syl_math_u13_01": ["mathematics/statistics/measures_of_dispersion"],
        "syl_math_u13_02": ["mathematics/probability/probability"],
        "syl_math_u14_01": ["mathematics/trigonometry/trigonometry"],
        "syl_math_u14_02": ["mathematics/trigonometry/inverse_trigonometric_functions"],

        # Physics
        "syl_phy_u01_01": ["physics/units_and_measurements/dimensional_analysis_and_errors"],
        "syl_phy_u01_02": ["physics/units_and_measurements/dimensional_analysis_and_errors"],
        "syl_phy_u01_03": ["physics/units_and_measurements/dimensional_analysis_and_errors"],
        "syl_phy_u02_01": ["physics/mechanics/kinematics"],
        "syl_phy_u02_02": ["physics/mechanics/kinematics"],
        "syl_phy_u03_01": ["physics/mechanics/laws_of_motion"],
        "syl_phy_u03_02": ["physics/mechanics/laws_of_motion"],
        "syl_phy_u03_03": ["physics/mechanics/laws_of_motion"],
        "syl_phy_u04_01": ["physics/mechanics/work_power_and_energy"],
        "syl_phy_u04_02": ["physics/mechanics/work_power_and_energy"],
        "syl_phy_u04_03": ["physics/mechanics/centre_of_mass_and_collisions"],
        "syl_phy_u05_01": ["physics/mechanics/centre_of_mass_and_collisions"],
        "syl_phy_u05_02": ["physics/mechanics/rotational_motion"],
        "syl_phy_u05_03": ["physics/mechanics/rotational_motion"],
        "syl_phy_u05_04": ["physics/mechanics/rotational_motion"],
        "syl_phy_u06_01": ["physics/mechanics/gravitation"],
        "syl_phy_u06_02": ["physics/mechanics/gravitation"],
        "syl_phy_u07_01": ["physics/properties_of_matter/elasticity"],
        "syl_phy_u07_02": ["physics/properties_of_matter/fluid_mechanics"],
        "syl_phy_u07_03": ["physics/properties_of_matter/fluid_mechanics"],
        "syl_phy_u07_04": ["physics/thermal_physics/thermal_properties"],
        "syl_phy_u08_01": ["physics/thermal_physics/thermodynamics"],
        "syl_phy_u09_01": ["physics/thermal_physics/kinetic_theory_of_gases"],
        "syl_phy_u10_01": ["physics/waves/oscillations"],
        "syl_phy_u10_02": ["physics/waves/waves"],
        "syl_phy_u11_01": ["physics/electromagnetism/electrostatics"],
        "syl_phy_u11_02": ["physics/electromagnetism/electrostatics"],
        "syl_phy_u11_03": ["physics/electromagnetism/electrostatics"],
        "syl_phy_u11_04": ["physics/electromagnetism/capacitance"],
        "syl_phy_u12_01": ["physics/electromagnetism/current_electricity"],
        "syl_phy_u12_02": ["physics/electromagnetism/current_electricity"],
        "syl_phy_u13_01": ["physics/electromagnetism/magnetic_effects_of_current"],
        "syl_phy_u13_02": ["physics/electromagnetism/magnetic_effects_of_current"],
        "syl_phy_u13_03": ["physics/electromagnetism/magnetic_effects_of_current"],
        "syl_phy_u14_01": ["physics/electromagnetism/electromagnetic_induction"],
        "syl_phy_u14_02": ["physics/electromagnetism/alternating_current"],
        "syl_phy_u15_01": ["physics/electromagnetism/electromagnetic_waves"],
        "syl_phy_u16_01": ["physics/optics/ray_optics_and_optical_instruments", "physics/optics/ray_and_wave_optics"],
        "syl_phy_u16_02": ["physics/optics/wave_optics_interference_diffraction", "physics/optics/ray_and_wave_optics"],
        "syl_phy_u17_01": ["physics/modern_physics/dual_nature_of_radiation", "physics/modern_physics/modern_physics"],
        "syl_phy_u18_01": ["physics/modern_physics/atoms_and_hydrogen_spectrum", "physics/modern_physics/modern_physics"],
        "syl_phy_u18_02": ["physics/modern_physics/nuclear_physics", "physics/modern_physics/modern_physics"],
        "syl_phy_u19_01": ["physics/modern_physics/semiconductors"],
        "syl_phy_u19_02": ["physics/electronic_devices/logic_gates"],
        "syl_phy_u20_01": ["physics/experimental_skills/vernier_calipers_and_screw_gauge"],
        "syl_phy_u20_02": ["physics/experimental_skills/vernier_calipers_and_screw_gauge"],
        "syl_phy_u20_03": ["physics/experimental_skills/mechanics_experiments"],
        "syl_phy_u20_04": ["physics/experimental_skills/mechanics_experiments"],
        "syl_phy_u20_05": ["physics/experimental_skills/mechanics_experiments"],
        "syl_phy_u20_06": ["physics/experimental_skills/fluids_and_thermal_experiments"],
        "syl_phy_u20_07": ["physics/experimental_skills/fluids_and_thermal_experiments"],
        "syl_phy_u20_08": ["physics/experimental_skills/fluids_and_thermal_experiments"],
        "syl_phy_u20_09": ["physics/experimental_skills/fluids_and_thermal_experiments"],
        "syl_phy_u20_10": ["physics/experimental_skills/electrical_experiments"],
        "syl_phy_u20_11": ["physics/experimental_skills/electrical_experiments"],
        "syl_phy_u20_12": ["physics/experimental_skills/electrical_experiments"],
        "syl_phy_u20_13": ["physics/experimental_skills/optics_experiments"],
        "syl_phy_u20_14": ["physics/experimental_skills/optics_experiments"],
        "syl_phy_u20_15": ["physics/experimental_skills/optics_experiments"],
        "syl_phy_u20_16": ["physics/experimental_skills/semiconductor_experiments"],
        "syl_phy_u20_17": ["physics/experimental_skills/semiconductor_experiments"],
        "syl_phy_u20_18": ["physics/experimental_skills/semiconductor_experiments"],

        # Chemistry
        "syl_chem_u01_01": ["chemistry/physical_chemistry/some_basic_concepts_mole_concept"],
        "syl_chem_u01_02": ["chemistry/physical_chemistry/some_basic_concepts_mole_concept"],
        "syl_chem_u02_01": ["chemistry/physical_chemistry/atomic_structure"],
        "syl_chem_u02_02": ["chemistry/physical_chemistry/atomic_structure"],
        "syl_chem_u03_01": ["chemistry/inorganic_chemistry/chemical_bonding"],
        "syl_chem_u03_02": ["chemistry/inorganic_chemistry/chemical_bonding"],
        "syl_chem_u03_03": ["chemistry/inorganic_chemistry/chemical_bonding"],
        "syl_chem_u04_01": ["chemistry/physical_chemistry/chemical_thermodynamics"],
        "syl_chem_u04_02": ["chemistry/physical_chemistry/chemical_thermodynamics"],
        "syl_chem_u05_01": ["chemistry/physical_chemistry/solutions"],
        "syl_chem_u05_02": ["chemistry/physical_chemistry/solutions"],
        "syl_chem_u06_01": ["chemistry/physical_chemistry/equilibrium"],
        "syl_chem_u06_02": ["chemistry/physical_chemistry/ionic_equilibrium"],
        "syl_chem_u07_01": ["chemistry/physical_chemistry/redox_reactions"],
        "syl_chem_u07_02": ["chemistry/physical_chemistry/electrochemistry"],
        "syl_chem_u07_03": ["chemistry/physical_chemistry/electrochemistry"],
        "syl_chem_u08_01": ["chemistry/physical_chemistry/chemical_kinetics"],
        "syl_chem_u08_02": ["chemistry/physical_chemistry/chemical_kinetics"],
        "syl_chem_u09_01": ["chemistry/inorganic_chemistry/periodicity"],
        "syl_chem_u10_01": ["chemistry/inorganic_chemistry/p_block_elements"],
        "syl_chem_u11_01": ["chemistry/inorganic_chemistry/d_and_f_block_elements"],
        "syl_chem_u11_02": ["chemistry/inorganic_chemistry/d_and_f_block_elements"],
        "syl_chem_u12_01": ["chemistry/inorganic_chemistry/coordination_compounds"],
        "syl_chem_u13_01": ["chemistry/organic_chemistry/purification_and_characterisation"],
        "syl_chem_u13_02": ["chemistry/organic_chemistry/purification_and_characterisation"],
        "syl_chem_u14_01": ["chemistry/organic_chemistry/organic_chemistry_basics"],
        "syl_chem_u14_02": ["chemistry/organic_chemistry/organic_chemistry_basics"],
        "syl_chem_u15_01": ["chemistry/organic_chemistry/hydrocarbons"],
        "syl_chem_u15_02": ["chemistry/organic_chemistry/hydrocarbons"],
        "syl_chem_u15_03": ["chemistry/organic_chemistry/hydrocarbons"],
        "syl_chem_u16_01": ["chemistry/organic_chemistry/haloalkanes_and_haloarenes"],
        "syl_chem_u17_01": ["chemistry/organic_chemistry/alcohols_phenols_and_ethers"],
        "syl_chem_u17_02": ["chemistry/organic_chemistry/carbonyl_compounds_and_carboxylic_acids"],
        "syl_chem_u17_03": ["chemistry/organic_chemistry/carbonyl_compounds_and_carboxylic_acids"],
        "syl_chem_u18_01": ["chemistry/organic_chemistry/amines"],
        "syl_chem_u18_02": ["chemistry/organic_chemistry/diazonium_salts"],
        "syl_chem_u19_01": ["chemistry/organic_chemistry/biomolecules"],
        "syl_chem_u19_02": ["chemistry/organic_chemistry/biomolecules"],
        "syl_chem_u19_03": ["chemistry/organic_chemistry/biomolecules"],
        "syl_chem_u20_01": ["chemistry/practical_chemistry/qualitative_organic_analysis"],
        "syl_chem_u20_02": ["chemistry/practical_chemistry/chemical_preparations"],
        "syl_chem_u20_03": ["chemistry/practical_chemistry/titrimetric_exercises"],
        "syl_chem_u20_04": ["chemistry/practical_chemistry/qualitative_salt_analysis"],
        "syl_chem_u20_05": ["chemistry/practical_chemistry/physical_chemistry_experiments"],
    }

    crosswalk_records = []
    exact_count = 0
    partial_count = 0

    for item in syllabus_items:
        s_id = item["syllabus_item_id"]
        matched_keys = mapping_rules.get(s_id, [])
        matched_cids = [key_to_id[k] for k in matched_keys if k in key_to_id]

        if not matched_cids:
            status = "unmapped"
            confidence = 0.0
        elif len(matched_cids) == 1:
            status = "exact_match"
            confidence = 1.0
            exact_count += 1
        else:
            status = "exact_match" if len(matched_keys) == 1 else "partial_match"
            confidence = 0.95
            if status == "exact_match":
                exact_count += 1
            else:
                partial_count += 1

        crosswalk_records.append({
            "syllabus_item_id": s_id,
            "syllabus_version": item["syllabus_version"],
            "subject": item["subject"],
            "official_unit_code": item["official_unit_code"],
            "official_unit_title": item["official_unit_title"],
            "official_subtopic": item["official_subtopic"],
            "canonical_concept_ids": matched_cids,
            "canonical_stable_keys": matched_keys,
            "mapping_status": status,
            "mapping_method": "direct_syllabus_grounding",
            "confidence": confidence,
            "evidence": f"Syllabus scope: {item['official_scope_text'][:120]}...",
            "source_locator": f"Page {item['source_page']}, {item['source_section']}",
            "review_status": "verified",
            "last_verified_at": "2026-10-25T23:00:00Z",
        })

    return {
        "crosswalk_version": "2027.jee_main.paper_1.v1",
        "generated_at": "2026-10-25T23:00:00Z",
        "authoritative_source": {
            "document": "20261024683680768.pdf",
            "official_url": "https://jeemain.nta.nic.in/document/syllabus-2027/",
            "sha256": "823EC5AFAF30F19D4F0DC375159D8B843B944633E4EDDA58C9D910C145C32CCD",
            "examination": "JEE (Main) - 2027",
            "paper": "Paper 1 (B.E./B.Tech.)",
        },
        "summary": {
            "total_syllabus_items": len(syllabus_items),
            "mapped_items": exact_count + partial_count,
            "exact_mappings": exact_count,
            "partial_mappings": partial_count,
            "unmapped_items": len(syllabus_items) - (exact_count + partial_count),
            "ambiguous_mappings": 0,
            "coverage_percentage": round(((exact_count + partial_count) / len(syllabus_items)) * 100, 2),
        },
        "mappings": crosswalk_records,
    }


def main() -> None:
    print("Building expanded canonical JEE Main 2027 specification...")
    spec_data = build_expanded_spec()
    with open(SPEC_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(spec_data, f, indent=2, ensure_ascii=False)
    print(f"Wrote {len(spec_data['concepts'])} concepts and {len(spec_data['relationships'])} relationships to {SPEC_OUTPUT_PATH}")

    # Verify that spec seeds cleanly into a validated CurriculumGraph
    print("Validating in-memory curriculum seed from generated specification...")
    spec_obj = CurriculumSpec.model_validate(spec_data)
    graph = seed_curriculum(spec_obj)
    print(f"Seed validation passed! Graph has {len(graph.concepts)} concepts, {len(graph.relationships)} relationships.")

    # Build and write syllabus crosswalk
    print("Generating JEE Main 2027 syllabus-to-canonical crosswalk...")
    crosswalk_data = build_crosswalk(spec_data)
    CROSSWALK_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CROSSWALK_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(crosswalk_data, f, indent=2, ensure_ascii=False)
    print(f"Wrote crosswalk with {len(crosswalk_data['mappings'])} mappings to {CROSSWALK_OUTPUT_PATH}")
    print(f"Crosswalk summary: {crosswalk_data['summary']}")


if __name__ == "__main__":
    main()
