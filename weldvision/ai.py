"""Izolowany silnik SAM; moduły AI importowane wyłącznie w procesie roboczym."""
from __future__ import annotations

import gc
import json
import os
import sys
import traceback
from pathlib import Path

import cv2
import numpy as np

from .core import image_read, png_bytes, roi_tuple

os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')


def notify(kind, **kwargs):
    print(json.dumps({'kind': kind, **kwargs}, ensure_ascii=False), flush=True)


def dependencies():
    info = {'python': sys.executable, 'packages': {}, 'cuda': False, 'gpu': '', 'runtime': None}
    for name in ('numpy', 'cv2', 'PIL', 'torch', 'transformers', 'safetensors'):
        try:
            module = __import__(name)
            info['packages'][name] = getattr(module, '__version__', 'OK')
        except Exception as exc:
            info['packages'][name] = f'BRAK ({type(exc).__name__}: {exc})'
    try:
        import torch
        info['cuda'] = bool(torch.cuda.is_available())
        info['runtime'] = torch.version.cuda
        if info['cuda']:
            info['gpu'] = torch.cuda.get_device_name(0)
    except Exception:
        pass
    return info


def check_ai(device):
    info = dependencies()
    missing = [m for m in ('torch','transformers','PIL','safetensors')
               if str(info['packages'][m]).startswith('BRAK')]
    notify('diagnostic', **info)
    if missing:
        raise RuntimeError(
            'Brakuje pakietów w interpreterze procesu roboczego: ' + ', '.join(missing)
            + '\nInterpreter: ' + info['python']
            + '\nUruchom Install_AI_NVIDIA_CUDA.bat w folderze programu.'
        )
    if device == 'cuda' and not info['cuda']:
        raise RuntimeError('Wybrano CUDA, ale PyTorch nie wykrywa GPU. Sprawdź instalację CUDA/PyTorch.')
    return info


def crop_image(img, pos, neg, box, margin=0.06):
    h, w = img.shape[:2]
    if box is None:
        return img, pos, neg, None, (0,0,w,h)
    x1,y1,x2,y2 = box
    x1, x2 = sorted((max(0, int(x1)), min(w, int(x2))))
    y1, y2 = sorted((max(0, int(y1)), min(h, int(y2))))
    pad = max(16, int(max(x2-x1,y2-y1)*margin))
    a,b,c,d = max(0,x1-pad), max(0,y1-pad), min(w,x2+pad), min(h,y2+pad)
    def local(points):
        return [[float(x-a), float(y-b)] for x,y in points if a <= x < c and b <= y < d]
    return img[b:d,a:c].copy(), local(pos), local(neg), (x1-a,y1-b,x2-a,y2-b), (a,b,c,d)


def sample_seed(mask_blob, shape, limit=40):
    if not mask_blob:
        return []
    from .core import from_png
    mask = from_png(bytes.fromhex(mask_blob) if isinstance(mask_blob, str) else mask_blob, shape)
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return []
    indices = np.linspace(0, len(xs)-1, min(limit, len(xs)), dtype=np.int64)
    return [[float(xs[i]), float(ys[i])] for i in indices]


def best_mask(outputs, inputs, shape):
    scores = outputs.iou_scores.detach().float().cpu().numpy().reshape(-1)
    pred = outputs.pred_masks.detach().float().cpu().numpy()
    candidates = pred.reshape(-1, *pred.shape[-2:])
    idx = int(np.argmax(scores)) if len(scores) == len(candidates) else 0
    low = candidates[idx]
    ph,pw = inputs['pixel_values'].shape[-2:]
    up = cv2.resize(low, (int(pw),int(ph)), interpolation=cv2.INTER_LINEAR)
    reshaped = inputs['reshaped_input_sizes'][0].detach().cpu().numpy()
    rh,rw = int(reshaped[0]), int(reshaped[1])
    up = up[:rh,:rw]
    h,w = shape[:2]
    result = cv2.resize(up, (w,h), interpolation=cv2.INTER_LINEAR)
    return (result > 0).astype(np.uint8) * 255


def run_grabcut_job(job):
    """GrabCut w procesie izolowanym: nie potrzebuje torch ani Transformers."""
    directory=Path(job['output_dir'])
    directory.mkdir(parents=True,exist_ok=True)
    tasks=job['tasks']
    done=0
    for order,task in enumerate(tasks,1):
        uid=task['uid']
        try:
            img=image_read(task['image_path'])
            if img is None:
                raise FileNotFoundError(task['image_path'])
            H,W=img.shape[:2]
            box=task.get('roi')
            pos=task.get('pos',[])
            neg=task.get('neg',[])
            if box is None and not pos:
                raise ValueError('GrabCut wymaga ROI albo FG')
            cut,p,n,roi,bounds=crop_image(img,pos,neg,box)
            h,w=cut.shape[:2]
            segmentation=np.full((h,w),cv2.GC_PR_BGD,np.uint8)
            if roi:
                x1,y1,x2,y2=roi
                segmentation[:]=cv2.GC_BGD
                segmentation[y1:y2,x1:x2]=cv2.GC_PR_FGD
            elif p:
                segmentation[:]=cv2.GC_PR_BGD
            for x,y in n:
                cv2.circle(segmentation,(int(x),int(y)),4,cv2.GC_BGD,-1)
            for x,y in p:
                cv2.circle(segmentation,(int(x),int(y)),4,cv2.GC_FGD,-1)
            if not np.any(segmentation==cv2.GC_FGD) and not np.any(segmentation==cv2.GC_PR_FGD):
                raise ValueError('GrabCut nie ma obszaru pierwszego planu')
            bg=np.zeros((1,65),np.float64)
            fg=np.zeros((1,65),np.float64)
            notify('progress',message=f'GrabCut {order}/{len(tasks)} · {Path(task["image_path"]).name}')
            cv2.grabCut(cut,segmentation,None,bg,fg,5,cv2.GC_INIT_WITH_MASK)
            small=np.where((segmentation==cv2.GC_PR_FGD)|(segmentation==cv2.GC_FGD),255,0).astype(np.uint8)
            result=np.zeros((H,W),np.uint8)
            x0,y0,x1,y1=bounds
            result[y0:y1,x0:x1]=small
            outfile=directory/(uid+'.png')
            outfile.write_bytes(png_bytes(result))
            done+=1
            notify('result',uid=uid,revision=task['revision'],path=str(outfile),index=order,total=len(tasks),method='GrabCut')
        except Exception as e:
            notify('sample_error',uid=uid,error=f'{type(e).__name__}: {e}')
    notify('finished',processed=done,total=len(tasks))
    return 0


def run_job(job_path):
    try:
        job = json.loads(Path(job_path).read_text(encoding='utf-8'))
        if job.get('mode')=='grabcut':
            return run_grabcut_job(job)
        device_choice = job.get('device', 'auto')
        check_ai(device_choice)
        import torch
        from PIL import Image
        from transformers import SamModel, SamProcessor

        device = 'cuda' if torch.cuda.is_available() and device_choice != 'cpu' else 'cpu'
        model_id = job.get('model_id','facebook/sam-vit-large')
        if model_id not in ('facebook/sam-vit-base','facebook/sam-vit-large','facebook/sam-vit-huge'):
            raise ValueError('Nieobsługiwany model SAM')
        notify('progress', message=f'Ładowanie {model_id} na {device} (tylko jeden model)')
        processor = SamProcessor.from_pretrained(model_id)
        if device == 'cuda':
            try:
                model = SamModel.from_pretrained(model_id, dtype=torch.float16)
            except TypeError:
                model = SamModel.from_pretrained(model_id, torch_dtype=torch.float16)
        else:
            model = SamModel.from_pretrained(model_id)
        model.to(device).eval()
        directory = Path(job['output_dir'])
        directory.mkdir(parents=True, exist_ok=True)
        tasks = job['tasks']
        count = 0
        for order, task in enumerate(tasks, 1):
            uid = task['uid']
            try:
                img = image_read(task['image_path'])
                if img is None:
                    raise FileNotFoundError(task['image_path'])
                shape = img.shape[:2]
                # prompts passed as points in JSON, not full-size masks
                pos, neg = task.get('pos', []), task.get('neg', [])
                roi = task.get('roi')
                if not roi and not pos:
                    raise ValueError('Brak ROI i FG')
                cropped, p, n, b, bounds = crop_image(img, pos, neg, roi)
                if roi is not None:
                    notify('progress', message=f'{order}/{len(tasks)} · ROI {cropped.shape[1]}×{cropped.shape[0]} px')
                else:
                    notify('progress', message=f'{order}/{len(tasks)} · całe zdjęcie (większa pamięć)')
                image = Image.fromarray(cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB))
                kwargs = {'images':image, 'return_tensors':'pt'}
                if p or n:
                    kwargs['input_points'] = [[p+n]]
                    kwargs['input_labels'] = [[[1]*len(p)+[0]*len(n)]]
                if b:
                    kwargs['input_boxes'] = [[[float(v) for v in b]]]
                encoded = processor(**kwargs)
                encoded = {key: value.to(device) if hasattr(value,'to') else value
                           for key,value in encoded.items()}
                if device == 'cuda':
                    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16):
                        result = model(**encoded)
                else:
                    with torch.inference_mode():
                        result = model(**encoded)
                small = best_mask(result, encoded, cropped.shape)
                full = np.zeros(shape, np.uint8)
                x0,y0,x1,y1 = bounds
                full[y0:y1,x0:x1] = small
                # binary png may be much smaller than uncompressed 4K masks
                out = directory / (uid + '.png')
                out.write_bytes(png_bytes(full))
                del encoded, result, small, full, cropped, img, image
                gc.collect()
                if device == 'cuda':
                    torch.cuda.empty_cache()
                count += 1
                notify('result', uid=uid, revision=task['revision'], path=str(out), index=order, total=len(tasks), method='SAM')
            except Exception as e:
                notify('sample_error', uid=uid, error=f'{type(e).__name__}: {e}')
                if 'out of memory' in str(e).lower():
                    try:
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    notify('fatal', error='Brak VRAM podczas analizy. Zmniejsz ROI albo użyj SAM Large.',
                           traceback=traceback.format_exc(limit=4))
                    return 2
        notify('finished', processed=count, total=len(tasks))
        return 0
    except Exception as e:
        notify('fatal', error=f'{type(e).__name__}: {e}', traceback=traceback.format_exc(limit=8))
        return 2


def worker_main(argv):
    if len(argv) >= 2 and argv[0] == '--worker':
        return run_job(argv[1])
    if argv and argv[0] == '--diagnose':
        info=dependencies()
        notify('diagnostic', **info)
        return 0
    return 2
