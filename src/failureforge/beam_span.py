"""Transverse point and patch loads for a prismatic cantilever in one bending plane."""
from math import fsum, sqrt

import numpy as np


def load_terms(model):
    """Signed resultant in N on each fractional interval; coincident ends represent a point."""
    terms = [(1., 1., model.tip_force_n), (0., 1., model.transverse_load_n_per_m * model.length_m)]
    terms.extend((p.start_fraction, p.end_fraction, p.force_n) for p in model.span_loads or ())
    return [(a, b, force) for a, b, force in terms if force]


def load_profile(terms):
    """Group equivalent forces, including contiguous patches with equal load density."""
    points, patches = [], []
    edges = sorted({s for a, b, _ in terms for s in (a, b)} | {0., 1.})
    for x in edges:
        force = fsum(f for a, b, f in terms if a == b == x)
        if force:
            points.append((x, x, force))
    for a, b in zip(edges, edges[1:]):
        density = fsum(f / (end-start) for start, end, f in terms if start <= a and end >= b)
        if density:
            if patches and patches[-1][1] == a and patches[-1][2] == density:
                patches[-1] = (patches[-1][0], b, density)
            else:
                patches.append((a, b, density))
    # Interval weight is N per unit of normalized span; point weight is N.
    return sorted(points + patches)


def _shape(r, h):
    """Cubic Hermite translations/rotations at local fraction r of an element."""
    return np.array([(1-r)**2*(1+2*r), h*r*(1-r)**2, r*r*(3-2*r), -h*r*r*(1-r)])


def add_span_forces(rhs, model, n, rigidity):
    h = 1 / n
    scale = model.length_m**3 / rigidity
    for patch in model.span_loads:
        a, b = patch.start_fraction, patch.end_fraction
        force = patch.force_n * scale
        if a == b:
            element = min(int(a*n), n-1)
            rhs[2*element:2*element+4] += force * _shape(a*n-element, h)
            continue
        for element in range(int(a*n), min(int(b*n)+1, n)):
            lower, upper = max(a, element/n), min(b, (element+1)/n)
            if upper <= lower:
                continue
            # Two-point Gauss quadrature exactly integrates the cubic shape over
            # the loaded subinterval, including boundaries between mesh nodes.
            center = (lower+upper)*n/2 - element
            offset = (upper-lower)*n/(2*sqrt(3))
            weight = force * (upper-lower)/(2*(b-a))
            rhs[2*element:2*element+4] += weight * (_shape(center-offset, h) + _shape(center+offset, h))


def continuous_peaks(model):
    """Integrate piecewise equilibrium and find all slope and shear zeros on each interval."""
    length = model.length_m
    inertia = model.width_m * model.height_m**3 / 12
    rigidity = model.young_modulus_pa * inertia
    terms = load_terms(model)
    edges = sorted({s for a, b, _ in terms for s in (a, b)} | {0., 1.})
    sections = []
    shear = moment = 0.
    for a, b in reversed(list(zip(edges, edges[1:]))):
        h = (b-a)*length
        shear += fsum(f for start, end, f in terms if start == end == b)
        q = fsum(f / ((end-start)*length) for start, end, f in terms if start <= a and end >= b)
        moment += h*(shear + q*h/2)
        shear += q*h
        sections.append((h, moment, shear, q))
    position = rotation = peak_displacement = peak_moment = 0.
    for h, left_moment, left_shear, q in reversed(sections):
        # Normalized coordinate t lies in [0,1]. EI * curvature = moment.
        m0, m1, m2 = left_moment, -left_shear*h, q*h*h/2
        slope = np.polynomial.Polynomial([rotation, h*m0/rigidity, h*m1/(2*rigidity), h*m2/(3*rigidity)])
        deflection = slope.integ(lbnd=0) * h + position
        stationary = [float(r.real) for r in slope.trim().roots() if abs(r.imag) < 1e-12 and 0 < r.real < 1]
        peak_displacement = max(peak_displacement, *(abs(float(deflection(t))) for t in (0., 1., *stationary)))
        moments = [m0, m0+m1+m2]
        if m2 and 0 < (turn := -m1/(2*m2)) < 1:
            moments.append(m0 + turn*(m1 + turn*m2))
        peak_moment = max(peak_moment, *map(abs, moments))
        position, rotation = float(deflection(1.)), float(slope(1.))
    return peak_displacement, peak_moment*model.height_m/(2*inertia)
