"""Prevent spreadsheet formula execution without changing scientific numeric results."""
import csv
import io
from weldvision.core import Project, Sample, csv_content, csv_safe_text, measurements_csv


def sample(name):
    return Sample(uid='a'*32, name=name, source_name='photo.jpg',
                  image_path='unused.jpg', dimensions=(100, 100),
                  measurements=[{'kind':'t1','points':[[0,0],[10,0]]}], mm_per_px=0.1)


def test_csv_formula_guard():
    for formula in ('=1+1', '+CMD', '-evil', '@SUM(1)', ' \t=HYPERLINK(1)'):
        assert csv_safe_text(formula) == "'" + formula
    for normal in ('ABC_03', 'ST 3-2', "'quoted", '', 'Spoiny 3727'):
        assert csv_safe_text(normal) == normal
    assert csv_safe_text(-10.25) == -10.25


def test_project_csv_does_not_change_source_model():
    s = sample('=HYPERLINK("https://example.org")')
    parsed = list(csv.DictReader(io.StringIO(
        csv_content(Project([s])).decode('utf-8-sig')), delimiter=';'))
    assert parsed[0]['probka'].startswith("'=")
    assert s.name.startswith('=')
    assert float(parsed[0]['skala_mm_px']) == 0.1


def test_measurements_csv_escapes_text_only():
    s = sample('-bad')
    parsed = list(csv.DictReader(io.StringIO(
        measurements_csv([s]).decode('utf-8-sig')), delimiter=';'))
    assert parsed[0]['probka'] == "'-bad"
    assert float(parsed[0]['wymiar_mm']) == 1.0
