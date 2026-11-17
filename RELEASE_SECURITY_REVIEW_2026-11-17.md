# Source publication security review — 2026-11-17

**Scope:** WeldVision AI 3.2 source-code-only release; originally 34 GitHub files. No original research photos, `.weldproj` projects or model weight files in the original code archive. A heuristic secret/key scan found no obvious hardcoded private keys or tokens. These are limited checks, not a guarantee of total security or legal compliance.

## Addressed on release branch
- **S-01 Spreadsheet formula injection in CSV exports:** neutralized potentially executable prefixes in untrusted *text* values when writing CSV. Measurement values are not rewritten. Added tests for suspicious sample names and numerical preservation.

## Known residual risks and usage guidance
- **S-02 Untrusted project archive decompression:** `_zip_checked()` rejects duplicate names, enforces member/count/total limits, and checks CRC, but still permits relatively large uncompressed archives. Avoid opening `.weldproj` files from unknown senders until resource consumption limits are further hardened.
- **S-03 Third-party dependency vulnerabilities:** packages are downloaded at installation; no fixed lockfile or full SBOM scan in this review. Keep dependencies updated from official sources and check licensing before bundling binaries.
- **S-04 Research privacy:** projects bundle original research images; never commit project data. The published demonstration screenshot contains a single image the owner expressly permitted to share, with local user paths redacted.
- **S-05 Remote model supply-chain:** SAM weights are obtained from Hugging Face under their own licenses; users should verify model IDs and origin.
- **S-06 Scientific measurement uncertainty:** three decimal places do not imply 0.001 mm accuracy. User controls calibration and must verify segmentation and dimensions.

**Review scope:** This is a reasonable source release readiness review, **not a legal opinion**, complete penetration test, or certification of scientific measurement accuracy. Please report vulnerabilities privately to the maintainer.
