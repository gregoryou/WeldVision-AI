# Windows 11 pre-publication test evidence — 2026-11-17

**Project:** WeldVision AI 3.2 (source baseline commit `6132c98f6debd6a712eaf86ef4d7d9596f1e2147`)

**Report time:** 2026-11-17 20:07:16 +01:00

## Automated test outcomes
- Python: **3.13.15**
- PyQt6: **6.12.0**, Qt import exit code 0
- pytest (PyQt6 offscreen): **26 passed, 1 skipped, 0 failed, 0 errors** in **5.84 s**, exit code 0
- NVIDIA GPU: **RTX 5070**, **12,227 MiB** reported, driver **617.42**
- Python AI environment: PyTorch **2.14.1+cu130**, Transformers **5.22.2**, safetensors **0.8.0**
- `torch.cuda.is_available()`: **true**, CUDA runtime **13.0**
- Preflight: **PASS**

## Scope and caveats
- This is a report **supplied by the project owner and reviewed**, not an independent remote execution on the Windows machine.
- The single skipped test was not diagnosed in this report; run pytest with `-rs` to record the skip reason.
- A CUDA availability check is not an actual SAM inference. SAM mask correctness, model-weights retrieval, VRAM use and isolated-worker behavior still require smoke tests.
- Manual GUI acceptance (calibration, geometric measurement, undo/redo, persistence, export and error handling) still requires execution and evidence.
- Security review and rights/license clearance remain pending; the repo **must remain private** until these are complete.
- Preserve the original application algorithms and measurement behavior; do not change scientific outcomes to make tests pass.

**Release decision: NO-GO for public visibility at this stage.**

See [WINDOWS_RELEASE_VERIFICATION.md](WINDOWS_RELEASE_VERIFICATION.md) and [OPEN_SOURCE_RELEASE_GATE.md](OPEN_SOURCE_RELEASE_GATE.md).

## Manual acceptance — owner confirmation (2026-11-17)

The project owner reported in chat that **all previously requested manual checks work** after performing the suggested checklist: image calibration, weld/thickness measurements, saving and reopening a test project, and SAM processing on CUDA. This is an **owner-reported PASS**, not an independently witnessed or instrumented run; screenshots, model ID, logs and test data were not provided. Independent reproduction remains a recommended release-quality improvement.

**Publication remains on hold pending documented ownership/third-party rights, final GPL-3.0 licensing decision, and security review.** No public-release approval has been granted.
