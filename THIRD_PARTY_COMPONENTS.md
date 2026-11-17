# Third-party component licenses (source-code release)

The distribution is of the **WeldVision AI source code**, not pre-installed wheels, proprietary weight files, or a standalone executable. The repository's original source code is licensed under **GPL-3.0-only**; the following items keep their separate terms.

| Component | License indicated by source/vendor | Notes |
| --- | --- | --- |
| PyQt6 | GPL-3.0-only community edition, or separate commercial option | GPL-3.0-only chosen for this project's original code |
| Qt libraries | Qt licenses as bundled with the installed PyQt6-Qt6 package | Binary redistribution requires confirming Qt notices and licenses |
| opencv-python | Apache-2.0 | Installed separately |
| NumPy | BSD-3-Clause / MIT / additional permissive notices | Installed separately |
| Pillow | MIT-CMU | Installed separately |
| PyTorch, torchvision, Transformers, safetensors, huggingface-hub | Separate upstream package licenses | Installed separately; do not assume every transitive license matches |
| facebook/sam-vit-base, large, huge | Apache-2.0 per Hugging Face model repositories | Model weights fetched separately; not included |

**References (checked 2026-11-17):**
- https://www.riverbankcomputing.com/software/
- https://pypi.org/project/PyQt6/6.12.0/
- https://huggingface.co/facebook/sam-vit-base
- https://huggingface.co/facebook/sam-vit-large
- https://huggingface.co/facebook/sam-vit-huge

The project does not relicense third-party dependencies or model weights. For a future Windows executable, perform a new binary-distribution notice/SBOM review.
