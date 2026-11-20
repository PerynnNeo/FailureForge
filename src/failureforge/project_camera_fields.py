"""Inspection cameras driven by recorded project fields, geometry and joint angles."""
import math

import numpy as np

from .camera_scene import Camera, Frame, Object3D, Scene


_SWEEP_SECONDS = 5.0
_ALONG_X = np.array([[0., 0., 1.], [0., 1., 0.], [-1., 0., 0.]])
_COLD = np.array([0.09, 0.31, 0.68])
_MIDDLE = np.array([0.20, 0.67, 0.72])
_HOT = np.array([0.94, 0.37, 0.08])
_DARK = (0.16, 0.22, 0.26)
_MARKER = (0.91, 0.86, 0.54)
_MEASURED = (0.16, 0.76, 0.69)
_PREDICTED = (0.98, 0.52, 0.19)


def _numbers(value, shape):
    if not isinstance(value, (list, tuple, np.ndarray)):
        return None
    try:
        values = np.asarray(value)
    except (ValueError, TypeError):
        return None
    if values.dtype.kind not in 'iuf' or values.ndim != len(shape):
        return None
    if any(expected is not None and actual != expected for expected, actual in zip(shape, values.shape)):
        return None
    return values.astype(float) if np.isfinite(values).all() else None


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _field_color(value, lo, hi):
    t = (value - lo) / (hi - lo) if hi > lo else 0.5
    a, b, amount = (_COLD, _MIDDLE, 2*t) if t < 0.5 else (_MIDDLE, _HOT, 2*t-1)
    return tuple(a + (b-a)*amount)


def _sample_indices(values):
    # The exact minimum and maximum remain visible even for refined high-density fields.
    indices = np.linspace(0, len(values)-1, min(len(values), 44), dtype=int)
    return np.unique(np.append(indices, [np.argmin(values), np.argmax(values)]))


def _cameras(center, size, focus, close_size):
    center, focus = np.asarray(center), np.asarray(focus)
    return (Camera(center + np.array([0.80, -1.75, 0.89])*size, center),
            Camera(focus + np.array([-0.35, -1.60, 0.67])*close_size, focus))


def comparison_scale(first, second):
    """One color domain and one displacement magnification for both saved fields."""
    adapter = first.get('adapter')
    if adapter != second.get('adapter') or adapter not in ('thermal_rod', 'structural_beam'):
        return None
    bounds, starts, ends, spans, widths, heights = [], [], [], [], [], []
    for run in (first, second):
        result = run.get('result') or {}
        traces = result.get('traces') or {}
        x = _numbers(traces.get('node_position_m'), (None,))
        if x is None or not 2 <= len(x) <= 4096 or np.any(np.diff(x) <= 0):
            return None
        channel = 'temperature_k' if adapter == 'thermal_rod' else 'displacement_m'
        values = _numbers(traces.get(channel), (len(x),))
        if values is None:
            return None
        spans.append(float(x[-1] - x[0]))
        starts.append(float(x[0]))
        ends.append(float(x[-1]))
        bounds.extend((float(values.min()), float(values.max())))
        inputs = result.get('inputs') or run.get('inputs') or {}
        if adapter == 'thermal_rod':
            if not _positive(inputs.get('area_m2')):
                return None
            widths.append(2*math.sqrt(inputs['area_m2']/math.pi))
            limit = inputs.get('max_temperature_k')
            if _positive(limit):
                bounds.append(limit)
        else:
            if not all(_positive(inputs.get(k)) for k in ('width_m', 'height_m')):
                return None
            widths.append(inputs['width_m'])
            heights.append(inputs['height_m'])
    lo, hi = min(bounds), max(bounds)
    span = max(ends) - min(starts)
    scale = {'lo': lo, 'hi': hi, 'center_x': (min(starts) + max(ends))/2, 'center_z': 0.,
             'overview_size': max(.60*span, max(widths)), 'detail_size': max(.18*span, 1.65*max(widths))}
    if adapter == 'structural_beam':
        peak = max(abs(lo), abs(hi))
        scale['gain'] = max(1., min(10000., .075*min(spans)/peak)) if peak else 1.
        scale['center_z'] = (lo+hi)*scale['gain']/2
        scale['overview_size'] = max(scale['overview_size'], (hi-lo)*scale['gain']+max(heights))
        scale['detail_size'] = max(.18*span, 1.8*max(widths), 3*max(heights))
    return scale


def _station_scene(result, inputs, rod, scale=None, mark_events=True):
    traces = result.get('traces') or {}
    x = _numbers(traces.get('node_position_m'), (None,))
    if x is None or not 2 <= len(x) <= 4096 or np.any(np.diff(x) <= 0):
        return None
    values = _numbers(traces.get('temperature_k' if rod else 'displacement_m'), (len(x),))
    if values is None:
        return None
    span = x[-1] - x[0]
    lo, hi = float(values.min()), float(values.max())
    if scale:
        lo, hi = scale['lo'], scale['hi']
    ids = _sample_indices(values)
    objects, positions, rotations = [], [], []
    if rod:
        if not _positive(inputs.get('area_m2')):
            return None
        radius = math.sqrt(inputs['area_m2']/math.pi)
        limit = inputs.get('max_temperature_k')
        above = np.flatnonzero(values > limit) if mark_events and _positive(limit) else []
        if len(above):
            # Retain the adjacent samples bracketing the threshold even when reducing a dense mesh.
            ids = np.unique(np.r_[ids, max(0, above[0]-1), above[0]])
        z = np.zeros_like(x)
        extent = max(0.60*span, 2*radius)
        floor_z = -radius*1.12
        close_size = max(span*0.18, radius*3.3)
        # Give each displayed node its own color band, bounded by the adjacent midpoints.
        edges = np.r_[x[0], (x[ids[:-1]] + x[ids[1:]])/2, x[-1]]
        for index, start, end in zip(ids, edges[:-1], edges[1:]):
            objects.append(Object3D('cylinder', (radius, (end-start)/2), _field_color(values[index], lo, hi)))
            positions.append(((start+end)/2, 0., 0.))
            rotations.append(_ALONG_X)
        if len(above):
            objects.append(Object3D('cylinder', (1.13*radius, min(span*.0035, radius*.2)), (.86, .18, .52)))
            positions.append((x[above[0]], 0., 0.))
            rotations.append(_ALONG_X)
        objects.append(Object3D('cylinder', (1.075*radius, min(span*0.0025, radius*0.12)), _MARKER))
        rotations.append(_ALONG_X)
        description = ('Steady temperature field from saved simulation nodes. '
                       'A circular section represents the declared area. The gold band scans the span. ')
        description += (f'Blue is {lo:.6g} K and orange is {hi:.6g} K.' if hi > lo else f'Uniform temperature {lo:.6g} K.')
        if len(above):
            i = above[0]
            description += (f' The fixed pink ring marks the first node above {limit:g} K from the left end, '
                            f'at {x[i]:.7g} m and {values[i]:.7g} K.')
    else:
        width, height = inputs.get('width_m'), inputs.get('height_m')
        if not _positive(width) or not _positive(height):
            return None
        peak = max(abs(lo), abs(hi))
        gain = max(1., min(10000., 0.075*span/peak)) if peak else 1.
        if scale:
            gain = scale['gain']
        z = values * gain
        extent = max(0.60*span, width, np.ptp(z)+height)
        floor_z = float(z.min()-max(0.65*height, 0.03*span))
        close_size = max(span*0.18, width*1.8, height*3)
        for left, right in zip(ids[:-1], ids[1:]):
            dx, dz = x[right]-x[left], z[right]-z[left]
            length = math.hypot(dx, dz)
            c, s = dx/length, dz/length
            color = _field_color(float((values[right]+values[left])/2), lo, hi)
            objects.append(Object3D('box', (length/2, width/2, height/2), color))
            positions.append(((x[left]+x[right])/2, 0., (z[left]+z[right])/2))
            rotations.append(np.array([[c,0,-s], [0,1,0], [s,0,c]]))
        objects.append(Object3D('box', (span*0.003, width*0.55, height*0.56), _MARKER))
        rotations.append(np.eye(3))
        description = (f'Static beam from saved dimensions and nodal deflections. Displayed deflection is '
                       f'{gain:.4g}× the recorded displacement. The gold band scans the span. '
                       f'The color scale spans {1000*lo:.5g} to {1000*hi:.5g} mm of signed deflection.')
    positions.append((x[0], 0., z[0]))
    positions, rotations = np.asarray(positions), np.asarray(rotations)
    center = ((x[0]+x[-1])/2, 0., (z.min()+z.max())/2)
    if scale:
        center = (scale['center_x'], 0., scale['center_z'])
        extent, close_size = scale['overview_size'], scale['detail_size']

    def frame(seconds):
        x_scan = x[0] + np.clip(seconds/_SWEEP_SECONDS, 0., 1.)*span
        node = int(np.argmin(np.abs(x-x_scan)))
        state = positions.copy()
        state[-1] = (x[node], 0., z[node])
        return Frame(state, rotations, _cameras(center, extent, state[-1], close_size))

    return Scene(objects, _SWEEP_SECONDS, ('Whole rod' if rod else 'Whole beam', 'Section inspection'),
                 description, frame, floor_z=floor_z)


def _cad_scene(result, inputs, model_bytes):
    total = (result.get('summary') or {}).get('triangles')
    units = {'mm': 1e-3, 'cm': 1e-2, 'm': 1}.get(inputs.get('units'))
    surface = None
    if model_bytes and units and inputs.get('cad_asset_id'):
        from .camera_mesh import mesh_surface, stl_triangles
        try:
            original = stl_triangles(model_bytes)
            if 1 <= len(original) <= 100000 and (total is None or len(original) == total):
                vertices, faces, simplified = mesh_surface(original * units, max_faces=3500)
                if len(vertices) and len(faces):
                    source = (f'A display mesh with {len(faces)} faces represents the {len(original)}-triangle STL.'
                              if simplified else f'All {len(original)} triangles from the recorded STL are shown.')
                    surface = vertices, faces, source
        except (ValueError, TypeError, OverflowError):
            pass
    if surface is None:
        triangles = _numbers(result.get('preview_triangles_m'), (None, 3, 3))
        if triangles is None or not 1 <= len(triangles) <= 300:
            return None
        vertices = triangles.reshape(-1, 3)
        faces = np.arange(len(vertices)).reshape(-1, 3)
        count = f'{len(triangles)} of {total}' if isinstance(total, int) and total >= len(triangles) else str(len(triangles))
        source = f'The saved preview contains {count} STL triangles.'
    else:
        vertices, faces, source = surface
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    center = (low+high)/2
    radius = float(np.max(np.linalg.norm(vertices-center, axis=1)))
    if not radius:
        return None
    part = Object3D('mesh', (), (0.39, 0.56, 0.62), vertices-center, faces)
    duration = 6.0

    def frame(seconds):
        angle = 2*math.pi*(np.clip(seconds/duration, 0., 1.) + 0.12)
        offset = np.array([math.cos(angle), math.sin(angle), 0.54])
        overhead = np.array([-0.12, -0.32, 1.])
        return Frame(np.array([center]), None, (Camera(center + radius*3.1*offset, center),
                                                Camera(center + radius*3.3*overhead, center)))

    return Scene([part], duration, ('Orbit camera', 'Fixed upper view'),
                 f'Static CAD inspection. {source} The camera orbits the part.', frame, floor_z=float(low[2]-radius*0.01))


def _joint_scene(result):
    log = (result.get('traces') or {}).get('validation') or {}
    times = _numbers(log.get('time_s'), (None,))
    if times is None or not 2 <= len(times) <= 5000 or np.any(np.diff(times) <= 0):
        return None
    measured = _numbers(log.get('position_rad'), (len(times),))
    predicted = _numbers(log.get('predicted_rad'), (len(times),))
    if measured is None:
        return None
    objects = [Object3D('cylinder', (0.11,0.009), _DARK),
               Object3D('box', (0.046,0.004,0.003), (0.16,0.76,0.69))]
    positions = [[0.,0.,0.], [0.,0.,0.020]]
    if predicted is not None:
        objects.append(Object3D('box', (0.035,0.003,0.002), (0.98,0.52,0.19)))
        positions.append([0.,0.,0.032])
    # Static index marks define the zero-angle direction and quadrants on the illustrative dial.
    for angle in (0., math.pi/2, math.pi, 3*math.pi/2):
        objects.append(Object3D('sphere', (0.0038 if angle == 0 else 0.0025,), (0.88,0.88,0.83)))
        positions.append([0.097*math.cos(angle),0.097*math.sin(angle),0.011])
    duration = float(times[-1]-times[0])
    cameras = (Camera((0.19,-0.26,0.25), (0.,0.,0.)),
               Camera((0.,0.,0.34), (0.,0.,0.), up=(0.,1.,0.)))
    def frame(seconds):
        index = int(np.clip(np.searchsorted(times-times[0], seconds, side='right')-1, 0, len(times)-1))
        pos = np.array(positions)
        rot = np.repeat(np.eye(3)[None,:,:], len(objects), axis=0)
        hands = [(1, measured[index], 0.046)]
        if predicted is not None:
            hands.append((2, predicted[index], 0.035))
        for obj, angle, length in hands:
            c, s = math.cos(angle), math.sin(angle)
            pos[obj,:2] = (length*c, length*s)
            rot[obj] = [[c,-s,0.],[s,c,0.],[0.,0.,1.]]
        return Frame(pos, rot, cameras)

    description = ('Illustrative angle gauge for the held-out joint log. The teal pointer shows '
                   'the measured angle in radians at each recorded time.')
    if predicted is not None:
        description += ' The orange pointer shows the fitted prediction.'
    return Scene(objects, duration, ('Gauge overview', 'Dial face'), description, frame, floor_z=-0.010)


def _calibration_scene(result, inputs):
    model = inputs.get('model') or {}
    length = model.get('length_m')
    bank = result.get('validation')
    if not _positive(length) or not isinstance(bank, list) or not 1 <= len(bank) <= 500:
        return None
    if any(not isinstance(row, dict) for row in bank):
        return None
    measured = _numbers([row.get('measured') for row in bank], (len(bank),))
    predicted = _numbers([row.get('predicted') for row in bank], (len(bank),))
    if measured is None or predicted is None:
        return None
    # Leave enough viewing time per independent experiment. Always include the worst disagreement.
    selected = np.unique(np.r_[np.linspace(0, len(bank)-1, min(len(bank), 9), dtype=int),
                               np.argmax(abs(measured-predicted))])
    if model.get('kind') == 'structural_beam':
        width, height = model.get('width_m'), model.get('height_m')
        if not _positive(width) or not _positive(height):
            return None
        extent = max(0.60*length, width, height)
        peak = float(max(abs(measured).max(), abs(predicted).max()))
        gain = max(1., min(10000., 0.12*length/peak)) if peak else 1.
        floor_z = float(min(-height, gain*min(measured.min(), predicted.min())-0.05*length))
        mark = min(extent*0.025, max(width*0.14, height*0.20))
        parts = [Object3D('box', (length/2, width/2, height/2), _DARK),
                 Object3D('sphere', (mark,), _MEASURED),
                 Object3D('box', (mark, mark, mark), _PREDICTED)]
        rotations = None
        close = max(width*1.8, height*2.4, mark*7, peak*gain*1.5, length*0.1)

        def markers(i):
            return [[length, -width/2-mark, gain*measured[i]], [length, width/2+mark, gain*predicted[i]]], None

        description = (f'Tip displacement on the undeflected beam fixture. The teal sphere shows the measured '
                       f'tip displacement and the orange cube shows the prediction. Vertical offset is displayed at {gain:.4g}×.')
    elif model.get('kind') == 'thermal_rod':
        if not _positive(model.get('area_m2')):
            return None
        source = inputs.get('validation') or []
        source_positions = {row.get('run_id'): row.get('position_m') for row in source if isinstance(row, dict)}
        x = _numbers([source_positions.get(row.get('run_id')) for row in bank], (len(bank),))
        if x is None or np.any(x < 0) or np.any(x > length):
            return None
        lo, hi = float(min(measured.min(), predicted.min())), float(max(measured.max(), predicted.max()))
        radius = math.sqrt(model['area_m2']/math.pi)
        extent = max(0.60*length, 2*radius)
        floor_z = -radius*1.08
        close = max(radius*4.5, length*0.15)
        mark = min(length*0.035, radius*0.38)
        parts = [Object3D('cylinder', (radius, length/2), _DARK),
                 Object3D('sphere', (mark,), _MEASURED),
                 Object3D('box', (mark, mark, mark), _PREDICTED)]
        rotations = np.array([_ALONG_X, np.eye(3), np.eye(3)])

        def markers(i):
            return ([[x[i], -radius*0.65, radius+mark], [x[i], radius*0.65, radius+mark]],
                    np.array([_DARK, _field_color(measured[i], lo, hi), _field_color(predicted[i], lo, hi)]))

        description = ('The circular rod represents the supplied cross-sectional area. At the saved sensor '
                       'station the sphere shows measured temperature and the cube shows predicted temperature. ')
        description += f'The colors span {lo:.6g} K (blue) to {hi:.6g} K (orange).' if hi > lo else f'Both read {lo:.6g} K.'
    else:
        return None
    duration = max(2., 1.2*len(selected))
    center = [length/2, 0., 0.]

    def frame(seconds):
        ordinal = min(len(selected)-1, int(np.clip(seconds/duration, 0., 1.) * len(selected)))
        points, colors = markers(selected[ordinal])
        focus = np.mean(points, axis=0)
        return Frame(np.array([center, *points]), rotations, _cameras(center, extent, focus, close), colors)

    description += (f' This inspection steps through {len(selected)} of {len(bank)} independent held-out readings '
                    'in saved order, including the largest discrepancy.')
    return Scene(parts, duration, ('Fixture overview', 'Measurement comparison'), description, frame, floor_z=floor_z)


def field_scene(run, model_bytes=None):
    """Read the saved run, optionally using a checksum-verified original CAD asset."""
    result = run.get('result') or {}
    adapter = run.get('adapter')
    if adapter in ('thermal_rod', 'structural_beam'):
        valid = not (run.get('assessment_error') or run.get('error') or
                     (result.get('numerical_diagnostics') or {}).get('passed') is False)
        return _station_scene(result, result.get('inputs') or run.get('inputs') or {}, adapter == 'thermal_rod',
                              run.get('camera_comparison_scale'), mark_events=valid)
    if adapter == 'cad_inventory':
        return _cad_scene(result, run.get('inputs') or {}, model_bytes)
    if adapter == 'joint_response':
        return _joint_scene(result)
    if adapter == 'calibration':
        return _calibration_scene(result, result.get('inputs') or run.get('inputs') or {})
    return None
