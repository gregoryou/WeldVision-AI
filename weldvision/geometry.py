"""Editable macrograph objects. Coordinates are always source-image pixels."""
from __future__ import annotations
from .i18n import tr

import math
import re
import uuid
from dataclasses import dataclass

from .calibration import affine_mm_delta, affine_pixel_delta
from .measurements import measurement_geometry, throat_contour_geometry
from .annotation_style import default_style, normalize_style, numeric_label

TYPES = {
    'circle': 'Okrąg', 'line': 'Linia prosta', 'horizontal': 'Linia pozioma',
    'vertical': 'Linia pionowa', 'infinite': 'Linia konstrukcyjna',
    'parallel': 'Linia równoległa', 'perpendicular': 'Linia prostopadła',
    'polyline': 'Linia łamana', 'angle': 'Kąt', 'intersection': 'Punkt przecięcia',
    'throat': 'Gardziel a / r', 'scale': 'Podziałka', 'point': 'Punkt pomiarowy',
    'comment': 'Komentarz', 't1': 'Grubość blachy t₁', 't2': 'Grubość blachy t₂',
    'distance': 'Wymiar liniowy', 'a_contour': 'Gardziel a — kontur',
}
LINES = frozenset(('line', 'horizontal', 'vertical', 'infinite', 'parallel', 'perpendicular'))
DERIVED = frozenset(('parallel', 'perpendicular'))
THICKNESS = frozenset(('t1', 't2', 'distance', 'a_contour'))
METHODS = {'manual': 'Promień ręczny', 'straight': 'Styczność z prostą',
           'contour': 'Styczność z konturem'}
EPS = 1e-9


def add(a, b):
    return a[0]+b[0], a[1]+b[1]


def sub(a, b):
    return a[0]-b[0], a[1]-b[1]


def mul(a, k):
    return a[0]*k, a[1]*k


def dot(a, b):
    return a[0]*b[0]+a[1]*b[1]


def cross(a, b):
    return a[0]*b[1]-a[1]*b[0]


def norm(a):
    return math.hypot(*a)


def unit(a):
    length = norm(a)
    if length <= EPS:
        raise ValueError(tr('Wskaż dwa różne punkty.'))
    return mul(a, 1/length)


def to_mm(a, matrix):
    return affine_mm_delta(*a, matrix) if matrix is not None else tuple(a)


def to_px(a, matrix):
    return affine_pixel_delta(*a, matrix) if matrix is not None else tuple(a)


def intersection(line_a, line_b):
    a, aa = line_a
    b, bb = line_b
    u, v = sub(aa, a), sub(bb, b)
    den = cross(u, v)
    if abs(den) <= EPS*norm(u)*norm(v):
        raise ValueError(tr('Proste są równoległe lub zdegenerowane.'))
    return add(a, mul(u, cross(sub(b, a), v)/den))


def projection(p, a, b, segment=False):
    v = sub(b, a)
    if norm(v) <= EPS:
        raise ValueError(tr('Odcinek ma zerową długość.'))
    t = dot(sub(p, a), v)/dot(v, v)
    if segment:
        t = min(1., max(0., t))
    return add(a, mul(v, t))


def ellipse(center, vector, matrix, steps=120):
    """Sample an actual circle in the calibrated plane, then invert to pixels."""
    u = to_mm(vector, matrix)
    v = -u[1], u[0]
    return [add(center, to_px(add(mul(u, math.cos(t)), mul(v, math.sin(t))), matrix))
            for t in (i*math.tau/steps for i in range(steps+1))]


def make_object(kind, points=(), refs=(), **options):
    item = {'id': uuid.uuid4().hex, 'kind': kind, 'name': TYPES[kind],
            'points': [list(p) for p in points], 'refs': list(refs),
            'style': default_style(kind), 'visible': True, 'diameter': False, 'show_radius': True}
    item.update(options)
    return item


def validate_objects(items, shape):
    """Validate JSON structure and the order of its acyclic dependencies."""
    if not isinstance(items, list) or len(items) > 2000:
        raise ValueError(tr('Nieprawidłowa lista obiektów pomiarowych.'))
    h, w = shape
    result, known = [], {}
    counts = {'circle': (2, 0), 'line': (2, 0), 'horizontal': (2, 0), 'vertical': (2, 0),
              'infinite': (2, 0), 'parallel': (2, 1), 'perpendicular': (2, 1),
              'angle': (0, 2), 'intersection': (0, 2), 'throat': (None, 3),
              'scale': (1, 0), 'polyline': (None, 0), 'point': (1, 0), 'comment': (1, 0),
              't1': (2, 0), 't2': (2, 0), 'distance': (2, 0), 'a_contour': (None, 0)}
    for item in items:
        kind, uid = item['kind'], item['id']
        if kind not in counts or not re.fullmatch(r'[a-f0-9]{32}', uid) or uid in known:
            raise ValueError(tr('Nieprawidłowy typ lub identyfikator obiektu.'))
        expected, n_refs = counts[kind]
        points, refs = item['points'], item['refs']
        if not isinstance(points, list) or not isinstance(refs, list):
            raise ValueError(tr('Nieprawidłowe punkty lub odwołania obiektu.'))
        if len(refs) != n_refs or len(set(refs)) != n_refs or any(ref not in known for ref in refs):
            raise ValueError(tr('Brakujący lub cykliczny obiekt odniesienia.'))
        if any(known[ref] not in LINES for ref in (refs[:2] if kind == 'throat' else refs)):
            raise ValueError(tr('Odniesienie musi być prostą.'))
        if kind == 'polyline' and not 2 <= len(points) <= 500:
            raise ValueError(tr('Linia łamana wymaga od 2 do 500 punktów.'))
        if kind == 'a_contour' and not 3 <= len(points) <= 500:
            raise ValueError(tr('Kontur gardzieli wymaga od 3 do 500 punktów.'))
        fields = {}
        if kind == 'throat':
            method = item.get('method')
            if method not in METHODS or known[refs[2]] not in LINES | {'polyline'}:
                raise ValueError(tr('Nieprawidłowa metoda lub odniesienie gardzieli.'))
            if (method == 'straight' and known[refs[2]] not in LINES or
                    method == 'contour' and known[refs[2]] != 'polyline'):
                raise ValueError(tr('Geometria lica nie odpowiada metodzie gardzieli.'))
            expected = 2 if method == 'manual' else 1
            fields['method'] = method
        if expected is not None and len(points) != expected:
            raise ValueError(tr('Nieprawidłowa liczba punktów geometrii.'))
        # Throat points are a root correction vector and a manual radius vector.
        def valid_point(p):
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                return False
            x, y = p
            return (all(isinstance(v, (int, float)) and math.isfinite(v) for v in p)
                    and (-w < x < w and -h < y < h if kind == 'throat' else
                         0 <= x < w and 0 <= y < h))
        if not all(map(valid_point, points)):
            raise ValueError(tr('Punkt obiektu poza obszarem zdjęcia lub nieprawidłowy.'))
        raw_style = item.get('style', {})
        if 'style' not in item and 'color' in item:
            raw_style = dict(line_color=item['color'], text_color=item['color'],
                             line_width=item['width'], font_pt=item['font']*.75)
        style = normalize_style(raw_style, kind)
        if kind == 'scale':
            size = float(item['length_mm'])
            angle = float(item.get('angle_deg', 0.))
            if not .001 <= size <= 100000 or not math.isfinite(angle):
                raise ValueError(tr('Nieprawidłowa długość lub orientacja podziałki.'))
            fields.update(length_mm=size, angle_deg=angle % 360)
        result.append(make_object(kind, points, refs, id=uid, name=str(item['name'])[:160],
                                  style=style, visible=bool(item['visible']),
                                  diameter=bool(item['diameter']),
                                  show_radius=bool(item.get('show_radius', True)), **fields))
        known[uid] = kind
    return result


@dataclass
class Result:
    value: float | None = None
    unit: str = ''
    label: str = ''
    status: str = ''
    paths: tuple = ()
    handles: tuple = ()
    anchor: tuple = ()
    line: tuple = ()
    radius: float | None = None
    triangle: tuple = ()
    center: tuple = ()


def number(value):
    return f'{value:.2f}'.replace('.', ',')


def caption(value, unit, symbol='', diameter=None):
    if value is None:
        return ''
    label = f'{symbol} = ' if symbol else ''
    label += f'{number(value)}{unit}' if unit == '°' else f'{number(value)} {unit}'
    if diameter is not None:
        label += f'   d = {number(diameter)} mm'
    return label


def legacy_caption(item, value):
    name = {'a_contour': 'a', 't1': 't₁', 't2': 't₂', 'distance': 'L'}.get(item['kind'], 'a')
    return caption(value, 'mm', name)


def _line(item, deps, matrix):
    a, b = map(tuple, item['points'])
    kind = item['kind']
    if kind == 'horizontal':
        b = b[0], a[1]
    elif kind == 'vertical':
        b = a[0], b[1]
    elif kind in DERIVED:
        p, q = deps[0].line
        u = unit(to_mm(sub(q, p), matrix))
        if kind == 'perpendicular':
            u = -u[1], u[0]
        along = dot(to_mm(sub(b, a), matrix), u)
        b = add(a, to_px(mul(u, along), matrix))
    unit(sub(b, a))
    return a, b


def _path_for_line(line, shape, infinite):
    """Clip an extended line to the image rectangle."""
    if not infinite:
        return line
    h, w = shape
    a, b = line
    u = sub(b, a)
    limits = [-math.inf, math.inf]
    for origin, delta, bound in zip(a, u, (w-1, h-1)):
        if abs(delta) < EPS:
            if not 0 <= origin <= bound:
                return ()
            continue
        low, high = sorted((-origin/delta, (bound-origin)/delta))
        limits = [max(limits[0], low), min(limits[1], high)]
    return tuple(add(a, mul(u, t)) for t in limits) if limits[0] <= limits[1] else ()


def _circle_result(o, p, matrix, diameter):
    r = norm(to_mm(sub(p, o), matrix))
    if r <= EPS:
        raise ValueError(tr('Wskaż dodatni promień.'))
    return Result(r if matrix is not None else None, 'mm',
                  caption(r, 'mm', 'r', 2*r if diameter else None) if matrix is not None else '',
                  '' if matrix is not None else tr('Brak kalibracji'),
                  (ellipse(o, sub(p, o), matrix), (o, p)), (o, p), p,
                  radius=r if matrix is not None else None, center=o)


def _throat(item, deps, matrix):
    plate1, plate2 = deps[0].line, deps[1].line
    root = intersection(plate1, plate2)
    o = add(root, item['points'][0])
    method = item['method']
    face = deps[2].line or deps[2].paths[0]
    # Calculate true point-to-segment/line distances under the affine calibration.
    face_mm = [to_mm(sub(p, o), matrix) for p in face]
    if method == 'manual':
        p = add(o, item['points'][1])
    else:
        contact = min((projection((0., 0.), a, b, not deps[2].line)
                       for a, b in zip(face_mm, face_mm[1:])), key=norm)
        p = add(o, to_px(contact, matrix))
    result = _circle_result(o, p, matrix, item['diameter'])
    result.value = None
    if matrix is None:
        return result
    try:
        profile = (intersection(plate1, face), intersection(plate2, face)) if deps[2].line else face
        leg1, leg2 = [to_mm(sub(t, o), matrix) for t in (profile[0], profile[-1])]
        tol = max(1e-6, min(.05, .005*min(norm(leg1), norm(leg2))))
        if norm(to_mm(sub(o, root), matrix)) > tol:
            raise ValueError(tr('O poza przecięciem linii blach'))
        _, mid, height = throat_contour_geometry([o, *profile], matrix)
        e1, e2 = unit(leg1), unit(leg2)
        # Direct or reverse contour order is accepted. Each toe must lie on
        # a different selected fusion face, and the profile must trace the wedge.
        dirs = [unit(to_mm(sub(b, a), matrix)) for a, b in (plate1, plate2)]
        toe_errors = [[abs(cross(leg, d)) for d in dirs] for leg in (leg1, leg2)]
        if min(max(toe_errors[0][0], toe_errors[1][1]),
               max(toe_errors[0][1], toe_errors[1][0])) > tol:
            raise ValueError(tr('Brzegi lica muszą leżeć na obu liniach blach'))
        if not deps[2].line:
            phase = []
            for t in profile:
                pt = to_mm(sub(t, o), matrix)
                u, v = cross(pt, e2)/cross(e1, e2), cross(e1, pt)/cross(e1, e2)
                if min(u, v) < -tol or u+v <= tol:
                    raise ValueError(tr('Kontur wychodzi poza przekrój'))
                phase.append(v/(u+v))
            if any(b < a-1e-6 for a, b in zip(phase, phase[1:])):
                raise ValueError(tr('Prowadź kontur kolejno od jednego brzegu do drugiego'))
        else:
            start, end = face_mm
            face_kind = item.get('_face_kind')
            if face_kind not in DERIVED | {'infinite'}:
                for t in profile:
                    v = to_mm(sub(t, o), matrix)
                    if norm(sub(v, projection(v, start, end, True))) > tol:
                        raise ValueError(tr('Odcinek lica musi sięgać obu powierzchni blach'))
        leg_size = height/norm(mul(add(e1, e2), .5))
        toe_a = add(o, to_px(mul(e1, leg_size), matrix))
        toe_b = add(o, to_px(mul(e2, leg_size), matrix))
        result.triangle = (o, toe_a, toe_b, o)
        if abs(result.radius-height) > tol:
            raise ValueError(tr('Promień różni się od wysokości trójkąta równoramiennego'))
        if method == 'manual':
            endpoint = to_mm(sub(p, o), matrix)
            extended = item.get('_face_kind') in DERIVED | {'infinite'}
            if min(norm(sub(endpoint, projection(endpoint, a, b, not extended)))
                   for a, b in zip(face_mm, face_mm[1:])) > tol:
                raise ValueError(tr('Koniec promienia nie leży na wskazanym licu'))
        elif norm(to_mm(sub(p, mid), matrix)) > tol:
            raise ValueError(tr('Styczność nie wyznacza wysokości trójkąta równoramiennego'))
        # Tolerance only qualifies the geometry. The selected method reports a = r.
        result.value = result.radius
        result.label = (caption(height, 'mm', 'a') + '   ' +
                        caption(result.radius, 'mm', 'r',
                                2*result.radius if item['diameter'] else None))
        result.paths += ((o, mid),)
        result.anchor = mid
    except ValueError as exc:
        result.status = str(exc)
        result.label += tr('   (a nieważne)')
    return result


def evaluate(item, parts, matrix, shape):
    """Single source of dimensions and annotation labels for screen and export."""
    kind, points = item['kind'], tuple(map(tuple, item['points']))
    deps = [parts.get(i, Result()) for i in item['refs']]
    try:
        if kind in LINES:
            if kind in DERIVED and not deps[0].line:
                raise ValueError(tr('Linia odniesienia nie ma geometrii.'))
            a, b = _line(item, deps, matrix)
            value = norm(to_mm(sub(b, a), matrix)) if matrix is not None else None
            extended = kind in DERIVED | {'infinite'}
            path = _path_for_line((a, b), shape, extended)
            return Result(value, 'mm', caption(value, 'mm'), '' if matrix is not None else tr('Brak kalibracji'),
                          (path,), (a, b), mul(add(a, b), .5), (a, b))
        if kind == 'circle':
            return _circle_result(*points, matrix, item['diameter'])
        if kind == 'scale':
            if matrix is None:
                return Result(status=tr('Brak kalibracji'), handles=points)
            a, = points
            length = item['length_mm']
            angle = math.radians(item.get('angle_deg', 0.))
            direction = math.cos(angle), math.sin(angle)
            b = add(a, mul(direction, length/norm(to_mm(direction, matrix))))
            return Result(length, 'mm', f'{length:g} mm'.replace('.', ','),
                          paths=((a, b),), handles=(a,), anchor=mul(add(a, b), .5))
        if kind in ('point', 'comment'):
            p, = points
            return Result(label='P' if kind == 'point' else item['name'],
                          paths=((p,),) if kind == 'point' else (), handles=points,
                          anchor=p, center=p if kind == 'point' else ())
        if kind in THICKNESS:
            start, end, length = measurement_geometry(kind, points, matrix)
            return Result(length if matrix is not None else None, 'mm',
                          status='' if matrix is not None else tr('Brak kalibracji'),
                          paths=((start, end),), handles=points, anchor=end)
        if kind == 'polyline':
            segments = [norm(to_mm(sub(b, a), matrix)) for a, b in zip(points, points[1:])]
            if any(length <= EPS for length in segments):
                raise ValueError(tr('Kolejne punkty łamanej muszą być różne.'))
            value = sum(segments) if matrix is not None else None
            return Result(value, 'mm', caption(value, 'mm'), '' if matrix is not None else tr('Brak kalibracji'),
                          (points,), points, points[len(points)//2])
        if kind in ('angle', 'intersection', 'throat') and not all(d.line for d in deps[:2]):
            raise ValueError(tr('Brak poprawnej geometrii obu prostych.'))
        if kind == 'intersection':
            o = intersection(deps[0].line, deps[1].line)
            return Result(label='O', paths=((o,),), anchor=o)
        if kind == 'angle':
            u, v = [unit(to_mm(sub(b, a), matrix)) for a, b in (d.line for d in deps)]
            # Smaller, orientation-independent angle between the supporting lines.
            if dot(u, v) < 0:
                v = mul(v, -1)
            alpha = math.atan2(cross(u, v), dot(u, v))
            a, b = deps[0].line
            o = a if abs(alpha) <= EPS else intersection(deps[0].line, deps[1].line)
            if matrix is None:
                return Result(status=tr('Brak kalibracji'), paths=((o,),), anchor=o)
            arm_px = min(42., max(5., .12*min(shape)))
            r = arm_px/max(norm(to_px(u, matrix)), norm(to_px(v, matrix)))
            start = math.atan2(u[1], u[0])
            arc = tuple(add(o, to_px((r*math.cos(t), r*math.sin(t)), matrix))
                        for t in (start+alpha*i/24 for i in range(25)))
            value = abs(math.degrees(alpha))
            return Result(value, '°', caption(value, '°'), paths=((o, arc[0]), arc, (o, arc[-1])),
                          anchor=arc[12])
        if not deps[2].line and not deps[2].paths:
            raise ValueError(tr('Brak poprawnej geometrii lica.'))
        return _throat(dict(item, _face_kind=parts.kinds[item['refs'][2]]), deps, matrix)
    except (ValueError, IndexError, ZeroDivisionError) as exc:
        return Result(status=str(exc))


def format_result(item, result):
    style = item['style']
    kind = item['kind']
    if kind in ('circle', 'throat'):
        labels = []
        if kind == 'throat' and result.value is not None:
            labels.append(numeric_label(result.value, 'mm', style, 'a'))
        if item['show_radius'] and result.radius is not None:
            labels.append(numeric_label(result.radius, 'mm', style, 'r'))
        if item['diameter'] and result.radius is not None:
            labels.append(numeric_label(2*result.radius, 'mm', style, 'd'))
        result.label = '   '.join(labels)
        if kind == 'throat' and result.status and result.radius is not None:
            result.label += tr('   (a nieważne)')
    elif result.value is not None:
        symbol = {'a_contour': 'a', 't1': 't₁', 't2': 't₂', 'distance': 'L'}.get(kind, '')
        result.label = numeric_label(result.value, result.unit, style, symbol,
                                     -1 if kind == 'scale' else 2)
    if style['signature'] == 'none':
        result.label = ''
    elif style['signature'] == 'custom' and (result.value is not None or result.radius is not None
                                             or kind in ('comment', 'point', 'intersection')):
        result.label = style['custom_label']
        if kind == 'throat' and result.value is None:
            result.label += tr('   (a nieważne)')
    return result


def promote_measurement(item):
    return make_object(item['kind'], item['points']) if item['kind'] in THICKNESS else None


class Scene(dict):
    def __init__(self, items, matrix, shape):
        super().__init__()
        self.kinds = {item['id']: item['kind'] for item in items}
        for item in items:
            evaluated = evaluate(item, self, matrix, shape)
            self[item['id']] = format_result(item, evaluated)
