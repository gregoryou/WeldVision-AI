"""Regression on example macrographs bundled with the review environment.
The images are optional: the end-user ZIP does not include research photos.
"""
from pathlib import Path
import hashlib
import numpy as np
import pytest
from weldvision.core import Project, Sample, load_project, save_project, export_results

PHOTOS = Path('/mnt/data')


def test_real_photo_roundtrip_and_export(tmp_path):
    filenames = sorted(PHOTOS.glob('DSC_*.JPG'))
    if not filenames:
        pytest.skip('Brak zdjęć przykładowych w środowisku')
    samples=[]
    for i,photo in enumerate(filenames):
        s=Sample.from_file(photo)
        s.known_mm=10
        s.cal_points=[[100.0,100.0],[800.0,100.0]]
        s.recalc_scale()
        s.roi_start=(300,450)
        s.roi_end=(1200,1000)
        mask=np.zeros(s.dimensions,np.uint8)
        mask[600:650,650:750]=255
        fg=np.zeros_like(mask)
        fg[620:626,670:677]=255
        bg=np.zeros_like(mask)
        bg[200:210,200:220]=255
        s.set_mask('mask',mask)
        s.set_mask('fg',fg)
        s.set_mask('bg',bg)
        s.name=f'Seria_{i:02d}'
        samples.append(s)
    project=Project(samples)
    project.active_id=samples[3].uid
    project.mark_dirty()
    out=tmp_path/'real_photos.weldproj'
    save_project(project,out)
    loaded=load_project(out)
    assert len(loaded.samples)==len(filenames)
    assert loaded.active_id==samples[3].uid
    for old,new in zip(samples,loaded.samples):
        assert old.name==new.name
        assert old.roi()==new.roi()
        assert old.cal_points==new.cal_points
        assert old.mm_per_px==new.mm_per_px
        for kind in ('mask','fg','bg'):
            assert np.array_equal(old.mask(kind),new.mask(kind))
        assert hashlib.sha256(Path(old.image_path).read_bytes()).digest()==hashlib.sha256(Path(new.image_path).read_bytes()).digest()
    exported=export_results(loaded,tmp_path/'export')
    assert len(list(exported.glob('*_wynik.png')))==len(filenames)
    assert len(list(exported.glob('*_maska.png')))==len(filenames)
    assert len(list(exported.glob('*_oryginal.JPG')))==0  # names normalized to lower case .jpg
    assert len(list(exported.glob('*_oryginal.jpg')))==len(filenames)
    assert (exported/'wyniki_zbiorcze.csv').exists()
    loaded.close()
