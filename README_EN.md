> **Open source:** original application source is licensed under GNU GPL-3.0-only. See [LICENSE](LICENSE), [AI-assisted development](AI_ASSISTED_DEVELOPMENT.md), and [third-party licensing](THIRD_PARTY_COMPONENTS.md).
>
> **Screenshot:** [WeldVision 3.2 in action](docs/screenshots/weldvision-ai-3.2.jpg); published with the image owner's permission, not licensed under the source-code GPL.

# WeldVision AI 3.2 — Research Software Overview

WeldVision AI is an experimental Windows desktop application for the analysis of weld macrographs, developed for research workflows.

## Current functionality

- Import and organize multiple macrograph images in one project.
- Calibrate pixel scale with two reference points and a known distance.
- Measure selected geometric distances: fillet weld throat **a**, plate thickness **t1/t2**, and arbitrary segments.
- Measure areas and estimate section-material mass per metre using operator-defined density.
- Segment selected regions via OpenCV GrabCut or optional Segment Anything (SAM).
- Revise masks manually, review and approve results, save projects and export CSV/image reports.

## Installation and testing

The application targets Windows 11 and Python 3.13. For details, consult the main [Polish README](README.md). `Install_Base.bat` installs the GUI and image-processing dependencies in a dedicated local virtual environment; GPU-based AI is optional. To run automated tests, install `pytest` and execute `python -m pytest -q tests` in the project directory.

## Research limitations

This is **research software**, not an independently certified metrology system. Results depend on calibration, the selected points/masks, image quality and operator review. The number of displayed decimal places is not an uncertainty statement. AI-generated segmentation should be independently verified. The application does not establish welding compliance or acceptance grades without separate, applicable criteria.

## Source-code and datasets

The repository intentionally does **not** contain laboratory photographs, patient/personal data, confidential reports, trained model weights, or `.weldproj` research projects. Avoid committing such files. The models referenced by code are obtained separately from their respective publishers.

## License status

The author has not yet selected a public open-source license. Until a license is formally added by the authorized rightsholder, **all rights are reserved**. Publishing this source code as open source requires a separate license and provenance review.
