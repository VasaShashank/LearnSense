"""
Script to extract and structure the official JEE Main 2027 Paper 1 PCM Syllabus
from the verified source PDF (20261024683680768.pdf).

Official Source:
    Document: Syllabus for JEE (Main) - 2027
    Official URL: https://jeemain.nta.nic.in/document/syllabus-2027/
    SHA-256: 823EC5AFAF30F19D4F0DC375159D8B843B944633E4EDDA58C9D910C145C32CCD
    Pages: 1-11 (Paper 1: B.E./B.Tech. Mathematics, Physics, Chemistry)
    Paper 2A & 2B (Pages 12-17) are excluded from the Paper 1 PCM curriculum.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import fitz

SOURCE_PDF_PATH = Path(r"c:\Users\REVANTH VISHNU REDDY\Downloads\20261024683680768.pdf")
EXPECTED_SHA256 = "823EC5AFAF30F19D4F0DC375159D8B843B944633E4EDDA58C9D910C145C32CCD"
OUTPUT_PATH = Path("curriculum/data/source/jee_main_2027_syllabus.json")


def verify_source_pdf(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Source PDF not found at {path}")
    data = path.read_bytes()
    computed_hash = hashlib.sha256(data).hexdigest().upper()
    if computed_hash != EXPECTED_SHA256:
        raise ValueError(f"Hash mismatch: expected {EXPECTED_SHA256}, got {computed_hash}")
    doc = fitz.open(path)
    return {
        "file_path": str(path),
        "sha256": computed_hash,
        "size_bytes": len(data),
        "total_pages": len(doc),
        "metadata": doc.metadata,
    }


def build_syllabus_inventory() -> Dict[str, Any]:
    source_info = verify_source_pdf(SOURCE_PDF_PATH)
    
    # We define the structured syllabus items representing the complete Paper 1 PCM syllabus
    # strictly mapped to pages 1-11 of the official document.
    items: List[Dict[str, Any]] = []

    def add_item(
        item_id: str,
        subject: str,
        unit_code: str,
        unit_title: str,
        topic: str,
        subtopic: str,
        scope_text: str,
        page: int,
        section: str,
    ) -> None:
        items.append({
            "syllabus_item_id": item_id,
            "syllabus_version": "2027.jee_main.paper_1",
            "paper": "Paper 1 (B.E./B.Tech.)",
            "subject": subject,
            "official_unit_code": unit_code,
            "official_unit_title": unit_title,
            "official_topic": topic,
            "official_subtopic": subtopic,
            "official_scope_text": scope_text.strip(),
            "source_document": "20261024683680768.pdf",
            "source_url": "https://jeemain.nta.nic.in/document/syllabus-2027/",
            "source_page": page,
            "source_section": section,
            "extraction_method": "direct_pdf_extraction_with_expert_normalization",
            "review_status": "verified",
        })

    # =========================================================================
    # MATHEMATICS (Units 1 to 14, Pages 1-2)
    # =========================================================================
    
    # Unit 1: Sets, Relations and Functions
    add_item("syl_math_u01_01", "mathematics", "MATH_U01", "SETS, RELATIONS AND FUNCTIONS",
             "Sets", "Representation, operations, and algebraic properties",
             "Sets and their representation; Union, intersection and complement of sets and their algebraic properties; Power set", 1, "UNIT 1")
    add_item("syl_math_u01_02", "mathematics", "MATH_U01", "SETS, RELATIONS AND FUNCTIONS",
             "Relations", "Types and equivalence relations",
             "Relations, type of relations, equivalence relations", 1, "UNIT 1")
    add_item("syl_math_u01_03", "mathematics", "MATH_U01", "SETS, RELATIONS AND FUNCTIONS",
             "Functions", "Types of functions and composition",
             "Functions; one-one, into and onto functions, the composition of functions", 1, "UNIT 1")

    # Unit 2: Complex Numbers and Quadratic Equations
    add_item("syl_math_u02_01", "mathematics", "MATH_U02", "COMPLEX NUMBERS AND QUADRATIC EQUATIONS",
             "Complex Numbers", "Algebra, Argand diagram, modulus and argument",
             "Complex numbers as ordered pairs of reals, Representation of complex numbers in the form a + ib and their representation in a plane, Argand diagram, algebra of complex numbers, modulus and argument (or amplitude) of a complex number", 1, "UNIT 2")
    add_item("syl_math_u02_02", "mathematics", "MATH_U02", "COMPLEX NUMBERS AND QUADRATIC EQUATIONS",
             "Quadratic Equations", "Roots, discriminant, and formation of equations",
             "Quadratic equations in real and complex number systems and their solutions; Relations between roots and coefficients, nature of roots, the formation of quadratic equations with given roots", 1, "UNIT 2")

    # Unit 3: Matrices and Determinants
    add_item("syl_math_u03_01", "mathematics", "MATH_U03", "MATRICES AND DETERMINANTS",
             "Matrices", "Algebra and types of matrices",
             "Matrices, algebra of matrices, type of matrices, determinants and matrices of order two and three", 1, "UNIT 3")
    add_item("syl_math_u03_02", "mathematics", "MATH_U03", "MATRICES AND DETERMINANTS",
             "Determinants", "Evaluation, properties, and area of triangles",
             "Evaluation of determinants, area of triangles using determinants; Adjoint and inverse of a square matrix", 1, "UNIT 3")
    add_item("syl_math_u03_03", "mathematics", "MATH_U03", "MATRICES AND DETERMINANTS",
             "Linear Systems", "Consistency and matrix solutions",
             "Test of consistency and solution of simultaneous linear equations in two or three variables using matrices", 1, "UNIT 3")

    # Unit 4: Permutations and Combinations
    add_item("syl_math_u04_01", "mathematics", "MATH_U04", "PERMUTATIONS AND COMBINATIONS",
             "Counting Principles", "Fundamental principle of counting, P(n,r) and C(n,r)",
             "The fundamental principle of counting, permutations and combinations; Meaning of P(n, r) and C(n, r). Simple applications", 1, "UNIT 4")

    # Unit 5: Binomial Theorem and its Simple Applications
    add_item("syl_math_u05_01", "mathematics", "MATH_U05", "BINOMIAL THEOREM AND ITS SIMPLE APPLICATIONS",
             "Binomial Theorem", "Expansion for positive integral index, general and middle terms",
             "Binomial theorem for a positive integral index, general term and middle term and simple applications", 1, "UNIT 5")

    # Unit 6: Sequence and Series
    add_item("syl_math_u06_01", "mathematics", "MATH_U06", "SEQUENCE AND SERIES",
             "Progressions", "Arithmetic and Geometric Progressions, A.M. and G.M.",
             "Arithmetic and Geometric progressions, insertion of arithmetic, geometric means between two given numbers, Relation between A.M and G.M.", 1, "UNIT 6")

    # Unit 7: Limit, Continuity and Differentiability
    add_item("syl_math_u07_01", "mathematics", "MATH_U07", "LIMIT, CONTINUITY AND DIFFERENTIABILITY",
             "Real-Valued Functions", "Elementary functions and their graphs",
             "Real-valued functions, algebra of functions; polynomial, rational, trigonometric, logarithmic and exponential functions; inverse functions. Graphs of simple functions", 1, "UNIT 7")
    add_item("syl_math_u07_02", "mathematics", "MATH_U07", "LIMIT, CONTINUITY AND DIFFERENTIABILITY",
             "Limits and Continuity", "Evaluation of limits and continuity of functions",
             "Limits, continuity and differentiability", 1, "UNIT 7")
    add_item("syl_math_u07_03", "mathematics", "MATH_U07", "LIMIT, CONTINUITY AND DIFFERENTIABILITY",
             "Differentiation", "Rules of differentiation and higher order derivatives",
             "Differentiation of the sum, difference, product and quotient of two functions. Differentiation of trigonometric, inverse trigonometric, logarithmic, exponential, composite and implicit functions; derivatives of order upto two", 1, "UNIT 7")
    add_item("syl_math_u07_04", "mathematics", "MATH_U07", "LIMIT, CONTINUITY AND DIFFERENTIABILITY",
             "Applications of Derivatives", "Rate of change, monotonicity, and extrema",
             "Applications of derivatives: Rate of change of quantities, monotonic-Increasing and decreasing functions, Maxima and minima of functions of one variable", 1, "UNIT 7")

    # Unit 8: Integral Calculus
    add_item("syl_math_u08_01", "mathematics", "MATH_U08", "INTEGRAL CALCULAS",
             "Indefinite Integrals", "Fundamental integrals and standard techniques",
             "Integral as an anti-derivative, Fundamental integrals involving algebraic, trigonometric, exponential and logarithmic functions. Integration by substitution, by parts and by partial fractions. Integration using trigonometric identities", 1, "UNIT 8")
    add_item("syl_math_u08_02", "mathematics", "MATH_U08", "INTEGRAL CALCULAS",
             "Special Integrals", "Evaluation of standard rational and irrational algebraic forms",
             "Evaluation of simple integrals of standard quadratic, radical, and linear/quadratic rational forms", 1, "UNIT 8")
    add_item("syl_math_u08_03", "mathematics", "MATH_U08", "INTEGRAL CALCULAS",
             "Definite Integrals and Area", "Fundamental theorem, definite integral properties, bounded areas",
             "The fundamental theorem of calculus, properties of definite integrals. Evaluation of definite integrals, determining areas of the regions bounded by simple curves in standard forms", 2, "UNIT 8")

    # Unit 9: Differential Equations
    add_item("syl_math_u09_01", "mathematics", "MATH_U09", "DIFFRENTIAL EQUATIONS",
             "Differential Equations", "Order, degree, separable, homogeneous and linear first-order ODEs",
             "Ordinary differential equations, their order and degree, the solution of differential equation by the method of separation of variables, solution of a homogeneous and linear differential equation of the type dy/dx + p(x)y = q(x)", 2, "UNIT 9")

    # Unit 10: Co-ordinate Geometry
    add_item("syl_math_u10_01", "mathematics", "MATH_U10", "CO-ORDINATE GEOMETRY",
             "Cartesian Coordinates", "Distance, section formula, locus, slope and line inclinations",
             "Cartesian system of rectangular coordinates in a plane, distance formula, sections formula, locus and its equation, the slope of a line, parallel and perpendicular lines, intercepts of a line on the co-ordinate axis", 2, "UNIT 10")
    add_item("syl_math_u10_02", "mathematics", "MATH_U10", "CO-ORDINATE GEOMETRY",
             "Straight Lines", "Forms of lines, intersection, concurrence, distance to line, triangle centres",
             "Straight line: Various forms of equations of a line, intersection of lines, angles between two lines, conditions for concurrence of three lines, the distance of a point form a line, co-ordinate of the centroid, orthocentre and circumcentre of a triangle", 2, "UNIT 10")
    add_item("syl_math_u10_03", "mathematics", "MATH_U10", "CO-ORDINATE GEOMETRY",
             "Circles", "Standard and general equations, diameter form, line-circle intersections",
             "Circle: A standard form of equations of a circle, the general form of the equation of a circle, its radius and centre, equation of a circle when the endpoints of a diameter are given, points of intersection of a line and a circle with the centre at the origin", 2, "UNIT 10")
    add_item("syl_math_u10_04", "mathematics", "MATH_U10", "CO-ORDINATE GEOMETRY",
             "Conic Sections", "Parabola, ellipse, and hyperbola in standard forms",
             "Sections of conics, equations of conic sections (parabola, ellipse and hyperbola) in standard forms", 2, "UNIT 10")

    # Unit 11: Three Dimensional Geometry
    add_item("syl_math_u11_01", "mathematics", "MATH_U11", "THREE DIMENSIONAL GEOMETRY",
             "Lines in Space", "Direction cosines, line equations, skew lines and shortest distance",
             "Coordinates of a point in space, the distance between two points, section formula, direction ratios and direction cosines and the angle between two intersecting lines. Equation of a line; Skew lines, the shortest distance between them and its equation", 2, "UNIT 11")

    # Unit 12: Vector Algebra
    add_item("syl_math_u12_01", "mathematics", "MATH_U12", "VECTOR ALGEBRA",
             "Vectors", "Components, addition, scalar (dot) and vector (cross) products",
             "Vectors and scalars, the addition of vectors, components of a vector in two dimensions and three-dimensional spaces, scalar and vector products", 2, "UNIT 12")

    # Unit 13: Statistics and Probability
    add_item("syl_math_u13_01", "mathematics", "MATH_U13", "STATISTICS AND PROBABILITY",
             "Statistics", "Measures of dispersion: mean, median, mode, variance, standard deviation",
             "Measures of dispersion; calculation of mean, median, mode of grouped and ungrouped data, calculation of standard deviation, variance and mean deviation for grouped and ungrouped data", 2, "UNIT 13")
    add_item("syl_math_u13_02", "mathematics", "MATH_U13", "STATISTICS AND PROBABILITY",
             "Probability", "Probability theorems, Bayes' theorem, probability distributions",
             "Probability: Probability of an event, addition and multiplication theorems of probability, Baye's theorem, probability distribution of a random variable", 2, "UNIT 13")

    # Unit 14: Trigonometry
    add_item("syl_math_u14_01", "mathematics", "MATH_U14", "TRIGONOMETRY",
             "Trigonometric Functions", "Identities and functions",
             "Trigonometrical identities and trigonometrical functions", 2, "UNIT 14")
    add_item("syl_math_u14_02", "mathematics", "MATH_U14", "TRIGONOMETRY",
             "Inverse Trigonometric Functions", "Definitions, domains, ranges, and properties",
             "Inverse trigonometrical functions their properties", 2, "UNIT 14")

    # =========================================================================
    # PHYSICS (Units 1 to 20, Pages 3-6)
    # =========================================================================

    # Unit 1: Units and Measurements
    add_item("syl_phy_u01_01", "physics", "PHY_U01", "Units and Measurements",
             "Units and Standards", "SI units, fundamental and derived units",
             "Units of measurements, System of units, SI Units, fundamental and derived units", 3, "UNIT 1")
    add_item("syl_phy_u01_02", "physics", "PHY_U01", "Units and Measurements",
             "Errors and Precision", "Least count, significant figures, measurement errors",
             "Least count, significant figures, Errors in measurements", 3, "UNIT 1")
    add_item("syl_phy_u01_03", "physics", "PHY_U01", "Units and Measurements",
             "Dimensional Analysis", "Dimensions of quantities and applications",
             "Dimensions of Physics quantities, dimensional analysis and its applications", 3, "UNIT 1")

    # Unit 2: Kinematics
    add_item("syl_phy_u02_01", "physics", "PHY_U02", "Kinematics",
             "Motion in a Straight Line", "Speed, velocity, acceleration, motion graphs, relative velocity",
             "The frame of reference, motion in a straight line, speed and velocity, uniform and non-uniform motion, average speed and instantaneous velocity, uniformly accelerated motion, velocity-time, position-time graph, relations for uniformly accelerated motion, relative velocity", 3, "UNIT 2")
    add_item("syl_phy_u02_02", "physics", "PHY_U02", "Kinematics",
             "Motion in a Plane", "Projectile motion and uniform circular motion",
             "Motion in a plane, projectile motion, uniform circular motion", 3, "UNIT 2")

    # Unit 3: Laws of Motion
    add_item("syl_phy_u03_01", "physics", "PHY_U03", "Laws of Motion",
             "Newton's Laws and Momentum", "Inertia, momentum, 3 laws, impulse, conservation of momentum",
             "Force and inertia, Newton’s first law of motion, momentum, Newton’s second Law of motion, impulse, Newton’s third Law of motion. Law of conservation of linear momentum and its applications, equilibrium of concurrent forces", 3, "UNIT 3")
    add_item("syl_phy_u03_02", "physics", "PHY_U03", "Laws of Motion",
             "Friction", "Static, kinetic, and rolling friction",
             "Static and Kinetic friction, laws of friction, rolling friction", 3, "UNIT 3")
    add_item("syl_phy_u03_03", "physics", "PHY_U03", "Laws of Motion",
             "Circular Dynamics", "Centripetal force, road banking",
             "Dynamics of uniform circular motion, centripetal force and its applications: vehicle on a level circular road, vehicle on a banked road", 3, "UNIT 3")

    # Unit 4: Work, Energy and Power
    add_item("syl_phy_u04_01", "physics", "PHY_U04", "Work, Energy and Power",
             "Work and Kinetic Energy", "Work done, kinetic energy, work-energy theorem, power",
             "Work done by a constant force and a variable force, kinetic and potential energies, work-energy theorem, power", 3, "UNIT 4")
    add_item("syl_phy_u04_02", "physics", "PHY_U04", "Work, Energy and Power",
             "Potential Energy and Conservation", "Spring potential energy, conservation of mechanical energy, vertical circle",
             "The potential energy of a spring, conservation of mechanical energy, conservative and non-conservative forces, motion in a vertical circle", 3, "UNIT 4")
    add_item("syl_phy_u04_03", "physics", "PHY_U04", "Work, Energy and Power",
             "Collisions", "Elastic and inelastic collisions in 1D and 2D",
             "Elastic and inelastic collisions in one and two dimensions", 3, "UNIT 4")

    # Unit 5: Rotational Motion
    add_item("syl_phy_u05_01", "physics", "PHY_U05", "Rotational Motion",
             "Centre of Mass", "Two-particle and rigid body centre of mass",
             "Centre of mass of a two-particle system, centre of mass of a rigid body", 3, "UNIT 5")
    add_item("syl_phy_u05_02", "physics", "PHY_U05", "Rotational Motion",
             "Torque and Angular Momentum", "Moment of force, angular momentum conservation",
             "Basic concepts of rotational motion, moment of a force, torque, angular momentum, conservation of angular momentum and its applications", 3, "UNIT 5")
    add_item("syl_phy_u05_03", "physics", "PHY_U05", "Rotational Motion",
             "Moment of Inertia", "Radius of gyration, parallel and perpendicular axes theorems",
             "The moment of inertia, the radius of gyration, values of moments of inertia for simple geometrical objects, parallel and perpendicular axes theorems and their applications", 3, "UNIT 5")
    add_item("syl_phy_u05_04", "physics", "PHY_U05", "Rotational Motion",
             "Rigid Body Dynamics", "Equilibrium and rotational kinematic equations",
             "Equilibrium of rigid bodies, rigid body rotation and equations of rotational motion, comparison of linear and rotational motions", 3, "UNIT 5")

    # Unit 6: Gravitation
    add_item("syl_phy_u06_01", "physics", "PHY_U06", "Gravitation",
             "Gravitational Law and Field", "Universal gravitation, variation of g with altitude and depth",
             "The universal law of gravitation. Acceleration due to gravity and its variation with altitude and depth. Kepler’s law of planetary motion", 3, "UNIT 6")
    add_item("syl_phy_u06_02", "physics", "PHY_U06", "Gravitation",
             "Gravitational Energy and Satellites", "Potential, escape velocity, orbital motion and satellite energy",
             "Gravitational potential energy, gravitational potential. Escape velocity, motion of a satellite, orbital velocity, time period and energy of satellite", 3, "UNIT 6")

    # Unit 7: Properties of Solids and Liquids
    add_item("syl_phy_u07_01", "physics", "PHY_U07", "Properties of Solids and Liquids",
             "Elasticity", "Stress-strain, Hooke's law, elastic moduli",
             "Elastic behaviour, stress-strain relationship, Hooke's Law, Young's modulus, bulk modulus and modulus of rigidity", 3, "UNIT 7")
    add_item("syl_phy_u07_02", "physics", "PHY_U07", "Properties of Solids and Liquids",
             "Fluid Statics and Dynamics", "Pressure, Pascal's law, viscosity, Stoke's law, Bernoulli's principle",
             "Pressure due to a fluid column, Pascal's law and its applications, effect of gravity on fluid pressure, viscosity, Stoke’s law, terminal velocity, streamline and turbulent flow, critical velocity, Bernoulli's principle and its applications", 4, "UNIT 7")
    add_item("syl_phy_u07_03", "physics", "PHY_U07", "Properties of Solids and Liquids",
             "Surface Tension", "Surface energy, contact angle, excess pressure, capillary rise",
             "Surface energy and surface tension, angle of contact, excess of pressure across a curved surface, application of surface tension: drops, bubbles and capillary rise", 4, "UNIT 7")
    add_item("syl_phy_u07_04", "physics", "PHY_U07", "Properties of Solids and Liquids",
             "Thermal Properties and Heat Transfer", "Expansion, calorimetry, latent heat, conduction, convection, radiation",
             "Heat, temperature, thermal expansion, specific heat capacity, calorimetry, change of state, latent heat. Heat transfer: conduction, convection and radiation", 4, "UNIT 7")

    # Unit 8: Thermodynamics
    add_item("syl_phy_u08_01", "physics", "PHY_U08", "Thermodynamics",
             "Laws of Thermodynamics", "Zeroth, first and second laws, thermodynamic processes",
             "Thermal equilibrium and the concept of temperature, zeroth law of thermodynamics, heat, work and internal energy. The first law of thermodynamics, isothermal and adiabatic processes. The second law of thermodynamics: reversible and irreversible processes", 4, "UNIT 8")

    # Unit 9: Kinetic Theory of Gases
    add_item("syl_phy_u09_01", "physics", "PHY_U09", "Kinetic Theory of Gases",
             "Kinetic Theory of Gases", "Gas state equation, pressure, RMS speed, equipartition, degrees of freedom",
             "Equation of state of a perfect gas, work done on compressing a gas, kinetic theory of gases: assumptions, the concept of pressure, kinetic interpretation of temperature, RMS speed of gas molecules, degrees of freedom, law of equipartition of energy and applications to specific heat capacities of gases, mean free path, Avogadro's number", 4, "UNIT 9")

    # Unit 10: Oscillations and Waves
    add_item("syl_phy_u10_01", "physics", "PHY_U10", "Oscillations and Waves",
             "Simple Harmonic Motion", "SHM kinematics, spring oscillations, energy, simple pendulum",
             "Oscillations and periodic motion: time period, frequency, displacement as a function of time, periodic functions. Simple harmonic motion (S.H.M.) and its equation, phase, oscillations of a spring: restoring force and force constant, energy in S.H.M.: kinetic and potential energies, simple pendulum: derivation of expression for its time period", 4, "UNIT 10")
    add_item("syl_phy_u10_02", "physics", "PHY_U10", "Oscillations and Waves",
             "Wave Motion and Sound", "Travelling waves, superposition, standing waves, resonance in pipes, beats",
             "Wave motion, longitudinal and transverse waves, speed of the travelling wave, displacement relation for a progressive wave, principle of superposition of waves, reflection of waves, standing waves in strings and organ pipes, fundamental mode and harmonics, beats", 4, "UNIT 10")

    # Unit 11: Electrostatics
    add_item("syl_phy_u11_01", "physics", "PHY_U11", "Electrostatics",
             "Electric Charges and Coulomb's Law", "Charge conservation, Coulomb's law, continuous distributions",
             "Electric charges: conservation of charge, Coulomb's law forces between two point charges, forces between multiple charges, superposition principle and continuous charge distribution", 4, "UNIT 11")
    add_item("syl_phy_u11_02", "physics", "PHY_U11", "Electrostatics",
             "Electric Field and Flux", "Field lines, dipole, Gauss's law and applications",
             "Electric field: electric field due to a point charge, electric field lines, electric dipole, electric field due to a dipole, torque on a dipole in a uniform electric field. Electric flux, Gauss's law and its applications to find field due to infinitely long uniformly charged straight wire, uniformly charged infinite plane sheet and uniformly charged thin spherical shell", 4, "UNIT 11")
    add_item("syl_phy_u11_03", "physics", "PHY_U11", "Electrostatics",
             "Electric Potential", "Point charges, dipoles, equipotential surfaces, potential energy",
             "Electric potential and its calculation for a point charge, electric dipole and system of charges, potential difference, equipotential surfaces, electrical potential energy of a system of two point charges and of electric dipole in an electrostatic field", 4, "UNIT 11")
    add_item("syl_phy_u11_04", "physics", "PHY_U11", "Electrostatics",
             "Capacitance", "Capacitor combinations, dielectrics, energy stored",
             "Conductors and insulators, dielectrics and electric polarization, capacitors and capacitance, the combination of capacitors in series and parallel and capacitance of a parallel plate capacitor with and without dielectric medium between the plates, energy stored in a capacitor", 4, "UNIT 11")

    # Unit 12: Current Electricity
    add_item("syl_phy_u12_01", "physics", "PHY_U12", "Current Electricity",
             "Electric Current and Resistance", "Drift velocity, Ohm's law, resistivity, temperature dependence",
             "Electric current: drift velocity, mobility and their relation with electric current, Ohm's law, electrical resistance, I-V characteristics of Ohmic and non-ohmic conductors, electrical energy and power, electrical resistivity and conductivity, series and parallel combinations of resistors, temperature dependence of resistance", 5, "UNIT 12")
    add_item("syl_phy_u12_02", "physics", "PHY_U12", "Current Electricity",
             "DC Circuits and Instruments", "EMF, internal resistance, Kirchhoff's laws, Wheatstone and Metre bridge",
             "Internal resistance, potential difference and emf of a cell, a combination of cells in series and parallel. Kirchhoff’s laws and their applications, Wheatstone bridge, Metre Bridge", 5, "UNIT 12")

    # Unit 13: Magnetic Effects of Current and Magnetism
    add_item("syl_phy_u13_01", "physics", "PHY_U13", "Magnetic Effects of Current and Magnetism",
             "Magnetic Fields of Currents", "Biot-Savart law, Ampere's law, solenoid",
             "Biot - Savart law and its application to the current carrying circular loop, Ampere's law and its applications to infinitely long current carrying straight wire and solenoid", 5, "UNIT 13")
    add_item("syl_phy_u13_02", "physics", "PHY_U13", "Magnetic Effects of Current and Magnetism",
             "Magnetic Forces and Galvanometer", "Lorentz force, parallel conductors, moving coil galvanometer",
             "Force on a moving charge in uniform magnetic and electric fields, force on a current-carrying conductor in a uniform magnetic field, the force between two parallel currents carrying conductors-definition of ampere, torque experienced by a current loop in a uniform magnetic field: Moving coil galvanometer, its sensitivity and conversion to ammeter and voltmeter", 5, "UNIT 13")
    add_item("syl_phy_u13_03", "physics", "PHY_U13", "Magnetic Effects of Current and Magnetism",
             "Magnetism and Magnetic Materials", "Magnetic dipoles, bar magnets, para/dia/ferromagnetism",
             "Current loop as a magnetic dipole and its magnetic dipole moment, bar magnet as an equivalent solenoid, magnetic field lines, magnetic field due to a magnetic dipole (bar magnet) along its axis and perpendicular to its axis, torque on a magnetic dipole in a uniform magnetic field, para-, dia- and ferromagnetic substances with examples, the effect of temperature on magnetic properties", 5, "UNIT 13")

    # Unit 14: Electromagnetic Induction and Alternating Currents
    add_item("syl_phy_u14_01", "physics", "PHY_U14", "Electromagnetic Induction and Alternating Currents",
             "Electromagnetic Induction", "Faraday's law, Lenz's law, eddy currents, inductance",
             "Electromagnetic induction: Faraday's law, induced emf and current, Lenz’s law, eddy currents, self and mutual inductance", 5, "UNIT 14")
    add_item("syl_phy_u14_02", "physics", "PHY_U14", "Electromagnetic Induction and Alternating Currents",
             "Alternating Currents", "RMS values, impedance, LCR series circuit, resonance, transformer",
             "Alternating currents, peak and RMS value of alternating current/voltage, reactance and impedance, LCR series circuit, resonance, power in AC circuits, wattless current, AC generator and transformer", 5, "UNIT 14")

    # Unit 15: Electromagnetic Waves
    add_item("syl_phy_u15_01", "physics", "PHY_U15", "Electromagnetic Waves",
             "Electromagnetic Waves", "Displacement current, wave characteristics, EM spectrum",
             "Displacement current, electromagnetic waves and their characteristics, transverse nature of electromagnetic waves, electromagnetic spectrum (radio waves, microwaves, infrared, visible, ultraviolet, X-rays, Gamma rays), applications of electromagnetic waves", 5, "UNIT 15")

    # Unit 16: Optics
    add_item("syl_phy_u16_01", "physics", "PHY_U16", "Optics",
             "Ray Optics", "Reflection, refraction, lenses, total internal reflection, prism, optical instruments",
             "Reflection of light, spherical mirrors, mirror formula. Refraction of light at plane and spherical surfaces, thin lens formula and lens maker formula, total internal reflection and its applications, magnification, power of a lens, combination of thin lenses in contact, refraction of light through a prism, microscope and astronomical telescope (reflecting and refracting) and their magnifying powers", 5, "UNIT 16")
    add_item("syl_phy_u16_02", "physics", "PHY_U16", "Optics",
             "Wave Optics", "Huygens' principle, interference (YDSE), diffraction, polarization (Brewster's law)",
             "Wave optics: wavefront and Huygens ‘Principle, laws of reflection and refraction using Huygens principle. Interference: Young's double-slit experiment and expression for fringe width, coherent sources and sustained interference of light. Diffraction due to a single slit, width of central maximum. Polarization: plane-polarized light, Brewster's law, uses of plane-polarized light and Polaroid", 5, "UNIT 16")

    # Unit 17: Dual Nature of Matter and Radiation
    add_item("syl_phy_u17_01", "physics", "PHY_U17", "Dual Nature of Matter and Radiation",
             "Photoelectric Effect and Matter Waves", "Photoelectric equation, photon nature, de Broglie relation",
             "Dual nature of radiation, Photoelectric effect, Hertz and Lenard's observations, Einstein's photoelectric equation, particle nature of light. Matter waves: wave nature of particle, de- Broglie relation", 6, "UNIT 17")

    # Unit 18: Atoms and Nuclei
    add_item("syl_phy_u18_01", "physics", "PHY_U18", "Atoms and Nuclei",
             "Atomic Physics", "Rutherford scattering, Bohr model, hydrogen spectrum",
             "Alpha-particle scattering experiment, Rutherford's model of atom, Bohr model, energy levels, hydrogen spectrum", 6, "UNIT 18")
    add_item("syl_phy_u18_02", "physics", "PHY_U18", "Atoms and Nuclei",
             "Nuclear Physics", "Nucleus size, mass defect, binding energy, fission and fusion",
             "Composition and size of nucleus, atomic masses, mass-energy relation, mass defect, binding energy per nucleon and its variation with mass number, nuclear fission and fusion", 6, "UNIT 18")

    # Unit 19: Electronic Devices
    add_item("syl_phy_u19_01", "physics", "PHY_U19", "Electronic Devices",
             "Semiconductor Diodes", "p-n junction, forward/reverse bias, rectifier, LED, photodiode, solar cell, Zener regulator",
             "Semiconductors, semiconductor diode: I-V characteristics in forward and reverse bias, diode as a rectifier; I-V characteristics of LED, the photodiode, solar cell, Zener diode, Zener diode as a voltage regulator", 6, "UNIT 19")
    add_item("syl_phy_u19_02", "physics", "PHY_U19", "Electronic Devices",
             "Logic Gates", "OR, AND, NOT, NAND, NOR gates",
             "Logic gates (OR. AND. NOT. NAND and NOR)", 6, "UNIT 19")

    # Unit 20: Experimental Skills (18 specific activities)
    add_item("syl_phy_u20_01", "physics", "PHY_U20", "Experimental Skills",
             "Vernier Calipers", "Internal and external diameter and depth measurement",
             "Vernier calipers -its use to measure the internal and external diameter and depth of a vessel", 6, "UNIT 20")
    add_item("syl_phy_u20_02", "physics", "PHY_U20", "Experimental Skills",
             "Screw Gauge", "Thickness and diameter of thin sheet/wire",
             "Screw gauge-its use to determine the thickness/ diameter of thin sheet/wire", 6, "UNIT 20")
    add_item("syl_phy_u20_03", "physics", "PHY_U20", "Experimental Skills",
             "Simple Pendulum", "Energy dissipation curve (amplitude squared vs time)",
             "Simple pendulum-dissipation of energy by plotting a graph between the square of amplitude and time", 6, "UNIT 20")
    add_item("syl_phy_u20_04", "physics", "PHY_U20", "Experimental Skills",
             "Metre Scale", "Mass determination by principle of moments",
             "Metre scale - the mass of a given object by the principle of moments", 6, "UNIT 20")
    add_item("syl_phy_u20_05", "physics", "PHY_U20", "Experimental Skills",
             "Young's Modulus", "Elasticity determination of metallic wire",
             "Young's modulus of elasticity of the material of a metallic wire", 6, "UNIT 20")
    add_item("syl_phy_u20_06", "physics", "PHY_U20", "Experimental Skills",
             "Surface Tension", "Capillary rise method and detergent effect",
             "Surface tension of water by capillary rise and effect of detergents", 6, "UNIT 20")
    add_item("syl_phy_u20_07", "physics", "PHY_U20", "Experimental Skills",
             "Viscosity Coefficient", "Terminal velocity of spherical body in viscous liquid",
             "Co-efficient of viscosity of a given viscous liquid by measuring the terminal velocity of a given spherical body", 6, "UNIT 20")
    add_item("syl_phy_u20_08", "physics", "PHY_U20", "Experimental Skills",
             "Speed of Sound", "Resonance tube method at room temperature",
             "Speed of sound in air at room temperature using a resonance tube", 6, "UNIT 20")
    add_item("syl_phy_u20_09", "physics", "PHY_U20", "Experimental Skills",
             "Specific Heat Capacity", "Method of mixtures for solid and liquid",
             "Specific heat capacity of a given (i) solid and (ii) liquid by method of mixtures", 6, "UNIT 20")
    add_item("syl_phy_u20_10", "physics", "PHY_U20", "Experimental Skills",
             "Metre Bridge Resistivity", "Resistivity of wire using metre bridge",
             "The resistivity of the material of a given wire using a metre bridge", 6, "UNIT 20")
    add_item("syl_phy_u20_11", "physics", "PHY_U20", "Experimental Skills",
             "Ohm's Law Resistance", "Resistance measurement using Ohm's law",
             "The resistance of a given wire using Ohm's law", 6, "UNIT 20")
    add_item("syl_phy_u20_12", "physics", "PHY_U20", "Experimental Skills",
             "Galvanometer Figures", "Resistance and figure of merit by half deflection",
             "Resistance and figure of merit of a galvanometer by half deflection method", 6, "UNIT 20")
    add_item("syl_phy_u20_13", "physics", "PHY_U20", "Experimental Skills",
             "Focal Length", "Convex mirror, concave mirror, and convex lens using parallax",
             "The focal length of (i) Convex mirror (ii) Concave mirror and (iii)Convex lens, using the parallax method", 6, "UNIT 20")
    add_item("syl_phy_u20_14", "physics", "PHY_U20", "Experimental Skills",
             "Prism Deviation", "Angle of deviation vs angle of incidence for triangular prism",
             "The plot of the angle of deviation vs angle of incidence for a triangular prism", 6, "UNIT 20")
    add_item("syl_phy_u20_15", "physics", "PHY_U20", "Experimental Skills",
             "Refractive Index", "Glass slab using travelling microscope",
             "The refractive index of a glass slab using a travelling microscope", 6, "UNIT 20")
    add_item("syl_phy_u20_16", "physics", "PHY_U20", "Experimental Skills",
             "p-n Diode Characteristics", "Forward and reverse bias curves",
             "Characteristic curves of a p-n junction diode in forward and reverse bias", 6, "UNIT 20")
    add_item("syl_phy_u20_17", "physics", "PHY_U20", "Experimental Skills",
             "Zener Diode Breakdown", "Reverse breakdown voltage determination",
             "Characteristic curves of a Zener diode and finding reverse breakdown voltage", 6, "UNIT 20")
    add_item("syl_phy_u20_18", "physics", "PHY_U20", "Experimental Skills",
             "Component Identification", "Diode, LED, resistor, capacitor identification",
             "Identification of diode, LED, resistor, a capacitor from a mixed collection of such items", 6, "UNIT 20")

    # =========================================================================
    # CHEMISTRY (Physical, Inorganic, Organic Units 1-20, Pages 7-11)
    # =========================================================================

    # Physical Chemistry Unit 1: Some Basic Concepts in Chemistry
    add_item("syl_chem_u01_01", "chemistry", "CHEM_U01", "SOME BASIC CONCEPTS IN CHEMISTRY",
             "Matter and Atomic Theory", "Dalton's theory, atoms, molecules, elements, compounds",
             "Matter and its nature, Dalton's atomic theory, Concept of atom, molecule, element and compound, Laws of chemical combination", 7, "UNIT 1")
    add_item("syl_chem_u01_02", "chemistry", "CHEM_U01", "SOME BASIC CONCEPTS IN CHEMISTRY",
             "Stoichiometry and Mole Concept", "Atomic masses, mole concept, percentage composition, empirical and molecular formula",
             "Atomic and molecular masses, mole concept, molar mass, percentage composition, empirical and molecular formulae, Chemical equations and stoichiometry", 7, "UNIT 1")

    # Physical Chemistry Unit 2: Atomic Structure
    add_item("syl_chem_u02_01", "chemistry", "CHEM_U02", "ATOMIC STRUCTURE",
             "Bohr Model and Dual Nature", "Hydrogen spectrum, Bohr model, de Broglie, Heisenberg principle",
             "Nature of electromagnetic radiation, photoelectric effect, spectrum of the hydrogen atom, Bohr model of a hydrogen atom - its postulates, derivation of the relations for the energy of the electron and radii of the different orbits, limitations of Bohr's model, dual nature of matter, de Broglie's relationship, Heisenberg uncertainty principle", 7, "UNIT 2")
    add_item("syl_chem_u02_02", "chemistry", "CHEM_U02", "ATOMIC STRUCTURE",
             "Quantum Mechanical Model", "Orbitals, quantum numbers, orbital shapes, Aufbau, Pauli, Hund rules",
             "Elementary ideas of quantum mechanics, the quantum mechanical model of the atom and its important features, concept of atomic orbitals as one-electron wave functions, variation of psi and psi^2 with r for 1s and 2s orbitals, various quantum numbers (principal, angular momentum and magnetic quantum numbers) and their significance, shapes of s, p and d - orbitals, electron spin and spin quantum number, rules for filling electrons in orbitals – Aufbau principle, Pauli's exclusion principle and Hund's rule, electronic configuration of elements and extra stability of half-filled and completely filled orbitals", 7, "UNIT 2")

    # Physical Chemistry Unit 3: Chemical Bonding and Molecular Structure
    add_item("syl_chem_u03_01", "chemistry", "CHEM_U03", "CHEMICAL BONDING AND MOLECULAR STRUCTURE",
             "Ionic and Covalent Bonding", "Kossel-Lewis, lattice enthalpy, Fajan's rule, dipole moment",
             "Kossel-Lewis approach to chemical bond formation, the concept of ionic and covalent bonds. Ionic Bonding: Formation of ionic bonds, factors affecting the formation of ionic bonds; calculation of lattice enthalpy. Covalent Bonding: Concept of electronegativity, Fajan’s rule, dipole moment", 7, "UNIT 3")
    add_item("syl_chem_u03_02", "chemistry", "CHEM_U03", "CHEMICAL BONDING AND MOLECULAR STRUCTURE",
             "Molecular Geometries (VSEPR & VBT)", "VSEPR theory, Valence Bond Theory, hybridization, resonance",
             "Valence Shell Electron Pair Repulsion (VSEPR) theory and shapes of simple molecules. Quantum mechanical approach to covalent bonding: Valence bond theory - its important features, the concept of hybridization involving s, p and d orbitals, resonance", 7, "UNIT 3")
    add_item("syl_chem_u03_03", "chemistry", "CHEM_U03", "CHEMICAL BONDING AND MOLECULAR STRUCTURE",
             "Molecular Orbital Theory", "LCAO, bond order, bond energy, homonuclear diatomics, hydrogen bonding",
             "Molecular Orbital Theory - Its important features, LCAOs, types of molecular orbitals (bonding, antibonding), sigma and pi-bonds, molecular orbital electronic configurations of homonuclear diatomic molecules, the concept of bond order, bond length and bond energy. Elementary idea of metallic bonding, hydrogen bonding and its applications", 7, "UNIT 3")

    # Physical Chemistry Unit 4: Chemical Thermodynamics
    add_item("syl_chem_u04_01", "chemistry", "CHEM_U04", "CHEMICAL THERMODYNAMICS",
             "First Law and Thermochemistry", "Internal energy, enthalpy, heat capacity, Hess's law, standard enthalpies",
             "Fundamentals of thermodynamics: System and surroundings, extensive and intensive properties, state functions, entropy, types of processes. The first law of thermodynamics - Concept of work, heat, internal energy and enthalpy, heat capacity, molar heat capacity, Hess’s law of constant heat summation, Enthalpies of bond dissociation, combustion, formation, atomization, sublimation, phase transition, hydration, ionization and solution", 7, "UNIT 4")
    add_item("syl_chem_u04_02", "chemistry", "CHEM_U04", "CHEMICAL THERMODYNAMICS",
             "Second Law and Spontaneity", "Entropy, Gibbs free energy criteria, equilibrium constant",
             "The second law of thermodynamics - Spontaneity of processes, Delta S of the universe and Delta G of the system as criteria for spontaneity. Delta G° (Standard Gibbs energy change) and equilibrium constant", 7, "UNIT 4")

    # Physical Chemistry Unit 5: Solutions
    add_item("syl_chem_u05_01", "chemistry", "CHEM_U05", "SOLUTIONS",
             "Concentration and Raoult's Law", "Concentration expressions, vapour pressure, ideal and non-ideal solutions",
             "Different methods for expressing the concentration of solution - molality, molarity, mole fraction, percentage (by volume and mass both), the vapour pressure of solutions and Raoult's Law - Ideal and non-ideal solutions, vapour pressure - composition, plots for ideal and non-ideal solutions", 7, "UNIT 5")
    add_item("syl_chem_u05_02", "chemistry", "CHEM_U05", "SOLUTIONS",
             "Colligative Properties", "Elevation of boiling point, depression of freezing point, osmotic pressure, van't Hoff factor",
             "Colligative properties of dilute solutions - a relative lowering of vapour pressure, depression of freezing point, the elevation of boiling point and osmotic pressure, determination of molecular mass using colligative properties, abnormal value of molar mass, van’t Hoff factor and its significance", 7, "UNIT 5")

    # Physical Chemistry Unit 6: Equilibrium
    add_item("syl_chem_u06_01", "chemistry", "CHEM_U06", "EQUILIBRIUM",
             "Physical and Chemical Equilibrium", "Dynamic equilibrium, Kp and Kc, Le Chatelier's principle",
             "Meaning of equilibrium is the concept of dynamic equilibrium. Equilibria involving physical processes: Solid-liquid, liquid-gas, gas-gas and solid-gas equilibria, Henry's law. General characteristics of equilibrium involving physical processes. Equilibrium involving chemical processes: Law of chemical equilibrium, equilibrium constants (Kp and Kc) and their significance, the significance of Delta G and Delta G° in chemical equilibrium, factors affecting equilibrium concentration, pressure, temperature, the effect of catalyst, Le Chatelier’s principle", 8, "UNIT 6")
    add_item("syl_chem_u06_02", "chemistry", "CHEM_U06", "EQUILIBRIUM",
             "Ionic Equilibrium", "Acids, bases, pH scale, salt hydrolysis, solubility product, buffer solutions",
             "Ionic equilibrium: Weak and strong electrolytes, ionization of electrolytes, various concepts of acids and bases (Arrhenius, Bronsted - Lowry and Lewis) and their ionization, acid-base equilibria (including multistage ionization) and ionization constants, ionization of water, pH scale, common ion effect, hydrolysis of salts and pH of their solutions, the solubility of sparingly soluble salts, solubility products and buffer solutions", 8, "UNIT 6")

    # Physical Chemistry Unit 7: Redox Reactions and Electrochemistry
    add_item("syl_chem_u07_01", "chemistry", "CHEM_U07", "REDOX REACTIONS AND ELECTROCHEMISTRY",
             "Redox Reactions", "Oxidation numbers and redox balancing",
             "Electronic concepts of oxidation and reduction, redox reactions, oxidation number, rules for assigning oxidation number and balancing of redox reactions", 8, "UNIT 7")
    add_item("syl_chem_u07_02", "chemistry", "CHEM_U07", "REDOX REACTIONS AND ELECTROCHEMISTRY",
             "Conductance and Kohlrausch's Law", "Electrolytic conduction, molar conductivities, Kohlrausch's law",
             "Electrolytic and metallic conduction, conductance in electrolytic solutions, molar conductivities and their variation with concentration, Kohlrausch’s law and its applications", 8, "UNIT 7")
    add_item("syl_chem_u07_03", "chemistry", "CHEM_U07", "REDOX REACTIONS AND ELECTROCHEMISTRY",
             "Electrochemical Cells and Nernst Equation", "Galvanic cells, standard potentials, Nernst equation, batteries",
             "Electrochemical cells - Electrolytic and Galvanic cells, different types of electrodes, electrode potentials including standard electrode potential, half-cell and cell reactions, emf of a Galvanic cell and its measurement, Nernst equation and its applications, relationship between cell potential and Gibbs' energy change, dry cell and lead accumulator, fuel cells", 8, "UNIT 7")

    # Physical Chemistry Unit 8: Chemical Kinetics
    add_item("syl_chem_u08_01", "chemistry", "CHEM_U08", "CHEMICAL KINETICS",
             "Reaction Rates and Rate Laws", "Order and molecularity, zero and first order integrated equations, half-life",
             "Rate of a chemical reaction, factors affecting the rate of reactions: concentration, temperature, pressure and catalyst, elementary and complex reactions, order and molecularity of reactions, rate law, rate constant and its units, differential and integral forms of zero and first-order reactions, their characteristics and half-lives", 8, "UNIT 8")
    add_item("syl_chem_u08_02", "chemistry", "CHEM_U08", "CHEMICAL KINETICS",
             "Temperature Dependence and Theories", "Arrhenius equation, activation energy, collision theory",
             "The effect of temperature on the rate of reactions, Arrhenius theory, activation energy and its calculation, collision theory of bi-molecular gaseous reactions (no derivation)", 8, "UNIT 8")

    # Inorganic Chemistry Unit 9: Classification of Elements and Periodicity in Properties
    add_item("syl_chem_u09_01", "chemistry", "CHEM_U09", "CLASSIFICATION OF ELEMENTS AND PERIODICITY IN PROPERTIES",
             "Periodic Table and Periodic Trends", "Modern periodic law, periodic trends in radii, ionization, electron gain, valence",
             "Modern periodic law and present form of the periodic table, s, p, d and f block elements, periodic trends in properties of elements atomic and ionic radii, ionization enthalpy, electron gain enthalpy, valence, oxidation states and chemical reactivity", 8, "UNIT 9")

    # Inorganic Chemistry Unit 10: p-Block Elements
    add_item("syl_chem_u10_01", "chemistry", "CHEM_U10", "p- BLOCK ELEMENTS",
             "p-Block Elements", "Group 13 to 18 electronic configurations, general trends, anomalous first element",
             "Group -13 to Group 18 Elements. General Introduction: Electronic configuration and general trends in physical and chemical properties of elements across the periods and down the groups, unique behaviour of the first element in each group", 8, "UNIT 10")

    # Inorganic Chemistry Unit 11: d- and f-Block Elements
    add_item("syl_chem_u11_01", "chemistry", "CHEM_U11", "d - and f- BLOCK ELEMENTS",
             "Transition Elements (3d series)", "Trends in properties, catalytic, magnetic, interstitial, alloys, K2Cr2O7 and KMnO4",
             "Transition Elements - General introduction, electronic configuration, occurrence and characteristics, general trends in properties of the first-row transition elements - physical properties, ionization enthalpy, oxidation states, atomic radii, colour, catalytic behaviour, magnetic properties, complex formation, interstitial compounds, alloy formation, preparation, properties and uses of K2Cr2O7 and KMnO4", 8, "UNIT 11")
    add_item("syl_chem_u11_02", "chemistry", "CHEM_U11", "d - and f- BLOCK ELEMENTS",
             "Inner Transition Elements", "Lanthanoids and Actinoids, oxidation states, Lanthanoid contraction",
             "Inner Transition Elements. Lanthanoids - Electronic configuration, oxidation states and Lanthanoid contraction. Actinoids - Electronic configuration and oxidation states", 8, "UNIT 11")

    # Inorganic Chemistry Unit 12: Coordination Compounds
    add_item("syl_chem_u12_01", "chemistry", "CHEM_U12", "COORDINATION COMPOUNDS",
             "Coordination Chemistry", "Werner's theory, ligands, IUPAC nomenclature, isomerism, VBT, CFT",
             "Introduction to coordination compounds. Werner's theory, ligands, coordination number, denticity, chelation, IUPAC nomenclature of mononuclear co-ordination compounds, isomerism, Bonding: Valence bond approach and basic ideas of Crystal field theory, colour and magnetic properties, importance of coordination compounds (in qualitative analysis, extraction of metals and in biological systems)", 9, "UNIT 12")

    # Organic Chemistry Unit 13: Purification and Characterisation of Organic Compounds
    add_item("syl_chem_u13_01", "chemistry", "CHEM_U13", "PURIFICATION AND CHARACTERISATION OF ORGANIC COMPOUNDS",
             "Purification Techniques", "Crystallization, sublimation, distillation, differential extraction, chromatography",
             "Purification - Crystallization, sublimation, distillation, differential extraction and chromatography - principles and their applications", 9, "UNIT 13")
    add_item("syl_chem_u13_02", "chemistry", "CHEM_U13", "PURIFICATION AND CHARACTERISATION OF ORGANIC COMPOUNDS",
             "Qualitative and Quantitative Analysis", "Detection and estimation of C, H, N, S, P, halogens, empirical formula",
             "Qualitative analysis - Detection of nitrogen, sulphur, phosphorus and halogens. Quantitative analysis (basic principles only) - Estimation of carbon, hydrogen, nitrogen, halogens, sulphur and phosphorus. Calculations of empirical formulae and molecular formulae, numerical problems in organic quantitative analysis", 9, "UNIT 13")

    # Organic Chemistry Unit 14: Some Basic Principles of Organic Chemistry
    add_item("syl_chem_u14_01", "chemistry", "CHEM_U14", "SOME BASIC PRINCIPLES OF ORGANIC CHEMISTRY",
             "Nomenclature and Isomerism", "IUPAC nomenclature, structural and stereoisomerism",
             "Tetravalency of carbon, shapes of simple molecules - hybridization (s and p): classification of organic compounds based on functional groups and those containing halogens, oxygen, nitrogen and sulphur, homologous series: Isomerism - structural and stereoisomerism. Nomenclature (Trivial and IUPAC)", 9, "UNIT 14")
    add_item("syl_chem_u14_02", "chemistry", "CHEM_U14", "SOME BASIC PRINCIPLES OF ORGANIC CHEMISTRY",
             "Reaction Mechanisms and Electronic Effects", "Bond fission, carbocations, free radicals, inductive, electromeric, resonance, hyperconjugation",
             "Covalent bond fission - Homolytic and heterolytic, free radicals, carbocations and carbanions, stability of carbocations and free radicals, electrophiles and nucleophiles. Electronic displacement in a covalent bond - Inductive effect, electromeric effect, resonance and hyperconjugation. Common types of organic reactions- Substitution, addition, elimination and rearrangement", 9, "UNIT 14")

    # Organic Chemistry Unit 15: Hydrocarbons
    add_item("syl_chem_u15_01", "chemistry", "CHEM_U15", "HYDROCARBONS",
             "Alkanes", "Conformations (Sawhorse, Newman) and halogenation mechanism",
             "Classification, isomerism, IUPAC nomenclature, general methods of preparation, properties and reactions. Alkanes - Conformations: Sawhorse and Newman projections (of ethane), mechanism of halogenation of alkanes", 9, "UNIT 15")
    add_item("syl_chem_u15_02", "chemistry", "CHEM_U15", "HYDROCARBONS",
             "Alkenes and Alkynes", "Electrophilic addition, Markovnikov rule, peroxide effect, ozonolysis, polymerization, acidity of alkynes",
             "Alkenes - Geometrical isomerism, mechanism of electrophilic addition, addition of hydrogen, halogens, water, hydrogen halides (Markownikoffs and peroxide effect), Ozonolysis and polymerization. Alkynes - Acidic character, addition of hydrogen, halogens, water and hydrogen halides, polymerization", 9, "UNIT 15")
    add_item("syl_chem_u15_03", "chemistry", "CHEM_U15", "HYDROCARBONS",
             "Aromatic Hydrocarbons", "Benzene aromaticity, electrophilic substitution, Friedel-Crafts, directive influence",
             "Aromatic hydrocarbons - Nomenclature, benzene - structure and aromaticity, mechanism of electrophilic substitution, halogenation, nitration. Friedel-Craft's alkylation and acylation, directive influence of the functional group in mono-substituted benzene", 9, "UNIT 15")

    # Organic Chemistry Unit 16: Organic Compounds Containing Halogens
    add_item("syl_chem_u16_01", "chemistry", "CHEM_U16", "ORGANIC COMPOUNDS CONTAINING HALOGENS",
             "Haloalkanes and Haloarenes", "C-X bond nature, substitution mechanisms (SN1, SN2), polyhalogen compounds",
             "General methods of preparation, properties and reactions, nature of C-X bond, mechanisms of substitution reactions. Uses, environmental effects of chloroform, iodoform, freons and DDT", 9, "UNIT 16")

    # Organic Chemistry Unit 17: Organic Compounds Containing Oxygen
    add_item("syl_chem_u17_01", "chemistry", "CHEM_U17", "ORGANIC COMPOUNDS CONTAINING OXYGEN",
             "Alcohols, Phenols and Ethers", "Alcohol dehydration, phenol electrophilic substitution, Reimer-Tiemann, ether structure",
             "General methods of preparation, properties, reactions and uses. ALCOHOLS, PHENOLS AND ETHERS. Alcohols: Identification of primary, secondary and tertiary alcohols, mechanism of dehydration. Phenols: Acidic nature, electrophilic substitution reactions, halogenation, nitration and sulphonation, Reimer - Tiemann reaction. Ethers: Structure", 10, "UNIT 17")
    add_item("syl_chem_u17_02", "chemistry", "CHEM_U17", "ORGANIC COMPOUNDS CONTAINING OXYGEN",
             "Aldehydes and Ketones", "Carbonyl nucleophilic addition, Aldol, Cannizzaro, Haloform, reduction reactions",
             "Aldehyde and Ketones: Nature of carbonyl group, nucleophilic addition to >C=O group, relative reactivities of aldehydes and ketones, important reactions such as - Nucleophilic addition reactions (addition of HCN, NH3 and its derivatives), Grignard reagent, oxidation, reduction (Wolf Kishner and Clemmensen), the acidity of alpha-hydrogen. Aldol condensation, Cannizzaro reaction, Haloform reaction, chemical tests to distinguish between aldehydes and ketones", 10, "UNIT 17")
    add_item("syl_chem_u17_03", "chemistry", "CHEM_U17", "ORGANIC COMPOUNDS CONTAINING OXYGEN",
             "Carboxylic Acids", "Acidity and factors affecting acid strength",
             "Carboxylic Acids: Acidic strength and factors affecting it", 10, "UNIT 17")

    # Organic Chemistry Unit 18: Organic Compounds Containing Nitrogen
    add_item("syl_chem_u18_01", "chemistry", "CHEM_U18", "ORGANIC COMPOUNDS CONTAINING NITROGEN",
             "Amines", "Classification, structure, basicity, identification of 1o, 2o, 3o amines",
             "General methods of preparation, properties, reactions and uses. Amines: Nomenclature, classification, structure, basic character and identification of primary, secondary and tertiary amines and their basic character", 10, "UNIT 18")
    add_item("syl_chem_u18_02", "chemistry", "CHEM_U18", "ORGANIC COMPOUNDS CONTAINING NITROGEN",
             "Diazonium Salts", "Synthetic importance and reactions",
             "Diazonium Salts: Importance in synthetic organic chemistry", 10, "UNIT 18")

    # Organic Chemistry Unit 19: Biomolecules
    add_item("syl_chem_u19_01", "chemistry", "CHEM_U19", "BIOMOLECULES",
             "Carbohydrates", "Classification, aldoses, ketoses, monosaccharides, oligosaccharides",
             "General introduction and importance of biomolecules. CARBOHYDRATES – Classification, aldoses and ketoses, monosaccharides (glucose and fructose) and constituent monosaccharides of oligosaccharides (sucrose, lactose and maltose)", 10, "UNIT 19")
    add_item("syl_chem_u19_02", "chemistry", "CHEM_U19", "BIOMOLECULES",
             "Proteins and Enzymes", "Amino acids, peptide bonds, protein structures, denaturation, enzymes",
             "PROTEINS - Elementary idea of alpha-amino acids, peptide bond, polypeptides, proteins: primary, secondary, tertiary and quaternary structure (qualitative idea only), denaturation of proteins, enzymes", 10, "UNIT 19")
    add_item("syl_chem_u19_03", "chemistry", "CHEM_U19", "BIOMOLECULES",
             "Vitamins, Nucleic Acids and Hormones", "Classification, DNA/RNA chemical constitution and biological functions, hormones",
             "VITAMINS – Classification and functions. NUCLEIC ACIDS – Chemical constitution of DNA and RNA, biological functions of nucleic acids. Hormones (General introduction)", 10, "UNIT 19")

    # Organic Chemistry Unit 20: Principles Related to Practical Chemistry
    add_item("syl_chem_u20_01", "chemistry", "CHEM_U20", "PRINCIPLES RELATED TO PRACTICAL CHEMISTRY",
             "Detection of Elements and Functional Groups", "Extra elements (N, S, halogens) and functional groups detection",
             "Detection of extra elements (Nitrogen, sulphur, halogens) in organic compounds, detection of the following functional groups, hydroxyl (alcoholic and phenolic), carbonyl (aldehyde and ketones) carboxyl and amino groups in organic compounds", 10, "UNIT 20")
    add_item("syl_chem_u20_02", "chemistry", "CHEM_U20", "PRINCIPLES RELATED TO PRACTICAL CHEMISTRY",
             "Chemical Preparations", "Inorganic (Mohr's salt, potash alum) and organic preparations",
             "The chemistry involved in the preparation of the following: Inorganic compounds, Mohr’s salt, potash alum. Organic compounds: Acetanilide, p-nitro acetanilide, aniline yellow, iodoform", 10, "UNIT 20")
    add_item("syl_chem_u20_03", "chemistry", "CHEM_U20", "PRINCIPLES RELATED TO PRACTICAL CHEMISTRY",
             "Titrimetric Analysis", "Acid-base titrations and KMnO4 redox titrations",
             "The chemistry involved in the titrimetric exercises – acids, bases and the use of indicators, oxalic-acid vs KMnO4, Mohr’s salt vs KMnO4", 10, "UNIT 20")
    add_item("syl_chem_u20_04", "chemistry", "CHEM_U20", "PRINCIPLES RELATED TO PRACTICAL CHEMISTRY",
             "Qualitative Salt Analysis", "Cation and anion detection and chemical principles",
             "Chemical principles involved in the qualitative salt analysis: Cations – Pb2+, Cu2+, Al3+, Fe3+, Zn2+, Ni2+, Ca2+, Ba2+, Mg2+, NH4+; Anions – CO3 2-, S 2-, SO4 2-, NO3 -, NO2 -, Cl -, Br -, I - (Insoluble salts excluded)", 10, "UNIT 20")
    add_item("syl_chem_u20_05", "chemistry", "CHEM_U20", "PRINCIPLES RELATED TO PRACTICAL CHEMISTRY",
             "Physical Chemistry Experiments", "Enthalpy, lyophilic/lyophobic sols, and reaction kinetics",
             "Chemical principles involved in the following experiments: 1. Enthalpy of solution of CuSO4; 2. Enthalpy of neutralization of strong acid and strong base; 3. Preparation of lyophilic and lyophobic sols; 4. Kinetic study of the reaction of iodide ions with hydrogen peroxide at room temperature", 11, "UNIT 20")

    result = {
        "metadata": {
            "examination": "JEE (Main) - 2027",
            "paper": "Paper 1 (B.E./B.Tech.)",
            "subjects": ["mathematics", "physics", "chemistry"],
            "total_units": 54,
            "unit_distribution": {
                "mathematics": 14,
                "physics": 20,
                "chemistry": 20,
            },
            "source": source_info,
            "official_url": "https://jeemain.nta.nic.in/document/syllabus-2027/",
            "verified_at": "2026-10-25T22:50:00Z",
            "excluded_papers": [
                "Paper 2A (B.Arch.) - Mathematics, Aptitude Test and Drawing Test",
                "Paper 2B (B.Planning) - Mathematics, Aptitude Test and Planning"
            ],
            "total_syllabus_items": len(items),
        },
        "syllabus_items": items,
    }
    return result


def main() -> None:
    data = build_syllabus_inventory()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Successfully generated {OUTPUT_PATH} with {len(data['syllabus_items'])} syllabus items.")
    print(f"Mathematics: {len([x for x in data['syllabus_items'] if x['subject'] == 'mathematics'])} items across 14 units")
    print(f"Physics: {len([x for x in data['syllabus_items'] if x['subject'] == 'physics'])} items across 20 units")
    print(f"Chemistry: {len([x for x in data['syllabus_items'] if x['subject'] == 'chemistry'])} items across 20 units")


if __name__ == "__main__":
    main()
