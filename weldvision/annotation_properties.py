"""Live property panel for measurement annotations."""
from __future__ import annotations
from .i18n import tr

import math

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFontDatabase
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget)

from .annotation_style import NUMBERS, OPTIONS
from .geometry import (DERIVED, LINES, TYPES, add, mul, norm, sub, to_mm)


class Properties(QGroupBox):
    def __init__(self, editor, parent):
        super().__init__(tr('Właściwości obiektu'), parent)
        self.editor = editor
        self.uid = None
        self.loading = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.flush)
        self.editor.flush_pending = self.flush
        layout = QVBoxLayout(self)
        self.failure = QLabel()
        self.failure.setWordWrap(True)
        layout.addWidget(self.failure)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.widgets = {}
        fields = {
            tr('Tekst'): [('font_family', tr('Czcionka')), ('font_pt', tr('Wielkość [pt]')),
                      ('text_color', tr('Kolor tekstu')), ('bold', tr('Pogrubienie')), ('italic', tr('Kursywa')),
                      ('position', tr('Pozycja podpisu')), ('alignment', tr('Wyrównanie')),
                      ('label_gap', tr('Odstęp [px]')), ('label_x', tr('Przesunięcie X [px]')),
                      ('label_y', tr('Przesunięcie Y [px]')), ('decimals', tr('Miejsca po przecinku')),
                      ('show_unit', tr('Pokaż jednostkę')), ('signature', tr('Podpis')),
                      ('custom_label', tr('Treść podpisu'))],
            tr('Tło'): [('background', tr('Tło podpisu')), ('background_color', tr('Własny kolor tła')),
                    ('background_opacity', tr('Krycie tła [%]')), ('padding', tr('Margines [px]')),
                    ('corner', tr('Promień rogów [px]')), ('border_color', tr('Kolor ramki')),
                    ('border_width', tr('Grubość ramki [px]')), ('border_opacity', tr('Krycie ramki [%]'))],
            tr('Linia'): [('line_color', tr('Kolor linii / obwodu')), ('line_width', tr('Grubość [px]')),
                      ('line_pattern', tr('Styl linii')), ('line_opacity', 'Krycie linii [%]'),
                      ('line_cap', tr('Zakończenia')), ('arrows', tr('Strzałki')), ('arrow_size', tr('Strzałka [px]')),
                      ('controls', tr('Punkty kontrolne')), ('center', tr('Znacznik środka')),
                      ('center_size', tr('Znacznik [px]')), ('tick', tr('Kreska skali [px]'))]
        }
        for name, rows in fields.items():
            panel = QWidget()
            form = QFormLayout(panel)
            for key, label in rows:
                widget, get, put = self._field(key)
                form.addRow(label, widget)
                self.widgets[key] = widget, get, put
            self.tabs.addTab(panel, name)
        panel = QWidget()
        form = QFormLayout(panel)
        self.name = QLineEdit()
        self.name.setMaxLength(160)
        self.name.textEdited.connect(lambda: self.change('name', self.name.text()))
        form.addRow(tr('Nazwa'), self.name)
        self.visible = QCheckBox()
        self.visible.toggled.connect(lambda state: self.change('visible', state))
        form.addRow(tr('Widoczny'), self.visible)
        self.length = QDoubleSpinBox()
        self.length.setDecimals(4)
        self.length.setRange(.0001, 1000000.)
        self.length.setKeyboardTracking(False)
        self.length.valueChanged.connect(lambda value: self.change('metric', value))
        self.length_label = QLabel(tr('Wymiar [mm]'))
        form.addRow(self.length_label, self.length)
        self.orientation = QDoubleSpinBox()
        self.orientation.setDecimals(2)
        self.orientation.setRange(-360., 360.)
        self.orientation.setSuffix('°')
        self.orientation.valueChanged.connect(lambda value: self.change('angle_deg', value))
        self.orientation_label = QLabel(tr('Kąt skali na zdjęciu'))
        form.addRow(self.orientation_label, self.orientation)
        self.radius = QCheckBox()
        self.radius.toggled.connect(lambda state: self.change('show_radius', state))
        self.radius_label = QLabel(tr('Pokaż promień r'))
        form.addRow(self.radius_label, self.radius)
        self.diameter = QCheckBox()
        self.diameter.toggled.connect(lambda state: self.change('diameter', state))
        self.diameter_label = QLabel(tr('Pokaż średnicę d'))
        form.addRow(self.diameter_label, self.diameter)
        self.tabs.addTab(panel, tr('Geometria'))
        self.hide()

    def _field(self, key):
        def changed():
            self.change(key, get())
        if key in OPTIONS:
            widget = QComboBox()
            for value, name in OPTIONS[key].items():
                widget.addItem(tr(name), value)
            get = widget.currentData
            def put(v):
                widget.setCurrentIndex(widget.findData(v))
            widget.currentIndexChanged.connect(changed)
        elif key.endswith('_color'):
            widget = QPushButton()
            get = widget.text
            def put(v):
                widget.setText(v)
                ink = '#ffffff' if QColor(v).lightness() < 120 else '#111111'
                widget.setStyleSheet(f'background-color:{v}; color:{ink};')
            def choose():
                previous = get()
                dialog = QColorDialog(QColor(previous), self)
                def preview(color):
                    put(color.name())
                    self.change(key, get(), staged=True)
                dialog.currentColorChanged.connect(preview)
                if dialog.exec():
                    self.change(key, get())
                else:
                    put(previous)
                    self.change(key, previous)
            widget.clicked.connect(choose)
        elif key in NUMBERS:
            lo, hi = NUMBERS[key]
            widget = QSpinBox() if key == 'decimals' or key.endswith('_opacity') else QDoubleSpinBox()
            widget.setRange(lo, hi)
            if key == 'decimals':
                widget.setSpecialValueText('Auto')
            if isinstance(widget, QDoubleSpinBox):
                widget.setDecimals(2)
                widget.setSingleStep(.5)
            get, put = widget.value, widget.setValue
            widget.valueChanged.connect(changed)
        elif key in ('bold', 'italic', 'show_unit', 'controls'):
            widget = QCheckBox()
            get, put = widget.isChecked, widget.setChecked
            widget.toggled.connect(changed)
        elif key == 'font_family':
            widget = QComboBox()
            widget.setEditable(True)
            widget.setMaxVisibleItems(16)
            widget.setMinimumContentsLength(12)
            widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            fonts = ('Arial','Calibri','Times New Roman','Segoe UI')
            widget.addItems([*fonts, *[f for f in QFontDatabase.families() if f not in fonts]])
            get, put = widget.currentText, widget.setCurrentText
            widget.currentTextChanged.connect(changed)
        else:
            widget = QLineEdit()
            widget.setMaxLength(500)
            get, put = widget.text, widget.setText
            widget.textEdited.connect(changed)
        widget.setObjectName(f'annotation_{key}')
        return widget, get, put

    def select(self, uid, refresh=False):
        if self.uid == uid and not refresh:
            return
        self.flush()
        item = self.editor.item(uid)
        self.uid = uid if item else None
        self.setVisible(item is not None)
        if not item:
            return
        self.loading = True
        try:
            style = item['style']
            for key, (_, _, put) in self.widgets.items():
                put(style[key])
            default_name = TYPES[item['kind']]
            self.name.setText(tr(default_name) if item['name'] == default_name else item['name'])
            self.visible.setChecked(item['visible'])
            kind = item['kind']
            self.orientation.setVisible(kind == 'scale')
            self.orientation_label.setVisible(kind == 'scale')
            self.orientation.setValue(item.get('angle_deg', 0))
            is_circle = kind in ('circle','throat')
            for control in (self.radius, self.radius_label, self.diameter, self.diameter_label):
                control.setVisible(is_circle)
            self.radius.setChecked(item['show_radius'])
            self.diameter.setChecked(item['diameter'])
            interpolated = self.editor.scene()[uid]
            allowed = (kind in (LINES | {'circle','scale','throat','t1','t2','distance'}))
            self.length_label.setVisible(allowed)
            self.length.setVisible(allowed)
            value = interpolated.radius if is_circle else interpolated.value
            self.length.setEnabled(allowed and value is not None and self.editor.matrix is not None)
            self.length.setValue(value or item.get('length_mm', 0))
            self.length_label.setText(tr('Promień [mm]') if is_circle else tr('Długość [mm]'))
            self.failure.setText(interpolated.status)
        finally:
            self.loading = False

    def change(self, key, value, staged=False):
        if self.loading or not self.uid:
            return
        obj = self.editor.draft or self.editor.item(self.uid)
        if not obj:
            return
        updated = dict(obj)
        try:
            if key == 'metric':
                updated = self.resize_metric_geometry(obj, value)
            elif key in obj['style']:
                updated['style'] = dict(obj['style'], **{key: value})
            else:
                updated[key] = value
        except ValueError as exc:
            self.failure.setText(str(exc))
            return
        self.editor.draft = updated
        self.editor.canvas.update()
        if staged:
            self.timer.stop()
        else:
            self.timer.start()

    def flush(self):
        self.timer.stop()
        updated = self.editor.draft
        if updated is None:
            return
        self.editor.draft = None
        try:
            self.editor.style(updated['id'], **{k: v for k, v in updated.items() if k != 'id'})
        except ValueError as exc:
            self.failure.setText(str(exc))
        self.editor.canvas.update()

    def resize_metric_geometry(self, item, value):
        if not math.isfinite(value) or value <= 0 or self.editor.matrix is None:
            raise ValueError(tr('Podaj dodatni wymiar na skalibrowanym zdjęciu.'))
        kind = item['kind']
        r = self.editor.scene()[item['id']]
        if kind == 'scale':
            return dict(item, length_mm=value)
        if kind in ('circle', 'throat'):
            start, end = r.handles[:2]
        elif r.line:
            start, end = r.line
        else:
            start, end = r.paths[0]
        vector = sub(end, start)
        length = norm(to_mm(vector, self.editor.matrix))
        if length <= 1e-9:
            raise ValueError(tr('Obiekt nie ma dodatniego wymiaru.'))
        vector = mul(vector, value/length)
        end = add(start, vector)
        h, w = self.editor.shape
        if not (0 <= end[0] < w and 0 <= end[1] < h):
            raise ValueError(tr('Po zmianie wymiaru punkt uchwytu znalazłby się poza zdjęciem.'))
        if kind == 'throat':
            return dict(item, method='manual', points=[item['points'][0], list(vector)])
        return dict(item, points=[list(start), list(end)])
