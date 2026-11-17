# WeldVision AI 3.2 — Open-source source-release review (2026-11-17)

**Decision:** Source-only publication under GPL-3.0-only is authorized by the project maintainer. The GitHub screenshot is to be uploaded separately with path redaction before changing repository visibility. No research dataset or standalone executable is included.

## Reviewed evidence

- Maintainer confirmed: original research-software idea, functional requirements and hands-on scientific testing; coding assistance by ChatGPT/AI; no knowingly copied third-party/university-owned program code.
- Formal rights guarantee: **not independently verified**. See [AI_ASSISTED_DEVELOPMENT.md](AI_ASSISTED_DEVELOPMENT.md).
- Full text of **GNU GPL version 3, no later-version option** is provided in [LICENSE](LICENSE), compatible with the community edition of PyQt6 used in the app.
- Third-party dependencies are installed separately and keep their own licenses. No SAM weights are redistributed. See [THIRD_PARTY_COMPONENTS.md](THIRD_PARTY_COMPONENTS.md).
- Owner-supplied Windows 11 report: **26 passed, 1 skipped**, PyQt6 and CUDA detected. Owner confirmed GUI/macrograph measurements and SAM Huge CUDA in actual use. These are user-provided results, not independently observed remote execution.
- Linux offline regressions after CSV formula-injection fix: **25 passed, 3 skipped** (Qt unavailable, original research photos absent).
- Automated GitHub Actions perform a core Linux test suite and Windows PyQt6 GUI tests.
- Security and supply chain risks are disclosed in [RELEASE_SECURITY_REVIEW_2026-11-17.md](RELEASE_SECURITY_REVIEW_2026-11-17.md). In particular, do not load untrusted project archives without adequate resources.

## Publication scope

**Public:** Python source code, installers/scripts, tests, GPL license, AI contribution disclosure, dependency notices, one owner-approved screenshot with local user paths redacted.

**Not published:** original source research photos, raw measurements, project archives, credentials, model weight files, confidential laboratory materials.

The screenshot is included under its owner's express permission for this repository and is **not automatically GPL-licensed**.

## Limitations

This checklist supports a reasonable initial source-only release. It does **not** guarantee compliance with every jurisdiction's intellectual-property law, certify metrological accuracy, or constitute an external security penetration test or legal opinion. Future packaged binaries require a separate license and redistribution audit.
