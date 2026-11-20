"""Geometry of weld macrograph measurements in ORIGINAL pixels.

For a fillet weld the ISO 2553 nominal throat a is the height of the
largest *isosceles* triangle which can be inscribed within the weld section.
The face is entered as a piecewise-linear contour; unseen concavities cannot
be inferred and the analyst must validate its traced shape.
"""
from __future__ import annotations
from .i18n import tr
import math
from .calibration import affine_mm_delta

MEASUREMENT_TYPES = {
    'a_contour': ('Gardziel spoiny a — kontur lica (≥3 punkty)', None,
        'Wskaż: (1) teoretyczny narożnik/granię, (2) pierwszy brzeg spoiny, '
        '(3...) punkty lica w kolejności, aż do drugiego brzegu. '
        'ZAKOŃCZ PRAWYM PRZYCISKIEM MYSZY (min. 3 punkty). '
        'Wynik: największy trójkąt równoramienny wpisany w zaznaczony przekrój.'),
    't1': ('Grubość blachy t₁ (2 punkty)', 2,
           'Wskaż dwa przeciwległe brzegi pierwszej blachy prostopadle do jej powierzchni.'),
    't2': ('Grubość blachy t₂ (2 punkty)', 2,
           'Wskaż dwa przeciwległe brzegi drugiej blachy prostopadle do jej powierzchni.'),
    'distance': ('Odcinek dowolny (2 punkty)', 2,
                 'Wskaż początek i koniec mierzonego odcinka.'),
    # Historical 3-point measurement from WeldVision 3.2.x measured the distance
    # to an arbitrary line. Kept for loading, never presented as valid a.
    'a': ('a — pomiar historyczny (nieważny; wykonaj ponownie)', 3,
          'Historyczny algorytm był niezgodny z definicją gardzieli a. Wykonaj nowy pomiar konturu.'),
}


def _validated_points(points):
    pts = []
    if not isinstance(points, (list, tuple)) or len(points) > 500:
        raise ValueError(tr('Niedozwolona liczba punktów pomiarowych.'))
    for point in points:
        if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
            raise ValueError(tr('Nieprawidłowe współrzędne punktu pomiarowego.'))
        pts.append(tuple(float(v) for v in point))
    return pts


def _to_mm(v, matrix):
    return affine_mm_delta(v[0], v[1], matrix) if matrix is not None else tuple(v)


def throat_contour_geometry(points, matrix=None):
    """Root + toe1 + face vertices + toe2 -> (root, throat end, length).

    In basis of unit fusion-face directions e1/e2, equal-leg triangle with leg
    length s has face u+v=s. To stay inside the measured section its largest
    allowable s is min_i(u_i+v_i) over sampled weld-face points. The height is
    s*cos(theta/2), including non-square fillet angles; at 90° a=s/sqrt(2).
    """
    pts = _validated_points(points)
    if len(pts) < 3:
        raise ValueError(tr('Zaznacz co najmniej granię i dwa brzegi spoiny.'))
    root, toe1, toe2 = pts[0], pts[1], pts[-1]
    a = _to_mm((toe1[0]-root[0], toe1[1]-root[1]), matrix)
    b = _to_mm((toe2[0]-root[0], toe2[1]-root[1]), matrix)
    len1, len2 = math.hypot(*a), math.hypot(*b)
    if min(len1, len2) <= 1e-6:
        raise ValueError(tr('Brzeg spoiny nie może pokrywać się z granią.'))
    e1, e2 = (a[0]/len1, a[1]/len1), (b[0]/len2, b[1]/len2)
    dot = max(-1., min(1., e1[0]*e2[0] + e1[1]*e2[1]))
    angle = math.degrees(math.acos(dot))
    if not 20 < angle < 160:
        raise ValueError(tr('Narożnik i brzegi spoiny muszą wyznaczać dwa różne kierunki blach (20°–160°).'))
    det = e1[0]*e2[1] - e1[1]*e2[0]
    legs = []
    for pt in pts[1:]:
        px, py = _to_mm((pt[0]-root[0], pt[1]-root[1]), matrix)
        u = (px*e2[1] - py*e2[0])/det
        v = (e1[0]*py - e1[1]*px)/det
        # A point outside the acute or obtuse wedge is not on the weld face.
        if u < -0.03*max(len1,len2) or v < -0.03*max(len1,len2):
            raise ValueError(tr('Punkt lica wypada poza kątem pomiędzy kierunkami blach.'))
        legs.append(u+v)
    s = min(legs)
    if s <= 1e-6:
        raise ValueError(tr('Profil lica nie wyznacza dodatniej grubości.'))
    mid_mm = (s*(e1[0]+e2[0])*.5, s*(e1[1]+e2[1])*.5)
    length = math.hypot(*mid_mm)
    if matrix is not None:
        # Translate the physical height vector back into image pixel coordinates.
        m00,m01=matrix[0]; m10,m11=matrix[1]
        determinant=m00*m11-m01*m10
        if abs(determinant)<1e-14:
            raise ValueError(tr('Nieprawidłowa macierz kalibracji.'))
        offset=((mid_mm[0]*m11-mid_mm[1]*m01)/determinant,
                (m00*mid_mm[1]-m10*mid_mm[0])/determinant)
    else:
        offset=mid_mm
    return root, (root[0]+offset[0], root[1]+offset[1]), length


def measurement_geometry(kind, points, matrix=None):
    """Display segment and geometry length (in mm if matrix was supplied)."""
    if kind not in MEASUREMENT_TYPES:
        raise ValueError(tr('Nieznany rodzaj pomiaru.'))
    pts = _validated_points(points)
    required=MEASUREMENT_TYPES[kind][1]
    if required is not None and len(pts) != required:
        raise ValueError(tr('Nieprawidłowa liczba punktów pomiarowych.'))
    if kind == 'a_contour':
        return throat_contour_geometry(pts, matrix)
    if kind == 'a':
        # Historical geometry retained ONLY so that old projects remain readable.
        # This value is NEVER returned as a valid throat thickness.
        root, toe1, toe2 = pts
        dx,dy=toe2[0]-toe1[0],toe2[1]-toe1[1]
        sx,sy=root[0]-toe1[0],root[1]-toe1[1]
        dd=_to_mm((dx,dy),matrix)
        ss=_to_mm((sx,sy),matrix)
        den=dd[0]**2+dd[1]**2
        if den<=1e-12:
            raise ValueError(tr('Historyczny pomiar ma zdegenerowane lico.'))
        ratio=(ss[0]*dd[0]+ss[1]*dd[1])/den
        foot=(toe1[0]+ratio*dx,toe1[1]+ratio*dy)
        delta=_to_mm((foot[0]-root[0],foot[1]-root[1]),matrix)
        return root,foot,math.hypot(*delta)
    start,end=pts
    length=math.hypot(*_to_mm((end[0]-start[0],end[1]-start[1]),matrix))
    if length<=1e-6:
        raise ValueError(tr('Wymiar musi mieć dodatnią długość.'))
    return start,end,length


def measurement_mm(item, mm_per_px, matrix=None):
    if item['kind'] == 'a':
        return None  # MUST redo obsolete 3.2.x throat measurement.
    if matrix is not None:
        return measurement_geometry(item['kind'], item['points'], matrix)[2]
    if mm_per_px is None or not math.isfinite(mm_per_px) or mm_per_px <= 0:
        return None
    return measurement_geometry(item['kind'],item['points'])[2]*mm_per_px


def validate_measurements(items, shape, matrix=None):
    if not isinstance(items, list) or len(items)>10000:
        raise ValueError(tr('Nieprawidłowa lista pomiarów liniowych.'))
    result=[]
    h,w=shape
    for item in items:
        kind,points=item['kind'],item['points']
        if kind == 'a_contour':
            pts = _validated_points(points)
            if len(pts) < 3:
                raise ValueError(tr('Brak punktów konturu gardzieli.'))
            # Geometry can become invalid after recalibration. Keep the
            # annotations editable and suppress the result until corrected.
        else:
            measurement_geometry(kind, points)
        if any(not(0<=p[0]<w and 0<=p[1]<h) for p in points):
            raise ValueError(tr('Punkt pomiarowy poza zdjęciem.'))
        result.append({'kind':kind,'points':[[float(v) for v in p] for p in points]})
    return result
