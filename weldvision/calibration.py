"""Kalibracja metrologiczna w układzie pikseli zdjęcia źródłowego.

Dwa punkty: izotropowy przelicznik (mm/px).
Trzy punkty siatki: wspólny narożnik, sąsiad wzdłuż osi X siatki,
sąsiad wzdłuż osi Y siatki, obie odległości = znana długość [mm].
Macierz transformuje przesunięcia (px) na (mm), w tym obrót i ścinanie.
"""
from __future__ import annotations
from .i18n import tr
import math


def pixel_to_mm_matrix(points, known_mm):
    """Macierz ((a,b),(c,d)): [dx_mm,dy_mm] = M @ [dx_px,dy_px]."""
    if not math.isfinite(known_mm) or known_mm <= 0:
        return None
    if len(points) not in (2, 3):
        return None
    if any(len(p) != 2 or any(not math.isfinite(float(v)) for v in p) for p in points):
        return None
    (x0,y0), (x1,y1) = points[:2]
    ux, uy = x1-x0, y1-y0
    if len(points) == 2:
        length = math.hypot(ux,uy)
        if length <= 1e-9:
            return None
        s = known_mm/length
        return ((s,0.0),(0.0,s))
    x2,y2 = points[2]
    vx,vy = x2-x0, y2-y0
    det = ux*vy-uy*vx
    # Nie akceptuj współliniowych lub prawie współliniowych osi siatki.
    if abs(det) <= 1e-4 * math.hypot(ux,uy) * math.hypot(vx,vy):
        return None
    k = known_mm/det
    return ((k*vy,-k*vx),(-k*uy,k*ux))


def pixel_area_mm2(matrix):
    if matrix is None:
        return None
    (a,b),(c,d) = matrix
    area = abs(a*d-b*c)
    return area if math.isfinite(area) and area > 0 else None


def affine_mm_delta(dx,dy,matrix):
    (a,b),(c,d)=matrix
    return a*dx+b*dy, c*dx+d*dy


def affine_pixel_delta(dx_mm,dy_mm,matrix):
    (a,b),(c,d)=matrix
    det=a*d-b*c
    if abs(det)<1e-20:
        raise ValueError(tr('Osie kalibracji są zdegenerowane.'))
    return (d*dx_mm-b*dy_mm)/det, (-c*dx_mm+a*dy_mm)/det
