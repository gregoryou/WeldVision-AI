"""Regression tests for CSV formula mitigation (3.5.1)."""
import csv
import io

from weldvision.core import Project, Sample, csv_content, csv_safe_text, measurements_csv


def _sample(name):
    return Sample(uid="a" * 32, name=name, source_name="photo.jpg",
                  image_path="unused.jpg", dimensions=(100, 100),
                  measurements=[{"kind": "t1", "points": [[0, 0], [10, 0]]}],
                  mm_per_px=0.1)


def test_dangerous_text_prefixes_escaped_without_mutating_project():
    for name in ("=1+1", "+CMD", "-evil", "@SUM(1)", " \t=HYPERLINK(1)", "\n+X"):
        sample = _sample(name)
        row = next(csv.DictReader(io.StringIO(
            csv_content(Project([sample])).decode("utf-8-sig")), delimiter=";"))
        assert row["probka"] == "'" + name
        assert sample.name == name
        measurement = next(csv.DictReader(io.StringIO(
            measurements_csv([sample]).decode("utf-8-sig")), delimiter=";"))
        assert measurement["probka"] == "'" + name
        assert float(measurement["wymiar_mm"]) == 1.0
        assert float(row["skala_mm_px"]) == 0.1


def test_regular_text_and_numerics_unchanged():
    for normal in ("ABC_03", "ST 3-2", "'quoted", "", "Spoiny 3727"):
        assert csv_safe_text(normal) == normal
    assert csv_safe_text(-10.25) == -10.25
    assert csv_safe_text(3.4) == 3.4
    assert csv_safe_text(None) is None
