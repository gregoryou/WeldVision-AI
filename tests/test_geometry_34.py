"""Acceptance tests for geometry, live formatting, EXIF, and photo export."""
from copy import deepcopy
import hashlib
from math import hypot, sqrt
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import numpy as np
from PIL import Image
import pytest

from weldvision.core import Project, Sample, export_results, image_write, load_project, save_project
from weldvision.geometry import Scene, ellipse, make_object, to_mm, validate_objects
from weldvision.photo_annotations import export_photo, native_photo

SHAPE = (360, 520)
CAL = ((.1, 0.), (0., .2))


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / 'makro.png'
    image_write(path, np.full((*SHAPE, 3), 74, np.uint8))
    sample = Sample.from_file(path)
    sample.cal_points = [[10, 10], [110, 10], [10, 60]]
    sample.recalc_scale()
    return sample


def obj(kind, *points, refs=(), **fields):
    return make_object(kind, points, [item['id'] for item in refs], **fields)


def report(items, matrix=CAL):
    scene = Scene(items, matrix, SHAPE)
    return [scene[o['id']] for o in items]


def test_circle_affine_radius_and_ellipse():
    c = obj('circle', (100, 100), (148.2, 100), diameter=True)
    r, = report([c])
    assert r.value == pytest.approx(4.82)
    assert r.label == 'r = 4,82 mm   d = 9,64 mm'
    path = np.array(r.paths[0])
    assert np.ptp(path[:, 0]) == pytest.approx(96.4)
    assert np.ptp(path[:, 1]) == pytest.approx(48.2)
    skew = ((.10, .032), (-.017, .19))
    p = ellipse((10, 20), (40, 11), skew)
    radii = [hypot(*to_mm((x-10, y-20), skew)) for x, y in p]
    assert np.ptp(radii) < 1e-12
    assert report([c], None)[0].label == ''


def test_lines_projection_angle_and_intersection():
    a = obj('horizontal', (40, 40), (140, 65))
    b = obj('vertical', (90, 15), (100, 110))
    c = obj('angle', refs=(a, b))
    d = obj('intersection', refs=(a, b))
    e = obj('parallel', (100, 120), (150, 145), refs=(a,))
    f = obj('perpendicular', (100, 120), (150, 145), refs=(a,))
    g = obj('polyline', (20, 20), (70, 20), (70, 70))
    h = obj('infinite', (45, 100), (45, 140))
    rs = report([a, b, c, d, e, f, g, h])
    assert [r.value for r in rs] == pytest.approx([10, 19, 90, None, 5, 5, 15, 8], nan_ok=True)
    assert rs[3].anchor == (90., 40.)
    assert rs[4].line[1] == (150., 120.)
    assert rs[5].line[1] == (100., 145.)
    assert rs[7].paths[0] == ((45., 0.), (45., 359.))
    skew = ((.1, .04), (.02, .2))
    assert report([a, f, obj('angle', refs=(a, f))], skew)[-1].value == pytest.approx(90)
    with pytest.raises(ValueError, match='cykliczny'):
        validate_objects([c, a, b], SHAPE)


def test_throat_validates_triangle_line_and_contour():
    o = (50, 60)
    a = obj('line', (30, 60), (180, 60))
    b = obj('line', (50, 30), (50, 180))
    symmetric = obj('line', (150, 60), (50, 110))
    t = obj('throat', (0, 0), refs=(a, b, symmetric), method='straight')
    r = report([a, b, symmetric, t])[-1]
    assert r.value == pytest.approx(10/sqrt(2))
    assert r.value == r.radius
    assert len(r.triangle) == 4
    asymmetric = obj('line', (130, 60), (50, 110))
    t = obj('throat', (0, 0), refs=(a, b, asymmetric), method='straight')
    r = report([a, b, asymmetric, t])[-1]
    assert r.value is None and r.radius == pytest.approx(80/sqrt(164))
    assert 'a nieważne' in r.label
    concave = obj('polyline', (150, 60), (75, 72.5), (50, 110))
    t = obj('throat', (0, 0), refs=(a, b, concave), method='contour')
    assert report([a, b, concave, t])[-1].value == pytest.approx(2.5*sqrt(2))
    manual = obj('throat', (0, 0), (50, 25), refs=(a, b, symmetric), method='manual')
    assert report([a, b, symmetric, manual])[-1].value == pytest.approx(10/sqrt(2))
    off_boundary = dict(manual, points=[[0, 0], [10/sqrt(2)/.1, 0]])
    assert report([a, b, symmetric, off_boundary])[-1].value is None
    displaced = dict(manual, points=[[3, 3], [50, 25]])
    assert report([a, b, symmetric, displaced])[-1].value is None


@pytest.mark.parametrize('angle', [0, 90, 37, 180])
def test_scale_has_true_length_at_any_angle(angle):
    scale = obj('scale', (200, 160), length_mm=10., angle_deg=angle)
    r, = report([scale], ((.1, .03), (.02, .2)))
    a, b = r.paths[0]
    assert hypot(*to_mm((b[0]-a[0], b[1]-a[1]), ((.1, .03), (.02, .2)))) == pytest.approx(10)
    assert r.label == '10 mm'
    assert not report([scale], None)[0].paths


def test_visual_edits_do_not_change_values_or_geometry():
    c = obj('circle', (100, 100), (148.2, 100))
    original, = report([c])
    c['style'].update(line_color='#112233', line_width=9., font_family='Times New Roman',
                      font_pt=20., background='white', padding=8., decimals=3,
                      show_unit=False, label_y=15., bold=True, italic=True)
    styled, = report([c])
    assert styled.value == original.value and styled.paths == original.paths
    assert styled.label == 'r = 4,820'
    c['style'].update(signature='custom', custom_label='Próbka 4490')
    custom, = report([c])
    assert custom.value == original.value and custom.label == 'Próbka 4490'


def test_project_and_excel_share_the_display_labels(sample, tmp_path):
    a = obj('line', (20, 20), (120, 20))
    b = obj('vertical', (60, 30), (60, 80))
    c = obj('angle', refs=(a, b))
    circle = obj('circle', (160, 110), (200, 110), diameter=True)
    scale = obj('scale', (195, 200), length_mm=10., angle_deg=48)
    note = obj('comment', (140, 200))
    note['style'].update(signature='custom', custom_label='Próbka 3315', background='white')
    sample.geometry_objects = validate_objects([a, b, c, circle, scale, note], sample.dimensions)
    sample.measurements = [{'kind': 't1', 'points': [[200, 30], [200, 60]]}]
    p = Project([sample])
    destination = tmp_path/'project.weldproj'
    save_project(p, destination)
    loaded = load_project(destination)
    try:
        s = loaded.samples[0]
        assert s.geometry_objects == sample.geometry_objects
        assert s.measurements == sample.measurements
        output = export_results(loaded, tmp_path/'results')
        with ZipFile(output/'wyniki_zbiorcze.xlsx') as archive:
            xml = archive.read('xl/worksheets/sheet2.xml')
            root = ET.fromstring(xml)
            ns = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            angle = root.find(".//x:c[@r='T5']/x:v", ns)
            assert float(angle.text) == 90
            for result in report(s.geometry_objects, s.calibration_matrix()):
                assert result.label in xml.decode()
            assert 't₁ = 6,00 mm'.encode() in xml
    finally:
        loaded.close()


@pytest.mark.parametrize('extension, name', [('.png','PNG'), ('.jpg','JPEG'), ('.jpeg','JPEG'),
                                              ('.bmp','BMP'), ('.tif','TIFF'), ('.tiff','TIFF')])
def test_export_matches_preview_in_native_resolution(sample, tmp_path, extension, name):
    a = obj('circle', (250, 140), (299, 140))
    a['style'].update(background='white', text_color='#101010', font_family='Times New Roman',
                      font_pt=15., line_color='#ff1010', line_width=4., line_pattern='dash')
    b = obj('scale', (140, 270), length_mm=10., angle_deg=38)
    b['style'].update(background='white', background_opacity=55)
    sample.geometry_objects = [a, b]
    original_hash = hashlib.sha256(open(sample.image_path, 'rb').read()).digest()
    chosen = {a['id']}
    preview, _ = native_photo(sample, 'publication', chosen, uniform=True)
    destination = tmp_path / ('publication'+extension)
    export_photo(sample, destination, 'publication', chosen, uniform=True)
    with Image.open(destination) as actual:
        assert actual.size == (520, 360) and actual.format == name
        d = np.abs(np.asarray(actual.convert('RGB')).astype(int)-np.asarray(preview).astype(int))
        assert (d.mean() < 1.6) if name == 'JPEG' else (d.max() == 0)
    original, _ = native_photo(sample, 'original')
    assert not np.array_equal(np.asarray(preview), np.asarray(original))
    assert hashlib.sha256(open(sample.image_path, 'rb').read()).digest() == original_hash
    with pytest.raises(ValueError, match='źródłową'):
        export_photo(sample, sample.image_path)


def test_white_background_and_alpha_are_rendered(sample):
    a = obj('scale', (125, 180), length_mm=10.)
    a['style'].update(background='white', background_opacity=100, line_width=4.5,
                      font_pt=14., padding=12., text_color='#000000', center='none')
    sample.geometry_objects = [a]
    opaque = np.asarray(native_photo(sample, 'measurements')[0])
    a['style']['background_opacity'] = 50
    translucent = np.asarray(native_photo(sample, 'measurements')[0])
    a['style']['background_opacity'] = 0
    transparent = np.asarray(native_photo(sample, 'measurements')[0])
    white = np.all(opaque == 255, axis=2)
    blends = white & (translucent[...,0] > 145) & (translucent[...,0] < 210)
    assert blends.sum() > 160
    assert np.count_nonzero(blends & (transparent[...,0] == 74)) > 100
    a['style']['label_x'] = 110.
    shifted = np.asarray(native_photo(sample, 'measurements')[0])
    assert not np.array_equal(shifted, transparent)


def test_original_native_format_copies_bytes(sample, tmp_path):
    out = export_photo(sample, tmp_path/'copy.png', 'original')
    assert hashlib.sha256(out.read_bytes()).digest() == hashlib.sha256(
        open(sample.image_path, 'rb').read()).digest()
    mask = np.zeros(sample.dimensions, np.uint8)
    mask[20:45, 40:80] = 255
    sample.set_mask('mask', mask)
    clean, _ = native_photo(sample, 'measurements')
    assert clean.getpixel((50, 30)) == (74, 74, 74)
