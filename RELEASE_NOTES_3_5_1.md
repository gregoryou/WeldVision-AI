# WeldVision AI 3.5.1 — poprawka bezpieczeństwa i CI / Security and CI hotfix

## PL
- Usunięto regresję ochrony przed formułami w eksporcie CSV: zabezpieczono tekstowe pola w zestawieniu próbek, pomiarach liniowych i eksporcie zbiorczym, zachowując nienaruszone wartości liczbowe i oryginalne dane projektów.
- Uzupełniono biblioteki systemowe Linux CI potrzebne PyQt6 (w tym libEGL.so.1).
- Dodano testy regresyjne ochrony pól CSV. Nie zmieniono algorytmów pomiarowych, segmentacji SAM Huge ani schematu zapisu projektów.

## EN
- Restored spreadsheet formula-injection protections for CSV text fields across project summaries, linear measurements, and batch export. Numeric values and original project metadata are unchanged.
- Added the missing system libraries required by PyQt6 in Linux CI, including libEGL.so.1.
- Added CSV security regression tests. No changes to measurement algorithms, SAM Huge segmentation, or project schema.

GitHub Actions checks validate the CPU/GUI test suite on CI runners; actual CUDA/SAM Huge GPU inference remains outside the CI scope.
