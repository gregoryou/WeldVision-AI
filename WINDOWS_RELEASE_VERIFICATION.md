# Windows release acceptance checklist (owner to perform)

The local preflight helper is supplied separately in the WeldVision AI 3.2 OSS-prep archive. It does not install packages, download weights or publish.

## Preconditions
- Local clone of gregoryou/WeldVision-AI
- Python 3.13 and the venv at %LOCALAPPDATA%\\WeldVisionAI\\venv
- Dependencies installed by the existing documented procedure

## Automated
Run from the local project root:

```powershell
& "$env:LOCALAPPDATA\WeldVisionAI\venv\Scripts\python.exe" -m pytest -q tests
& "$env:LOCALAPPDATA\WeldVisionAI\venv\Scripts\python.exe" weldvision_ai.py --diagnose
nvidia-smi
```

Record OS build, GPU + driver, PyQt6/PyTorch/Transformers versions, CUDA availability and all test failures.

## Manual GUI (synthetic test data)
- [ ] Start app; import two synthetic test images.
- [ ] Calibrate a 100-pixel segment as 10 mm: expected 0.1 mm/px.
- [ ] Measure 50-pixel thickness: expected 5.000 mm.
- [ ] Check 3-point weld throat geometry, projection and invalid points.
- [ ] Zoom/pan, undo/redo, cancel, delete, navigation and re-calibration.
- [ ] Save, reopen .weldproj; verify data and measurement persistence.
- [ ] Export CSV/image, verify values and data/privacy controls.
- [ ] Test GrabCut and invalid/corrupted project without data loss.

## Optional AI GPU
- [ ] First verify torch.cuda.is_available() with actual venv.
- [ ] Download/use a SAM model only with user consent and verified license; record model ID.
- [ ] Run real inference on synthetic image and verify mask, sample mapping and VRAM behavior.

Do not mark this release as tested merely on the basis of the earlier Linux suite. Do not make public until ownership and license clearance are complete.