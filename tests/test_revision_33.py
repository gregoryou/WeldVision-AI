"""Regression: 5-tab revision, definition of throat a, Excel and unit safety."""
import csv
import math
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
import numpy as np
import pytest

from weldvision.measurements import measurement_geometry, measurement_mm
from weldvision.core import Sample, Project, export_results, image_write, png_bytes, from_png
from weldvision.calibration import pixel_to_mm_matrix


def _measurement(points, matrix=None, mm_per_px=1):
    return measurement_mm({'kind':'a_contour','points':points},mm_per_px,matrix)


def test_straight_equal_legs_a_equals_leg_over_sqrt2():
    assert _measurement([[0,0],[0,100],[100,0]]) == pytest.approx(100/math.sqrt(2))


def test_unequal_legs_nominal_is_smaller_equal_leg_triangle():
    assert _measurement([[0,0],[0,100],[80,0]]) == pytest.approx(80/math.sqrt(2))


def test_concave_face_reduces_nominal_throat():
    assert _measurement([[0,0],[0,100],[20,20],[100,0]]) == pytest.approx(20*math.sqrt(2))


def test_convex_face_does_not_increase_nominal_throat():
    assert _measurement([[0,0],[0,100],[75,75],[100,0]]) == pytest.approx(100/math.sqrt(2))


def test_throat_obtuse_angle_symmetric():
    theta=120*math.pi/180
    points=[[0,0],[100,0],[100*math.cos(theta),100*math.sin(theta)]]
    assert _measurement(points) == pytest.approx(50)


def test_anisotropic_calibration_uses_physical_mm():
    # Image grid 100px/10mm X, 50px/10mm Y.
    m=pixel_to_mm_matrix([[0,0],[100,0],[0,50]],10)
    assert _measurement([[0,0],[0,50],[100,0]],m) == pytest.approx(10/math.sqrt(2))
    assert _measurement([[0,0],[0,50],[20,10],[100,0]],m) == pytest.approx(2*math.sqrt(2))


def test_bad_face_outside_fusion_wedge_fails():
    with pytest.raises(ValueError,match='poza kątem'):
        _measurement([[0,0],[0,100],[-10,40],[100,0]])


def test_legacy_3point_a_requires_remeasurement():
    legacy={'kind':'a','points':[[0,0],[0,100],[100,0]]}
    assert measurement_mm(legacy,.1) is None
    assert measurement_geometry('a',legacy['points'])[2]>0  # old project remains readable


def test_excel_export_and_clean_measurement_image(tmp_path):
    path=tmp_path/'pic.png'
    img=np.zeros((180,240,3),np.uint8)
    img[:]=(50,100,140)
    image_write(path,img)
    s=Sample.from_file(path,density=2.66)
    s.cal_points=[[0,0],[100,0],[0,50]]
    s.recalc_scale()
    mask=np.zeros((180,240),np.uint8)
    mask[50:100,60:140]=255
    s.set_mask('mask',mask)
    s.measurements=[{'kind':'a_contour','points':[[30,30],[30,80],[130,30]]},
                    {'kind':'a','points':[[30,30],[30,80],[130,30]]}]
    out=export_results(Project([s]),tmp_path/'exports')
    assert (out/'wyniki_zbiorcze.xlsx').exists()
    assert (out/'wyniki_zbiorcze.csv').exists()
    assert (out/'pomiary_liniowe.csv').exists()
    assert len(list(out.glob('*_pomiary_czyste.png')))==1
    from weldvision.core import image_read
    cleaned=image_read(next(out.glob('*_pomiary_czyste.png')))
    # Pixel away from the line must be original (no red mask segmentation).
    assert np.array_equal(cleaned[90,80],img[90,80])
    with ZipFile(out/'wyniki_zbiorcze.xlsx') as z:
        assert z.testzip() is None
        for name in ('xl/workbook.xml','xl/styles.xml','xl/worksheets/sheet1.xml',
                     'xl/worksheets/sheet2.xml','xl/worksheets/sheet3.xml'):
            ET.fromstring(z.read(name))
        ss=ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        assert len(ss.findall('.//m:sheetData/m:row',ns))==3
        xml=z.read('xl/worksheets/sheet2.xml').decode()
        assert 'WYMAGA POWTÓRZENIA' in xml
        assert 'a_contour' in xml
    with (out/'wyniki_zbiorcze.csv').open(encoding='utf-8-sig') as f:
        values=list(csv.DictReader(f,delimiter=';'))[0]
    assert float(values['pole_mm2']) == pytest.approx(80)
    assert float(values['objetosc_cm3_m']) == pytest.approx(80)
