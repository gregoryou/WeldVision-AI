# WeldVision AI 3.5.0 — publication review (20 November 2026)

## Scope and findings

Source: user-supplied archive `WeldVision_AI_3_5_0_SAM_HUGE_PL_EN(1).zip`.

- 46 ZIP entries in the original source package, containing Python, Windows launchers, tests and PL/EN documentation; no raw photos, project files, SAM checkpoints or packaged EXE.
- Python syntax: **passed** using Python 3.13.5 (`compileall`).
- Static scan: **no obvious** literal API tokens, SSH/private key blocks, or identifiable private user paths. This is not an exhaustive proof of security.
- Local test environment: PyQt6 unavailable and cannot be installed because external package retrieval is unavailable. A partial core run yielded **36 passed, 1 skipped and 3 failures caused by missing PyQt6**; full suite collection was blocked by 3 PyQt6 import errors. These are **environment limitations, not established code regressions**.
- The supplied release notes independently assert **74 passed, 1 skipped** on Windows/PyQt6. These results were **not reproduced** for this review; real SAM Huge GPU inference was also not reproduced.
- Publication only includes code, scripts, documentation and tests. It does not contain downloaded model weights or research photos.

## Changes in publication packaging

- Kept the pre-existing repository's GPL-3.0-only terms and strong `.gitignore` exclusions.
- Updated outdated installer display from 3.2 to 3.5.0 and clarified the fallback without AI. **No computation, AI or GUI implementation was changed**.
- Linked README files to license, provenance, security and third-party notices, and warned that legacy 3.2.x throat measurements require re-measurement.
- Historical review notes and the approved older 3.2 screenshot already on GitHub are intended to be preserved as archival records.

## After push

Verify the repository's GitHub Actions Windows/Linux results, then test SAM Huge CUDA with a real macrograph and review measurement correctness before describing the release as validated for research production use. The GitHub Release asset is source code, not a prebuilt installer or bundled model.
