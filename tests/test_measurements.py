import csv
import io
import json
import math
import zipfile

import cv2
import numpy as np
import pytest

from weldvision.core import Project, Sample, export_results, load_project, save_project, image_write
from weldvision.measurements import measurement_geometry, measurement_mm, validate_measurements


def test_throat_is_perpendicular_and_rotation_invariant():
    points = [[0, 0], [0, 100], [100, 0]]
    start, foot, pixels = measurement_geometry('a', points)
    assert start == (0, 0)
    assert foot == pytest.approx((50, 50))
    assert pixels == pytest.approx(math.sqrt(5000))
    angle = .723
    rotated = [[x*math.cos(angle)-y*math.sin(angle)+200,
                x*math.sin(angle)+y*math.cos(angle)+150] for x, y in points]
    assert measurement_geometry('a', rotated)[2] == pytest.approx(pixels)
    assert measurement_mm({'kind': 'a', 'points': points}, .02) == pytest.approx(math.sqrt(2))
    assert measurement_mm({'kind': 'a', 'points': points}, None) is None


@pytest.mark.parametrize('kind, points', [
    ('t1', [[2, 4], [2, 4]]),
    ('a', [[0, 0], [20, 20], [20, 20]]),
    ('a', [[30, 10], [0, 0], [20, 0]]),
    ('t2', [[float('nan'), 0], [10, 0]]),
])
def test_reject_degenerate_geometry(kind, points):
    with pytest.raises(ValueError):
        measurement_geometry(kind, points)


def test_linear_measurements_saved_and_exported_without_mask(tmp_path):
    image = np.full((240, 320, 3), 90, np.uint8)
    path = tmp_path / 'test.png'
    image_write(path, image)
    sample = Sample.from_file(path)
    sample.cal_points = [[10, 10], [110, 10]]
    sample.recalc_scale()
    sample.measurements = [
        {'kind': 'a', 'points': [[20, 20], [20, 120], [120, 20]]},
        {'kind': 't1', 'points': [[200, 20], [200, 60]]},
        {'kind': 't2', 'points': [[220, 20], [250, 60]]},
    ]
    project = Project([sample])
    dest = tmp_path / 'thickness.weldproj'
    save_project(project, dest)
    with zipfile.ZipFile(dest) as archive:
        assert 'pomiary_liniowe.csv' in archive.namelist()
    loaded = load_project(dest)
    try:
        other = loaded.samples[0]
        assert other.measurements == sample.measurements
        assert measurement_mm(other.measurements[1], other.mm_per_px) == pytest.approx(4)
        assert measurement_mm(other.measurements[2], other.mm_per_px) == pytest.approx(5)
        out = export_results(loaded, tmp_path)
        rows = list(csv.DictReader(io.StringIO((out/'pomiary_liniowe.csv').read_text('utf-8-sig')), delimiter=';'))
        assert len(rows) == 3
        assert float(rows[1]['wymiar_mm']) == pytest.approx(4)
        assert json.loads(rows[0]['punkty_px']) == sample.measurements[0]['points']
        annotated = cv2.imdecode(np.frombuffer(next(out.glob('*_wynik.png')).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        assert not np.array_equal(annotated, image)
        # Recalibration recomputes dimensions from original pixels.
        other.known_mm = 20
        other.recalc_scale()
        assert measurement_mm(other.measurements[1], other.mm_per_px) == pytest.approx(8)
    finally:
        loaded.close()


def test_old_project_without_measurements_and_out_of_bounds(tmp_path):
    path = tmp_path/'image.png'
    image_write(path, np.zeros((100, 120, 3), np.uint8))
    sample = Sample.from_file(path)
    metadata = sample.meta()
    del metadata['measurements']
    assert Sample.from_meta(metadata, path, {}).measurements == []
    with pytest.raises(ValueError):
        validate_measurements([{'kind': 't1', 'points': [[5, 5], [150, 5]]}], (100, 120))
