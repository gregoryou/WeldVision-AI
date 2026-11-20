"""Visual properties. Measurement values never depend on this data."""
from __future__ import annotations
from .i18n import language, tr

import math
import re

DEFAULT_STYLE = {
    'line_color': '#46ebff', 'line_width': 2., 'line_pattern': 'solid', 'line_opacity': 100,
    'line_cap': 'round', 'arrows': 'none', 'arrow_size': 10., 'controls': True,
    'center': 'cross', 'center_size': 5., 'tick': 6., 'font_family': 'Arial',
    'font_pt': 10.5, 'text_color': '#46ebff', 'bold': False, 'italic': False,
    'position': 'above', 'alignment': 'anchor', 'label_gap': 8., 'label_x': 0., 'label_y': 0.,
    'decimals': -1, 'show_unit': True, 'signature': 'auto', 'custom_label': '',
    'background': 'none', 'background_color': '#ffffff', 'background_opacity': 100,
    'padding': 4., 'corner': 3., 'border_color': '#303030', 'border_width': 0.,
    'border_opacity': 100,
}

PRESETS = {
    'Naukowy': dict(DEFAULT_STYLE, line_color='#222222', text_color='#222222', line_width=1.3,
                    font_pt=9.5, background='white', background_opacity=94, border_width=.7,
                    center_size=4., decimals=2),
    'Techniczny': dict(DEFAULT_STYLE, line_color='#f5fafc', text_color='#ffffff',
                       font_pt=13., arrows='both', line_width=2.5, arrow_size=13., bold=True),
    'Prezentacyjny': dict(DEFAULT_STYLE, line_color='#ffd24c', text_color='#ffe57b',
                          font_pt=17., bold=True, line_width=4., center_size=7.,
                          background='black', background_opacity=75, padding=7.),
}

OPTIONS = {
    'line_pattern': {'solid': 'Ciągła', 'dash': 'Przerywana', 'dot': 'Kropkowana',
                     'dashdot': 'Kreska–kropka'},
    'line_cap': {'flat': 'Płaskie', 'square': 'Kwadratowe', 'round': 'Okrągłe'},
    'arrows': {'none': 'Brak', 'start': 'Na początku', 'end': 'Na końcu', 'both': 'Obie'},
    'center': {'none': 'Brak', 'cross': 'Krzyżyk', 'dot': 'Pełny punkt', 'ring': 'Okrąg',
               'square': 'Kwadrat'},
    'position': {'above': 'Nad obiektem', 'below': 'Pod obiektem',
                 'left': 'Z lewej', 'right': 'Z prawej'},
    'alignment': {'anchor': 'Automatyczne', 'left': 'Do lewej', 'center': 'Do środka',
                  'right': 'Do prawej'},
    'signature': {'auto': 'Automatyczny', 'custom': 'Własny', 'none': 'Ukryty'},
    'background': {'none': 'Bez tła', 'white': 'Białe', 'black': 'Czarne', 'custom': 'Własny kolor'}
}

NUMBERS = {
    'line_width': (.5, 24), 'line_opacity': (0, 100), 'arrow_size': (2, 120),
    'center_size': (1, 80), 'tick': (1, 100), 'font_pt': (4, 144), 'label_gap': (0, 300),
    'label_x': (-100000, 100000), 'label_y': (-100000, 100000), 'decimals': (-1, 6),
    'background_opacity': (0, 100), 'padding': (0, 100), 'corner': (0, 100),
    'border_width': (0, 24), 'border_opacity': (0, 100)
}


def default_style(kind):
    style = dict(DEFAULT_STYLE)
    if kind == 'scale':
        style.update(line_color='#ffffff', text_color='#ffffff', alignment='center')
    return style


def normalize_style(raw, kind='line'):
    if not isinstance(raw, dict):
        raise ValueError(tr('Nieprawidłowy styl obiektu.'))
    result = default_style(kind)
    for key, default in result.items():
        value = raw.get(key, default)
        if key.endswith('_color'):
            if not isinstance(value, str) or not re.fullmatch(r'#[a-fA-F0-9]{6}', value):
                raise ValueError(tr('Nieprawidłowy kolor.'))
        elif key in OPTIONS:
            if value not in OPTIONS[key]:
                raise ValueError(tr('Nieprawidłowa opcja stylu.'))
        elif key in NUMBERS:
            lo, hi = NUMBERS[key]
            value = int(value) if key in ('decimals','line_opacity','background_opacity','border_opacity') else float(value)
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(tr('Wartość stylu poza zakresem.'))
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                raise ValueError(tr('Nieprawidłowa wartość stylu.'))
        else:
            value = str(value)[:(120 if key == 'font_family' else 500)]
        result[key] = value
    return result


def formatting_style(style):
    """Copy appearance without copying an object's own words or location."""
    return {k: v for k, v in style.items()
            if k not in ('custom_label', 'signature', 'label_x', 'label_y')}


def number(value, style, auto_decimals=2):
    precision = style['decimals']
    text = (f'{value:.{precision}f}' if precision >= 0 else
            f'{value:g}' if auto_decimals < 0 else f'{value:.{auto_decimals}f}')
    return text if language() == 'en' else text.replace('.', ',')


def numeric_label(value, unit, style, symbol='', auto_decimals=2):
    if value is None:
        return ''
    suffix = ((' ' if unit == 'mm' else '') + unit) if style['show_unit'] else ''
    return (f'{symbol} = ' if symbol else '') + number(value, style, auto_decimals) + suffix
