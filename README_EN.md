# WeldVision AI 3.5.0

## Author and contact

- **Author and project lead:** Sławomir Krajewski.
- **Academic affiliation:** West Pomeranian University of Technology in Szczecin, Poland.
- **Repository and source code:** https://github.com/gregoryou/WeldVision-AI
- **Contact, questions, bug reports and collaboration proposals:** https://github.com/gregoryou/WeldVision-AI/issues
- **Source-code license:** GNU GPL-3.0-only.

*Affiliation identifies the author’s academic institution. It does not indicate that the university publishes, sponsors or officially endorses the software.* No private phone number, home address or unconfirmed email address is published. Please use GitHub Issues for project contact.

[Polish documentation](README.md)

**License:** original application source: [GNU GPL-3.0-only](LICENSE); dependencies and SAM model weights remain separately licensed. [Third-party components](THIRD_PARTY_COMPONENTS.md) · [AI-assisted development](AI_ASSISTED_DEVELOPMENT.md) · [Security](SECURITY.md).

**Research limitations:** not certified metrology software. Operator review of segmentation and calibration is essential. **Legacy weld throat `a` measurements from version 3.2.x must be repeated** using the updated measurement methods.


WeldVision AI measures weld cross-sectional area, fillet weld throat thickness, plate thickness, and other geometric dimensions on macrographs. A .weldproj project stores images, calibration, masks, and annotations.

## Start on Windows

1. Extract the source archive into a separate folder. Install Python 3.13 and run `Install_Base.bat` the first time.
2. For SAM inference on a supported NVIDIA GPU, use `Install_AI_NVIDIA_CUDA.bat`. **Analysis → Check AI packages and CUDA** reports whether the worker can use the installed packages and GPU.
3. Run `Start_WeldVision_AI.bat`. Select **EN — English** in **O programie (About) → Język interfejsu (Interface language)**. Switching languages keeps the current project and unsaved changes.

The base application also runs without SAM. You can create a mask manually and make calibrated measurements. The SAM checkpoint is loaded separately from the source package.

## Workflow

| Step | What to do |
| --- | --- |
| **Calibration** | Pick a known length, or three adjacent intersections of a 10×10 mm grid in the plane of the section. |
| **Mask settings** | Draw a region of interest (ROI) around the weld. Mark known weld regions with **FG +** and background with **BG −**. Select **Next → Analysis** when ready. |
| **Analysis** | Select **Create AI mask — current sample**. New projects default to SAM Huge. Inspect the filled mask and correct it with the add/erase brushes or the polygon tool. |
| **Results** | Review the section area, estimated volume per metre, and mass per metre. Export the results to Excel or CSV. |
| **Measurements** | Measure the throat, plate thickness, radius, or angle. Add comments and scale bars, and export images as PNG, JPEG, BMP, or TIFF. |

**Approve section area** records that you reviewed the mask used to compute the area. The app reports a preliminary area as soon as the mask and calibration are available. Batch analysis skips approved samples. Editing the mask returns the sample to review and retains the raw SAM mask. A manually drawn polygon can also serve as the mask. Right-click to finish and fill it.

## Measure a fillet weld throat

Open **Measurements → Measure throat a — step by step**.

- **Straight face — six clicks.** Pick two points on each plate surface on the weld side, then two on the straight weld face. The app finds theoretical corner **O** and the perpendicular distance to the face. It reports `a = r` when the triangle check passes.
- **Concave or convex face — trace contour.** Pick **O**, the first weld toe, successive points along the face, and the second toe. Right-click to finish. Include the deepest point of a concave face.
- To annotate an image, select **Insert comment**, click the label location, and type. Double-click the comment to edit it.

## Development and tests

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.venv\Scripts\python.exe weldvision_ai.py
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe -m pytest -q -ra
```

Tests cover calibration, measurement geometry, annotations, project persistence, image exports, and the SAM request and mask-review workflow. Tests can validate the workflow with a deterministic mask without downloading a model checkpoint.
