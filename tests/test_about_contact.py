"""Source-level regression tests for public author information and bilingual links."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_public_contact_and_attribution_are_present():
    gui = (ROOT / 'weldvision/gui.py').read_text(encoding='utf-8')
    assert 'def _tab_about(self):' in gui
    assert "author = QLabel('Sławomir Krajewski')" in gui
    assert 'github.com/gregoryou/WeldVision-AI/issues' in gui
    assert 'repo.setOpenExternalLinks(True)' in gui
    assert 'support.setOpenExternalLinks(True)' in gui
    assert 'GPL-3.0-only' in gui
    assert '@zut.edu.pl' not in gui


def test_localization_is_complete_for_about_page():
    en = json.loads((ROOT / 'weldvision/locale/en.json').read_text(encoding='utf-8'))
    assert en['Autor i kontakt'] == 'Author and contact'
    assert en['Afiliacja:'] == 'Affiliation:'
    assert en['Kontakt / zgłaszanie błędów:'] == 'Contact / report issues:'
    assert 'officially endorses' in en['Afiliacja wskazuje miejsce pracy naukowej autora i nie oznacza, że uczelnia jest wydawcą, sponsorem lub oficjalnym podmiotem odpowiedzialnym za program.']


def test_both_readmes_contain_author_and_contact():
    for path in (ROOT / 'README.md', ROOT / 'README_EN.md'):
        content = path.read_text(encoding='utf-8')
        assert 'Sławomir Krajewski' in content
        assert 'https://github.com/gregoryou/WeldVision-AI/issues' in content
        assert 'GNU GPL-3.0-only' in content
