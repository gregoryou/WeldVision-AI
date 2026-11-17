"""Pomiary liniowe w układzie pikseli oryginalnego zdjęcia."""
from __future__ import annotations

import math


MEASUREMENT_TYPES = {
    'a': ('Grubość spoiny a — prostopadle (3 punkty)', 3,
          'Wskaż grań spoiny, potem dwa końce odcinka lica. '
          'Program wyznaczy odległość prostopadłą od grani do linii lica.'),
    't1': ('Grubość blachy t₁ (2 punkty)', 2,
           'Wskaż dwa przeciwległe brzegi pierwszej blachy, w kierunku prostopadłym do jej powierzchni.'),
    't2': ('Grubość blachy t₂ (2 punkty)', 2,
           'Wskaż dwa przeciwległe brzegi drugiej blachy, w kierunku prostopadłym do jej powierzchni.'),
    'distance': ('Odcinek dowolny (2 punkty)', 2,
                 'Wskaż początek i koniec mierzonego odcinka.'),
}


def measurement_geometry(kind, points):
    """Zwraca odcinek pomiarowy; dla a rzut musi leżeć na wskazanym licu."""
    if kind not in MEASUREMENT_TYPES or len(points) != MEASUREMENT_TYPES[kind][1]:
        raise ValueError('Nieprawidłowy rodzaj pomiaru lub liczba punktów.')
    pts = []
    for point in points:
        if len(point) != 2 or not all(math.isfinite(float(v)) for v in point):
            raise ValueError('Nieprawidłowe współrzędne punktu pomiarowego.')
        pts.append(tuple(float(v) for v in point))
    start = pts[0]
    if kind == 'a':
        p, q = pts[1:]
        dx, dy = q[0] - p[0], q[1] - p[1]
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            raise ValueError('Końce lica muszą być różnymi punktami.')
        ratio = ((start[0] - p[0]) * dx + (start[1] - p[1]) * dy) / denom
        if ratio < -1e-9 or ratio > 1 + 1e-9:
            raise ValueError('Rzut grani wypada poza odcinkiem lica. Wskaż ponownie grań i oba końce lica.')
        end = (p[0] + ratio * dx, p[1] + ratio * dy)
    else:
        end = pts[1]
    pixels = math.hypot(end[0] - start[0], end[1] - start[1])
    if pixels <= 1e-6:
        raise ValueError('Wymiar musi mieć dodatnią długość. Wskaż różne punkty.')
    return start, end, pixels


def measurement_mm(item, mm_per_px):
    if mm_per_px is None or not math.isfinite(mm_per_px) or mm_per_px <= 0:
        return None
    return measurement_geometry(item['kind'], item['points'])[2] * mm_per_px


def validate_measurements(items, shape):
    """Sprawdza geometrię i granice obrazu podczas odczytu projektu."""
    if not isinstance(items, list) or len(items) > 10000:
        raise ValueError('Nieprawidłowa lista pomiarów liniowych.')
    result = []
    h, w = shape
    for item in items:
        kind, points = item['kind'], item['points']
        measurement_geometry(kind, points)
        if any(not (0 <= p[0] < w and 0 <= p[1] < h) for p in points):
            raise ValueError('Punkt pomiarowy znajduje się poza zdjęciem.')
        result.append({'kind': kind, 'points': [[float(v) for v in p] for p in points]})
    return result
