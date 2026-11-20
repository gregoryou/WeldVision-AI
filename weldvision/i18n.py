"""Small, dependency-free catalogue shared by the Qt application and worker."""
from functools import lru_cache
import json
import os
from pathlib import Path


def _normalise(language):
    return 'en' if language == 'en' else 'pl'


_language = _normalise(os.getenv('WELDVISION_LANGUAGE', 'pl'))


def set_language(language):
    global _language
    _language = _normalise(language)
    return _language


def language():
    return _language


@lru_cache(maxsize=1)
def _english():
    source = Path(__file__).with_name('locale') / 'en.json'
    return json.loads(source.read_text(encoding='utf-8'))


def tr(source):
    return _english().get(source, source) if _language == 'en' else source
