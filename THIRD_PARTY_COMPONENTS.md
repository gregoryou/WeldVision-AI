# Third-party components — source-code release

The distribution contains Python source code, not bundled package wheels or SAM model checkpoints. The application source is released under GPL-3.0-only, as in the existing GitHub repository.

| Component | License / consideration |
| --- | --- |
| PyQt6 | GPL-3.0 community edition or separately purchased commercial license; maintain the GPL-compatible combination |
| Qt runtime libraries | Separate Qt notice/redistribution obligations apply to packaged binaries |
| OpenCV (`opencv-python`) | Apache-2.0 |
| NumPy | BSD-3-Clause and additional notices from upstream |
| Pillow | HPND / historical MIT-CMU terms; verify installed version's notices |
| PyTorch and torchvision | Upstream individual terms |
| Transformers, safetensors, huggingface-hub | Upstream individual terms |
| `facebook/sam-vit-base`, `large`, `huge` | Model-specific upstream licenses; weights are downloaded separately, not distributed here |

Source-only publication avoids bundling large third-party binaries, but does not remove the obligation to honor upstream terms. Verify all binary and model license obligations before publishing a standalone EXE or model weights.
