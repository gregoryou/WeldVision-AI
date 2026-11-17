# WeldVision AI 3.2 - Open-source release gate (2026-11-17)

**Status: PRIVATE / NO-GO for public release.** This staging branch does not authorize publication.

## Verified
- Source snapshot: WeldVision AI 3.2, calibration and measurements, provided by owner.
- Python 3.13.5 compileall: PASS.
- pytest on Linux: **22 passed, 3 skipped** (2 PyQt6-related, 1 optional real-image test).
- Connected GitHub metadata verifies the repository is private.
- The source snapshot has no included research photos, project .weldproj files, or model weights; a heuristic token scan found no obvious literal secrets. These checks do not prove the absence of sensitive data.

## Blockers before changing repository visibility
1. Owner confirms original code and all third-party contributions may be redistributed, considering any course or university project rights.
2. Choose a compatible license; PyQt6 community edition is GPLv3 or commercial, so **GPL-3.0-only is proposed, NOT yet granted**.
3. Run Windows 11 PyQt6 GUI tests, manual calibration/geometric acceptance and real CUDA/SAM smoke tests on the user's computer.
4. Review untrusted ZIP/images, dependency vulnerabilities, CSV export formula injection, Git history and installer provenance.
5. Add genuine synthetic examples only, attribution and the full approved LICENSE text. Never commit unpublished research data.

## Scope of this branch
Documentation and release preparation only. Do not change weld geometry, segmentation, calculations, research results or underlying application logic.

References: https://www.riverbankcomputing.com/software/ ; https://doc.qt.io/qtforpython-6/ ; https://huggingface.co/facebook/sam-vit-base ; https://huggingface.co/facebook/sam-vit-large ; https://huggingface.co/facebook/sam-vit-huge

Release requires explicit owner approval of exact files, license and commit.