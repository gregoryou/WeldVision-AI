"""Testy regresyjne kalibracji siatki 10x10 mm oraz fizyki jednostek."""
import csv
import io
import math
import numpy as np
import pytest

from weldvision.calibration import pixel_area_mm2, pixel_to_mm_matrix
from weldvision.core import Sample, Project, image_write, metrics, load_project, save_project, csv_content
from weldvision.measurements import measurement_geometry, measurement_mm


def test_area_equals_volume_cm3_per_meter_by_unit_conversion():
    # Zrzut ekranu: 156809 pikseli, A=27.1607 mm2 (równość nie jest błędem).
    pixels=156809
    mm_per_px=math.sqrt(27.1607/pixels)
    mask=np.ones((1,pixels),np.uint8)
    r=metrics(mask,mm_per_px,2.66)
    assert r['area_mm2']==pytest.approx(27.1607)
    assert r['volume_cm3_m']==pytest.approx(27.1607)
    assert r['mass_g_m']==pytest.approx(72.247462)
    assert r['mass_kg_m']==pytest.approx(.072247462)


def test_square_grid_10_by_10_area_and_linear_measurements():
    # 10 mm w poziomie odpowiada 100 px; w pionie 50 px.
    p=[[10,20],[110,20],[10,70]]
    m=pixel_to_mm_matrix(p,10)
    assert np.array(m)==pytest.approx(np.array(((.1,0),(0,.2))))
    assert pixel_area_mm2(m)==pytest.approx(.02)
    assert metrics(np.ones((50,100),np.uint8), .1, 2.66, pixel_area_mm2(m))['area_mm2']==pytest.approx(100)
    assert measurement_mm({'kind':'t1','points':[[10,20],[10,70]]},None,m)==pytest.approx(10)
    assert measurement_mm({'kind':'t2','points':[[10,20],[110,20]]},None,m)==pytest.approx(10)
    assert measurement_mm({'kind':'distance','points':[[10,20],[110,70]]},None,m)==pytest.approx(math.sqrt(200))


def test_grid_rotated_skewed_has_exact_area_and_perpendicularity():
    p=[[30,40],[130,50],[40,90]]
    m=pixel_to_mm_matrix(p,10)
    assert pixel_area_mm2(m)==pytest.approx(100/4900)
    # Odcinek grani (30,40) do przeciwprostokątnej (130,50)-(40,90).
    # Transformowane punkty to (0,0), (10,0), (0,10) => a=sqrt(50) mm.
    item={'kind':'a_contour','points':[p[0],p[1],p[2]]}
    assert measurement_mm(item,None,m)==pytest.approx(math.sqrt(50))
    assert measurement_geometry('a_contour',item['points'],m)[1]==pytest.approx((85,70))


def test_invalid_grid_rejected():
    assert pixel_to_mm_matrix([[0,0],[100,0],[200,0]],10) is None
    assert pixel_to_mm_matrix([[0,0],[0,0],[10,10]],10) is None
    assert pixel_to_mm_matrix([[0,0],[100,0],[0,100]],0) is None


def test_save_load_and_export_grid_area(tmp_path):
    img=np.zeros((200,300,3),np.uint8)
    path=tmp_path/'pic.png'
    image_write(path,img)
    s=Sample.from_file(path, density=2.66)
    s.cal_points=[[10,20],[110,20],[10,70]]
    s.recalc_scale()
    mask=np.zeros(s.dimensions,np.uint8)
    mask[30:80,20:120]=255
    s.set_mask('mask',mask)
    s.measurements=[{'kind':'t1','points':[[50,20],[50,70]]}]
    project=Project([s]); project.active_id=s.uid
    assert s.summary()['pole_mm2']==pytest.approx(100)
    assert s.summary()['objetosc_cm3_m']==pytest.approx(100)
    dst=tmp_path/'calibrated.weldproj'
    save_project(project,dst)
    p=load_project(dst)
    try:
        ss=p.samples[0]
        assert len(ss.cal_points)==3
        assert ss.area_per_pixel()==pytest.approx(.02)
        assert ss.summary()['pole_mm2']==pytest.approx(100)
        assert measurement_mm(ss.measurements[0],ss.mm_per_px,ss.calibration_matrix())==pytest.approx(10)
        rows=list(csv.DictReader(io.StringIO(csv_content(p).decode('utf-8-sig')),delimiter=';'))
        assert float(rows[0]['pole_mm2'])==pytest.approx(100)
        assert rows[0]['tryb_kalibracji']=='siatka_2d'
        assert float(rows[0]['mm2_na_px2'])==pytest.approx(.02)
        assert rows[0]['macierz_px_na_mm']
    finally:
        p.close()


def test_legacy_two_point_calibration_unchanged():
    s=Sample('a'*32,'a','','x.jpg',dimensions=(100,100))
    s.cal_points=[[0,0],[100,0]]
    s.recalc_scale()
    assert s.mm_per_px==pytest.approx(.1)
    assert s.area_per_pixel()==pytest.approx(.01)
    assert metrics(np.ones((10,10),np.uint8),s.mm_per_px,2.66,s.area_per_pixel())['area_mm2']==pytest.approx(1)


def test_grid_validation_uses_physical_geometry(tmp_path):
    from weldvision.measurements import validate_measurements
    m=pixel_to_mm_matrix([[10,10],[110,10],[10,35]],10)
    item={'kind':'a_contour','points':[[50,50],[150,50],[50,100]]}
    assert measurement_mm(item,None,m)>0
    assert len(validate_measurements([item],(250,300),m))==1
    with pytest.raises(ValueError):
        validate_measurements([{'kind':'a_contour','points':[[400,50],[150,50],[50,100]]}],(250,300),m)
