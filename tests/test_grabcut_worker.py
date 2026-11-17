"""GrabCut runs in an isolated process without requiring torch/Transformers."""
import json
from pathlib import Path
import cv2
import numpy as np
from weldvision.core import from_png, image_write
from weldvision.ai import run_job


def test_grabcut_no_ai_environment(tmp_path, capsys):
    H,W=250,320
    img=np.full((H,W,3),(160,160,160),dtype=np.uint8)
    cv2.rectangle(img,(80,65),(245,185),(25,25,225),-1)
    file=tmp_path/'sample.png'
    image_write(file,img)
    job={'mode':'grabcut','model_id':'unused','device':'auto',
         'tasks':[{'uid':'a'*32,'revision':0,'image_path':str(file),
                   'roi':[65,50,260,205], 'pos':[[140,125]],
                   'neg':[[70,55]]}], 'output_dir':str(tmp_path/'out')}
    p=tmp_path/'job.json';p.write_text(json.dumps(job),encoding='utf8')
    assert run_job(p)==0
    lines=[json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(m['kind']=='result' for m in lines)
    mask=from_png((tmp_path/'out'/('a'*32+'.png')).read_bytes(),(H,W))
    assert np.count_nonzero(mask)>1000
