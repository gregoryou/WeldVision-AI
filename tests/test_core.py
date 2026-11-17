import json
import io
import zipfile
from pathlib import Path
from random import Random

import cv2
import numpy as np
import pytest

from weldvision.core import (
    Project, Sample, STATUS_REVIEW, STATUS_APPROVED, clean_mask, export_results,
    export_stems, image_write, load_project, metrics, png_bytes, from_png,
    save_project, scaled_roi, clip_mask_roi
)


def sample_image(folder, name='image.png', size=(150,220)):
    arr=np.zeros((size[0],size[1],3),np.uint8)
    arr[:]=[160,130,120]
    arr[10:130,20:180]=[50,100,240]
    path=folder/name
    image_write(path,arr)
    return str(path)


def prepare_sample(folder, name='T1', index=0):
    path=sample_image(folder,f'image_{index}.png')
    s=Sample.from_file(path)
    s.name=name
    s.cal_points=[[10,15],[110,15]]
    s.recalc_scale()
    s.roi_start=(20,20)
    s.roi_end=(170,130)
    m=np.zeros(s.dimensions,np.uint8)
    m[30:80,40+index:130+index]=255
    s.set_mask('mask',m)
    s.set_mask('raw',m)
    f=np.zeros(s.dimensions,np.uint8)
    f[50:60,50:60]=255
    s.set_mask('fg',f)
    b=np.zeros(s.dimensions,np.uint8)
    b[5:12,7:11]=255
    s.set_mask('bg',b)
    s.state=STATUS_REVIEW
    return s


def test_metrics_scale_and_density():
    m=np.ones((10,10),np.uint8)*255
    first=metrics(m,0.1,7.85)
    second=metrics(m,0.2,7.85)
    assert second['area_mm2']==pytest.approx(4*first['area_mm2'])
    assert first['mass_g_m']==pytest.approx(7.85)
    assert first['mass_kg_m']==pytest.approx(.00785)


def test_mask_default_does_not_change_area():
    m=np.zeros((60,60),np.uint8)
    m[4,7]=255
    m[17:21,20:30]=255
    assert np.array_equal(clean_mask(m),m)
    assert np.count_nonzero(clean_mask(m,min_area=3)) == 40


def test_clip_roi_and_copy_scaled_coordinates():
    m=np.ones((100,200),np.uint8)*255
    roi=(20,30,60,80)
    assert np.count_nonzero(clip_mask_roi(m,roi))==2000
    start,end=scaled_roi((20,30),(100,70),(100,200),(200,400))
    assert start==(40,60)
    assert end==(200,140)


def test_sample_markers_survive_100_navigations(tmp_path):
    samples=[prepare_sample(tmp_path,f'Próbka_{i}',i) for i in range(15)]
    originals={s.uid:(s.mask('mask').copy(),s.mask('fg').copy(),s.mask('bg').copy(),s.roi())
               for s in samples}
    r=Random(240)
    for _ in range(100):
        s=samples[r.randrange(len(samples))]
        a,b,c,roi=originals[s.uid]
        assert np.array_equal(s.mask('mask'),a)
        assert np.array_equal(s.mask('fg'),b)
        assert np.array_equal(s.mask('bg'),c)
        assert s.roi()==roi


def test_round_trip_all_data_and_backup(tmp_path):
    samples=[prepare_sample(tmp_path,f'Weld_{i}',i) for i in range(5)]
    samples[0].state=STATUS_APPROVED
    samples[0].approved_at='2026-11-07T11:00:00+00:00'
    project=Project(samples)
    project.active_id=samples[-1].uid
    project.mark_dirty()
    target=tmp_path/'my_project.weldproj'
    save_project(project,target)
    assert not project.dirty
    loaded=load_project(target)
    assert loaded.active_id==samples[-1].uid
    assert [s.uid for s in loaded.samples]==[s.uid for s in samples]
    for old,new in zip(samples,loaded.samples):
        assert old.source_name==new.source_name
        assert old.cal_points==new.cal_points
        assert old.roi()==new.roi()
        assert old.mm_per_px==pytest.approx(new.mm_per_px)
        assert old.state==new.state
        for kind in ('mask','raw','fg','bg'):
            assert np.array_equal(old.mask(kind),new.mask(kind))
    loaded.samples[0].name='Zmiana'
    loaded.mark_dirty()
    save_project(loaded,target)
    assert target.with_suffix('.weldproj.bak').exists()
    loaded2=load_project(target)
    assert loaded2.samples[0].name=='Zmiana'
    loaded2.close(); loaded.close()


def test_failed_save_leaves_previous_archive_intact(tmp_path):
    s=prepare_sample(tmp_path)
    project=Project([s])
    path=tmp_path/'safe.weldproj'
    save_project(project,path)
    before=path.read_bytes()
    s.image_path=str(tmp_path/'non_existent.png')
    with pytest.raises(FileNotFoundError):
        save_project(project,path)
    assert path.read_bytes()==before
    restored=load_project(path)
    assert restored.samples[0].name==s.name
    restored.close()


def test_corrupt_project_never_silently_opened(tmp_path):
    f=tmp_path/'broken.weldproj'
    f.write_bytes(b'broken zip')
    with pytest.raises((ValueError,zipfile.BadZipFile)):
        load_project(f)


def test_legacy_v1_compatible(tmp_path):
    pic=sample_image(tmp_path, 'old.jpg')
    img=Path(pic).read_bytes()
    mask=np.zeros((150,220),np.uint8)
    mask[30:80,40:110]=255
    fg=np.zeros_like(mask)
    fg[45:50,55:62]=255
    path=tmp_path/'old_project.weldproj'
    legacy={"version":1,"current_index":0,"model_id":"facebook/sam-vit-large","items":[{
        "sample_name":"Stara próbka","source_name":"old.jpg", "known_mm":10,
        "mm_per_px":.01,"density":7.85,"roi_start":[30,20],"roi_end":[145,120],
        "files":{"image":"item_000/image.jpg","mask":"item_000/mask.png","fg":"item_000/fg.png"}
    }]}
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('project.json',json.dumps(legacy))
        z.writestr('item_000/image.jpg',img)
        z.writestr('item_000/mask.png',png_bytes(mask))
        z.writestr('item_000/fg.png',png_bytes(fg))
    loaded=load_project(path)
    assert loaded.samples[0].name=='Stara próbka'
    assert loaded.samples[0].source_name=='old.jpg'
    assert np.array_equal(loaded.samples[0].mask('fg'),fg)
    migrated=tmp_path/'migrated.weldproj'
    save_project(loaded,migrated)
    again=load_project(migrated)
    assert again.samples[0].source_name=='old.jpg'
    assert np.array_equal(again.samples[0].mask('mask'),mask)
    again.close(); loaded.close()


def test_export_unique_names_and_originals(tmp_path):
    samples=[prepare_sample(tmp_path,name,i) for i,name in enumerate(('A','A_02','A'))]
    stems=export_stems(samples)
    assert len(set(stems))==3
    project=Project(samples)
    out=export_results(project,tmp_path)
    assert len(list(out.glob('*_maska.png')))==3
    assert len(list(out.glob('*_wynik.png')))==3
    assert (out/'wyniki_zbiorcze.csv').exists()
    out2=export_results(project,tmp_path)
    assert out!=out2


def test_diagnose_subprocess_without_transformers(tmp_path):
    # Test procesu roboczego — przy braku zależności pokazuje konkretne nazwy, nie VRAM.
    import subprocess,sys
    script=Path(__file__).resolve().parent.parent/'weldvision_ai.py'
    p=subprocess.run([sys.executable,str(script),'--diagnose'],capture_output=True,text=True,encoding='utf-8')
    assert p.returncode==0
    report=json.loads(p.stdout.strip())
    assert report['kind']=='diagnostic'
    assert report['python']==sys.executable
    assert 'torch' in report['packages']
    assert 'transformers' in report['packages']
