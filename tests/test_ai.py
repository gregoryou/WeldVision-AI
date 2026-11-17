import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from weldvision.ai import crop_image, check_ai, best_mask


def test_crop_local_coordinates_and_roi():
    img=np.zeros((1000,2000,3),np.uint8)
    roi=(650,250,1100,600)
    pos=[[800,400],[100,100]]
    neg=[[680,270],[1900,900]]
    cut,p,n,box,coords=crop_image(img,pos,neg,roi)
    x0,y0,x1,y1=coords
    assert cut.shape[0]<1000 and cut.shape[1]<2000
    assert len(p)==1 and len(n)==1
    assert p[0]==[800-x0,400-y0]
    assert box==(650-x0,250-y0,1100-x0,600-y0)


def test_preflight_precise_missing_dependency(monkeypatch):
    import weldvision.ai as ai
    report={'python':'C:/Python313/python.exe','packages':{
        'torch':'2.14.0+cu130','transformers':'BRAK (ModuleNotFoundError)','PIL':'12.0',
        'safetensors':'1.0'},'cuda':True,'gpu':'RTX 5070','runtime':'13.0'}
    monkeypatch.setattr(ai,'dependencies',lambda:report)
    with pytest.raises(RuntimeError,match='transformers') as info:
        check_ai('cuda')
    assert 'VRAM' not in str(info.value)
    assert 'C:/Python313/python.exe' in str(info.value)


def test_sam_mask_selection_cpu_tensor():
    torch=pytest.importorskip('torch')
    class Outputs:
        pass
    outputs=Outputs()
    outputs.iou_scores=torch.tensor([[[0.1,0.9,0.3]]])
    outputs.pred_masks=torch.zeros((1,1,3,16,16))
    outputs.pred_masks[0,0,1,2:14,2:14]=1
    inputs={'pixel_values':torch.zeros((1,3,64,64)),
            'reshaped_input_sizes':torch.tensor([[64,64]])}
    mask=best_mask(outputs,inputs,(100,200))
    assert mask.shape==(100,200)
    assert mask.dtype==np.uint8
    assert mask[50,100]==255
    assert mask[0,0]==0


def test_grabcut_isolated_worker_without_transformers(tmp_path):
    """Tryb GrabCut nie importuje torch ani Transformers; działa przez CLI."""
    from weldvision.core import image_write, from_png
    import subprocess,sys
    image=np.full((120,160,3),200,np.uint8)
    image[35:95,35:130]=30
    image_path=tmp_path/'photo.png'
    image_write(image_path,image)
    output=tmp_path/'output'
    uid='f'*32
    job={'mode':'grabcut','model_id':'facebook/sam-vit-huge','device':'cuda',
         'output_dir':str(output),'tasks':[{
            'uid':uid,'revision':4,'image_path':str(image_path),
            'roi':[30,30,135,100],'pos':[[60,60],[90,80]],'neg':[[30,35]]
         }]}
    jobpath=tmp_path/'task.json'
    jobpath.write_text(json.dumps(job),encoding='utf-8')
    script=Path(__file__).resolve().parent.parent/'weldvision_ai.py'
    p=subprocess.run([sys.executable,str(script),'--worker',str(jobpath)],
                     text=True,capture_output=True,timeout=30)
    assert p.returncode==0,p.stdout+'\n'+p.stderr
    records=[json.loads(x) for x in p.stdout.splitlines()]
    assert any(x.get('kind')=='result' and x.get('uid')==uid for x in records)
    mask=from_png((output/(uid+'.png')).read_bytes(),(120,160))
    assert np.count_nonzero(mask)>0
    assert mask[50,50]==255
