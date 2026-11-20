# Security and data handling

Do not commit credentials, access tokens, `.env` files, private keys, confidential research photographs, original laboratory data, `.weldproj` projects, model checkpoints, or internal documents. The `.gitignore` file does not remove content already present in Git history.

The 3.5.0 source archive was checked for obvious literal tokens, private-key headers and private system paths, and passed Python syntax compilation. This is **not** a complete security audit. Full GUI tests and CUDA/SAM inference were not reproduced during this independent release preparation.

Do not open untrusted project archives without appropriate resource safeguards. Send security reports privately to the repository maintainer instead of posting exploits or sensitive details publicly.
