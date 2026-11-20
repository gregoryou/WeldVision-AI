"""Qt controls for geometry, object properties and photograph export."""
from __future__ import annotations
from .i18n import tr

import json
from copy import deepcopy
from pathlib import Path

from PyQt6.QtCore import Qt, QItemSelectionModel, QSettings, QSignalBlocker
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGridLayout, QGroupBox, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QInputDialog, QMenu, QMessageBox, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout)

from PyQt6.QtGui import QImage, QPixmap

from .annotation_properties import Properties
from .annotation_style import PRESETS, default_style, formatting_style, normalize_style
from .geometry import METHODS, TYPES, Scene, caption, promote_measurement
from .photo_annotations import export_photo, native_photo


class GeometryPanel(QGroupBox):
    def __init__(self, window):
        super().__init__(tr('Obiekty pomiarowe'))
        self.window = window
        self.canvas = window.canvas
        self.editor = self.canvas.geometry
        self.settings = QSettings('WeldVisionAI', 'AnnotationStyles')
        self.user_styles = self._load_styles()
        self.clipboard = None
        self.editor.new_style = self._new_style
        self.editor.comment_text = self._comment_text
        self._rows = []
        self._multiple = set()
        self._table_event = False
        layout = QVBoxLayout(self)
        tools = QGridLayout()
        self.buttons = {}

        def button(key, title, handler, row, col, span=1):
            control = QPushButton(title)
            control.clicked.connect(handler)
            tools.addWidget(control, row, col, 1, span)
            self.buttons[key] = control

        button('select', tr('Zaznacz / przeciągnij'), lambda: self.start('select'), 0, 0)
        button('pan', tr('Przesuwaj obraz'), self.pan, 0, 1)
        button('circle', tr('Wstaw okrąg / Pomiar r'), lambda: self.start('circle'), 1, 0, 2)
        button('throat', tr('Zmierz gardziel a — krok po kroku'), self.throat, 2, 0, 2)
        button('scale', tr('Wstaw skalę'), self.scale, 3, 0, 2)
        self.line_tool = QComboBox()
        self.line_tool.setMinimumContentsLength(14)
        self.line_tool.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        for key in ('line', 'horizontal', 'vertical', 'infinite', 'parallel', 'perpendicular',
                    'polyline', 'angle', 'intersection', 'point', 'comment',
                    't1', 't2', 'distance', 'a_contour'):
            self.line_tool.addItem(tr(TYPES[key]), key)
        tools.addWidget(self.line_tool, 4, 0)
        button('line', tr('Wstaw'), lambda: self.start(self.line_tool.currentData()), 4, 1)
        button('comment', tr('Wstaw komentarz'), lambda: self.start('comment'), 5, 0, 2)
        self.snap = QCheckBox(tr('Przyciąganie do geometrii'))
        self.snap.setChecked(True)
        self.snap.toggled.connect(self._set_snap)
        tools.addWidget(self.snap, 6, 0, 1, 2)
        layout.addLayout(tools)
        self.mode = QLabel(tr('Zaznaczanie'))
        self.mode.setWordWrap(True)
        self.mode.setStyleSheet('font-weight:600; padding:4px;')
        layout.addWidget(self.mode)
        self.table = QTableWidget(0, 5)
        self.table.setObjectName('geometry_object_table')
        self.table.setHorizontalHeaderLabels([tr('Nr'), tr('Typ obiektu'), tr('Nazwa'), tr('Wymiar'), tr('Widoczność')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((32, 79, 75, 95, 73)):
            self.table.setColumnWidth(column, width)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(145)
        self.table.itemSelectionChanged.connect(self._selected_row)
        self.table.cellDoubleClicked.connect(lambda *args: self.edit())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context)
        layout.addWidget(self.table)
        tools = QGridLayout()
        button('edit', tr('Edytuj / nazwa / kolor'), self.edit, 0, 0)
        button('visible', tr('Ukryj / pokaż'), self.visibility, 0, 1)
        button('copy', tr('Kopiuj'), self.copy, 1, 0)
        button('delete', tr('Usuń'), self.delete, 1, 1)
        button('undo', tr('Cofnij'), self.canvas.undo, 2, 0)
        button('redo', tr('Ponów'), self.canvas.redo, 2, 1)
        button('clear', tr('Wyczyść oznaczenia'), self.clear, 3, 0, 2)
        button('export', tr('Eksportuj fotografię'), self.export, 4, 0, 2)
        layout.addLayout(tools)
        self.canvas.geometry_state.connect(self.mode.setText)
        self.canvas.geometry_selected.connect(self._selected_canvas)
        self.canvas.geometry_properties.connect(self.open_properties)
        self.canvas.geometry_context.connect(self.context)
        self.properties = Properties(self.editor, self)
        layout.addWidget(self.properties)
        self.presets = QComboBox()
        self._refresh_presets()
        styles = QFormLayout()
        styles.addRow(tr('Styl pomiarowy'), self.presets)
        actions = QPushButton(tr('Opcje stylu'))
        menu = QMenu(actions)
        menu.addAction(tr('Zastosuj do zaznaczonych'), self.apply_selected)
        menu.addAction(tr('Zastosuj do całej serii'), self.apply_series)
        menu.addAction(tr('Zapisz wygląd obiektu jako styl…'), self.save_style)
        menu.addAction(tr('Ustaw wybrany jako domyślny'), self.set_default)
        menu.addAction(tr('Przywróć domyślny wygląd programu'), self.clear_default)
        menu.addSeparator()
        menu.addAction(tr('Kopiuj styl obiektu'), self.copy_style)
        menu.addAction(tr('Wklej styl obiektu'), self.paste_style)
        actions.setMenu(menu)
        styles.addRow(actions)
        layout.addLayout(styles)

    @staticmethod
    def _display_name(item):
        default = TYPES[item['kind']]
        return tr(default) if item['name'] == default else item['name']

    def _set_snap(self, checked):
        self.editor.snap = checked

    def enabled(self):
        return bool(self.window._sample()) and not (
            self.window.process and self.window.process_kind == 'ai')

    def start(self, kind, **kwargs):
        if self.enabled():
            self.editor.start(kind, **kwargs)

    def pan(self):
        self.properties.flush()
        self.canvas.set_mode(self.canvas.PAN)
        self.mode.setText(tr('Przesuwanie obrazu — przeciągnij lewym przyciskiem myszy.'))

    def _dialog(self, title):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        form = QFormLayout(dialog)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        return dialog, form, buttons

    def throat(self):
        dialog, form, buttons = self._dialog(tr('Pomiar gardzieli a spoiny pachwinowej'))
        method = QComboBox()
        method.addItem(tr('Proste lico — sześć kliknięć'), 'guided_throat')
        method.addItem(tr('Wklęsłe lub wypukłe lico — obrys'), 'a_contour')
        for key, title in METHODS.items():
            method.addItem(tr('Z istniejących prowadnic — {0}').format(tr(title)), key)
        hint = QLabel()
        hint.setWordWrap(True)
        instructions = {
            'guided_throat': tr('Kliknij dwa punkty na powierzchni pierwszej blachy, dwa na powierzchni drugiej i dwa na prostym licu. Program wyznaczy narożnik O oraz prostopadłą z O do lica. Wynik a = r pojawi się po sprawdzeniu konstrukcji trójkąta.'),
            'a_contour': tr('Kliknij teoretyczny narożnik O po stronie spoiny, pierwszy brzeg lica, pośrednie punkty konturu i drugi brzeg. Zakończ prawym przyciskiem. Przy licu wklęsłym zaznacz jego najgłębsze miejsce.'),
        }
        def show_hint():
            hint.setText(tr(instructions.get(method.currentData(),
                         'Wskaż istniejące prowadnice obu blach i prowadnicę lica. Przy promieniu ręcznym wskaż także jego koniec.')))
        method.currentIndexChanged.connect(show_hint)
        show_hint()
        form.addRow(tr('Metoda'), method)
        form.addRow(hint)
        form.addRow(buttons)
        if dialog.exec():
            key = method.currentData()
            if key in ('guided_throat', 'a_contour'):
                self.start(key)
            else:
                self.start('throat', method=key)

    def _comment_text(self, text=''):
        value, accepted = QInputDialog.getMultiLineText(self, tr('Komentarz na fotografii'),
                                                        tr('Wpisz treść komentarza:'), text)
        return value.strip()[:500] if accepted and value.strip() else None

    def edit_comment(self):
        self.properties.flush()
        item = self.editor.item(self.editor.selected)
        if item and item['kind'] == 'comment':
            style = item['style']
            previous = style['custom_label']
            updated = self._comment_text(previous)
            if updated is not None:
                self.editor.style(item['id'], style=dict(style, signature='custom', custom_label=updated))

    def scale(self):
        dialog, form, buttons = self._dialog(tr('Wstaw skalę'))
        choices = QComboBox()
        for n in (1, 2, 5, 10, 20):
            choices.addItem(f'{n} mm', float(n))
        choices.addItem(tr('Wartość własna'))
        choices.setCurrentIndex(3)
        length = self._scale_length(10.)
        length.setEnabled(False)
        choices.currentIndexChanged.connect(lambda: length.setEnabled(choices.currentData() is None))
        form.addRow(tr('Długość'), choices)
        form.addRow(tr('Własna długość'), length)
        form.addRow(buttons)
        if dialog.exec():
            self.start('scale', length_mm=choices.currentData() or length.value())

    @staticmethod
    def _scale_length(value):
        control = QDoubleSpinBox()
        control.setRange(.001, 100000.)
        control.setDecimals(3)
        control.setSuffix(' mm')
        control.setValue(value)
        return control

    def refresh(self):
        allowed = self.enabled()
        self.setEnabled(allowed)
        self.buttons['clear'].setEnabled(bool(self.editor.items or self.canvas.measurements))
        self.buttons['undo'].setEnabled(bool(self.canvas.history))
        self.buttons['redo'].setEnabled(bool(self.canvas.future))
        for key in ('circle', 'throat', 'scale'):
            self.buttons[key].setEnabled(self.canvas.calibration_matrix is not None)
        blocker = QSignalBlocker(self.table)
        entries = list(self.editor.items)
        for i, original in enumerate(self.canvas.measurements):
            obj = promote_measurement(original)
            if obj:
                entries.append(dict(obj, id=f'legacy:{i}'))
        self._rows = [item['id'] for item in entries]
        self._multiple.intersection_update(self._rows)
        self.table.setRowCount(len(entries))
        scene = Scene(entries, self.canvas.calibration_matrix, self.editor.shape) if self.canvas.has_image() else {}
        for row, item in enumerate(entries):
            result = scene[item['id']]
            dimension = caption(result.value, result.unit)
            if not dimension and result.radius is not None:
                dimension = caption(result.radius, 'mm', 'r') + tr(' (a nieważne)')
            if not dimension:
                dimension = tr('Nieważny') if result.status else '—'
            visible = (tr('Tak') if item['visible'] else tr('Nie'))
            if item['kind'] == 'scale' and self.canvas.calibration_matrix is None:
                visible = tr('Nieważna')
            values = (str(row+1), tr(TYPES[item['kind']]), self._display_name(item), dimension, visible)
            for column, text in enumerate(values):
                cell = QTableWidgetItem(text)
                cell.setToolTip('\n'.join(filter(None, (text, result.status))))
                self.table.setItem(row, column, cell)
        del blocker
        self._selected_canvas(self.editor.selected or '', refresh=True)

    def _selected_canvas(self, uid, refresh=False):
        if not self._table_event and not refresh:
            self._multiple = {uid} if uid else set()
        wanted = self._multiple | ({uid} if uid else set())
        blocker = QSignalBlocker(self.table)
        model = self.table.selectionModel()
        model.clearSelection()
        for row, row_id in enumerate(self._rows):
            if row_id in wanted:
                model.select(self.table.model().index(row, 0),
                             QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        del blocker
        for name in ('edit', 'visible', 'copy', 'delete'):
            self.buttons[name].setEnabled(uid in self._rows)
        self.properties.select(uid, refresh=refresh)

    def _selected_row(self):
        model = self.table.selectionModel()
        rows = [index.row() for index in model.selectedRows()]
        self._multiple = {self._rows[row] for row in rows}
        self._table_event = True
        try:
            if not rows:
                self.editor.select(None)
                return
            row = self.table.currentRow() if self.table.currentRow() in rows else rows[0]
            uid = self._rows[row]
            self.start('select')
            if uid.startswith('legacy:') and len(rows) == 1:
                uid = self.editor.promote(int(uid.split(':')[1]))
                self._multiple = {uid}
            elif uid.startswith('legacy:'):
                uid = next((x for x in self._multiple if not x.startswith('legacy:')), None)
            self.editor.select(uid)
        finally:
            self._table_event = False

    def open_properties(self, uid):
        if uid:
            item = self.editor.item(uid)
            if item and item['kind'] == 'comment':
                self.edit_comment()
                return
            self.open_style_properties()

    def open_style_properties(self):
        uid = self.editor.selected
        if uid:
            self.properties.select(uid, refresh=True)
            self.window.measurement_tab.ensureWidgetVisible(self.properties, 5, 12)
            self.properties.setFocus(Qt.FocusReason.OtherFocusReason)

    def edit(self):
        self.open_properties(self.editor.selected)

    def _table_context(self, local):
        row = self.table.rowAt(local.y())
        if row >= 0:
            self.table.selectRow(row)
            self.context(self.table.viewport().mapToGlobal(local))

    def context(self, position):
        menu = QMenu(self)
        item = self.editor.item(self.editor.selected)
        if item and item['kind'] == 'comment':
            menu.addAction(tr('Edytuj treść komentarza…'), self.edit_comment)
        menu.addAction(tr('Edytuj właściwości'), self.open_style_properties)
        menu.addAction(tr('Kopiuj styl'), self.copy_style)
        paste = menu.addAction(tr('Wklej styl'), self.paste_style)
        paste.setEnabled(self.clipboard is not None)
        menu.addAction(tr('Duplikuj'), self.copy)
        menu.addAction(tr('Ukryj / Pokaż'), self.visibility)
        menu.addAction(tr('Usuń'), self.delete)
        menu.exec(position)

    def _load_styles(self):
        try:
            data = json.loads(self.settings.value('styles', '{}', type=str))
            return {k: normalize_style(v) for k, v in data.items()}
        except (ValueError, TypeError, AttributeError):
            return {}

    def _refresh_presets(self, select=None):
        selected = select or self.presets.currentData()
        self.presets.clear()
        for key in PRESETS:
            self.presets.addItem(tr(key), key)
        for key in self.user_styles:
            self.presets.addItem(key, key)
        if selected:
            self.presets.setCurrentIndex(self.presets.findData(selected))

    def _preset(self, name=None):
        return (self.user_styles | PRESETS).get(name or self.presets.currentData())

    def _new_style(self, kind):
        style = self._preset(self.settings.value('default', '', type=str)) if self.settings.value('default') else None
        return dict(default_style(kind), **(formatting_style(style) if style else {}))

    def save_style(self):
        self.properties.flush()
        item = self.editor.item(self.editor.selected)
        if not item:
            return
        name, ok = QInputDialog.getText(self, tr('Zapisz styl'), tr('Nazwa stylu'))
        name = name.strip()[:80]
        if not ok or not name:
            return
        if name in PRESETS:
            self.window.statusBar().showMessage(tr('Wybierz nazwę inną niż nazwa wbudowanego stylu.'), 5000)
            return
        self.user_styles[name] = normalize_style(formatting_style(item['style']))
        self.settings.setValue('styles', json.dumps(self.user_styles, ensure_ascii=False))
        self._refresh_presets(name)

    def set_default(self):
        if self.presets.currentData():
            self.settings.setValue('default', self.presets.currentData())

    def clear_default(self):
        self.settings.remove('default')

    def copy_style(self):
        self.properties.flush()
        item = self.editor.item(self.editor.selected)
        if item:
            self.clipboard = formatting_style(item['style'])

    def paste_style(self):
        self.properties.flush()
        if self.clipboard and self.editor.selected:
            self.editor.apply_styles({self.editor.selected}, self.clipboard)

    @staticmethod
    def _restyle(items, legacy, selection, preset):
        objects, original = [], []
        for item in items:
            if selection is None or item['id'] in selection:
                item = dict(item, style=dict(item['style'], **preset))
            objects.append(item)
        for i, item in enumerate(legacy):
            obj = promote_measurement(item)
            if obj and (selection is None or f'legacy:{i}' in selection):
                obj['style'].update(preset)
                objects.append(obj)
            else:
                original.append(item)
        return objects, original

    def apply_selected(self):
        self.properties.flush()
        preset = self._preset()
        selection = self._multiple | ({self.editor.selected} if self.editor.selected else set())
        if not preset or not selection:
            return
        self._restyle_current(selection, formatting_style(preset))

    def _restyle_current(self, selection, preset):
        canvas = self.canvas
        new, legacy = self._restyle(self.editor.items, canvas.measurements, selection, preset)
        if (new, legacy) != (self.editor.items, canvas.measurements):
            canvas.begin_edit()
            self.editor.items = new
            canvas.measurements = legacy
            canvas.changed.emit()

    def apply_series(self):
        self.properties.flush()
        preset = self._preset()
        if not preset or not self.enabled():
            return
        fields = formatting_style(preset)
        current = self.window._sample()
        self._restyle_current(None, fields)
        for sample in self.window.project.samples:
            if sample is current:
                continue
            objects, legacy = self._restyle(sample.geometry_objects, sample.measurements, None, fields)
            if (objects, legacy) == (sample.geometry_objects, sample.measurements):
                continue
            past = (sample.mask_png, sample.fg_png, sample.bg_png, sample.roi_start,
                    sample.roi_end, deepcopy(sample.cal_points), deepcopy(sample.measurements),
                    deepcopy(sample.geometry_objects), sample.known_mm, sample.mm_per_px)
            sample.undo_history = [*sample.undo_history, past][-self.canvas.max_history:]
            sample.redo_history.clear()
            sample.geometry_objects, sample.measurements = objects, legacy
            sample.revision += 1
            self.window.project.mark_dirty()
        self.window._update_status()

    def copy(self):
        self.properties.flush()
        if self.enabled():
            self.editor.copy(self.editor.selected)

    def visibility(self):
        self.properties.flush()
        item = self.editor.item(self.editor.selected)
        if item:
            self.editor.style(item['id'], visible=not item['visible'])

    def delete(self):
        self.properties.flush()
        if not self.enabled() or self.window.tabs.currentIndex() != 4:
            return
        uid = self.editor.selected
        if not uid:
            self.window._remove_measurement()
            return
        dependents = self.editor.dependents(uid)
        if len(dependents) > 1:
            question = tr('Usunąć wybrany obiekt i {} zależne obiekty?').format(f'{len(dependents) - 1}')
            if QMessageBox.question(self, tr('Usuń obiekt'), question) != QMessageBox.StandardButton.Yes:
                return
        self.editor.delete(uid)

    def clear(self):
        self.properties.flush()
        if QMessageBox.question(self, tr('Wyczyść oznaczenia'),
                tr('Usunąć obiekty pomiarowe i wymiary bieżącego zdjęcia?')) == QMessageBox.StandardButton.Yes:
            self.editor.clear()

    def export(self):
        self.properties.flush()
        sample = self.window._sample()
        if not sample:
            return
        self.window._commit_current()
        dialog, form, buttons = self._dialog(tr('Eksport fotografii'))
        variant = QComboBox()
        variant.addItem(tr('A. Fotografia oryginalna'), 'original')
        variant.addItem(tr('B. Fotografia z pomiarami'), 'measurements')
        variant.addItem(tr('C. Fotografia do publikacji'), 'publication')
        variant.setCurrentIndex(1)
        choices = QListWidget()
        for item in sample.geometry_objects:
            choice = QListWidgetItem(f'{tr(TYPES[item["kind"]])} — {self._display_name(item)}', choices)
            choice.setData(Qt.ItemDataRole.UserRole, item['id'])
            choice.setCheckState(Qt.CheckState.Checked if item['visible'] else Qt.CheckState.Unchecked)
        for i, item in enumerate(sample.measurements):
            choice = QListWidgetItem(f'{i+1}. {item["kind"]}', choices)
            choice.setData(Qt.ItemDataRole.UserRole, f'legacy:{i}')
            choice.setCheckState(Qt.CheckState.Checked)
        variant.currentIndexChanged.connect(lambda: choices.setEnabled(variant.currentData() == 'publication'))
        choices.setEnabled(False)
        form.addRow(tr('Wariant'), variant)
        form.addRow(tr('Oznaczenia do publikacji'), choices)
        controls = QCheckBox(tr('Dołącz punkty kontrolne'))
        form.addRow(controls)
        uniform = QCheckBox(tr('Jednolita czcionka i grubość linii do publikacji'))
        uniform.setChecked(True)
        uniform.setEnabled(False)
        variant.currentIndexChanged.connect(lambda: uniform.setEnabled(variant.currentData() == 'publication'))
        form.addRow(uniform)
        form.addRow(buttons)
        if not dialog.exec():
            return
        key = variant.currentData()
        include = {choices.item(i).data(Qt.ItemDataRole.UserRole) for i in range(choices.count())
                   if choices.item(i).checkState() == Qt.CheckState.Checked}
        if not self._preview(sample, key, include, controls.isChecked(), uniform.isChecked()):
            return
        default = str(Path(sample.source_name).with_suffix('')) + f'_{key}.png'
        destination, fmt = QFileDialog.getSaveFileName(
            self, tr('Zapisz fotografię'), default,
            'PNG (*.png);;JPG (*.jpg *.jpeg);;BMP (*.bmp);;TIFF (*.tif *.tiff)')
        if not destination:
            return
        if not Path(destination).suffix:
            fmt_ext = {'TIFF': '.tiff', 'JPG': '.jpg', 'BMP': '.bmp', 'PNG': '.png'}
            destination += fmt_ext.get(fmt.split()[0], '.png') if fmt else '.png'
        protected = [p for s in self.window.project.samples for p in (s.image_path, s.original_path)]
        try:
            export_photo(sample, destination, key, include, protected, controls.isChecked(), uniform.isChecked())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr('Eksport fotografii'), str(exc))
        else:
            self.window.statusBar().showMessage(tr('Zapisano {}').format(f'{destination}'), 7000)

    def _preview(self, sample, variant, selected, controls, uniform):
        try:
            image, _ = native_photo(sample, variant, selected, controls, uniform)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr('Podgląd fotografii'), str(exc))
            return False
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('Podgląd fotografii przed zapisem'))
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        w, h = image.size
        raw = image.convert('RGB').tobytes()
        pix = QPixmap.fromImage(QImage(raw, w, h, 3*w, QImage.Format.Format_RGB888))
        fitted = pix.scaled(min(w, 810), min(h, 520), Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(fitted)
        scroll.setWidget(label)
        layout.addWidget(scroll, 1)
        native = QCheckBox(tr('Pokaż 1:1 ({} × {} px)').format(f'{w}', f'{h}'))
        def zoom(state):
            label.setPixmap(pix if state else fitted)
            label.adjustSize()
        native.toggled.connect(zoom)
        layout.addWidget(native)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        return dialog.exec() == QDialog.DialogCode.Accepted
