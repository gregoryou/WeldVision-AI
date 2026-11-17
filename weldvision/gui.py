"""WeldVision AI — uporządkowany interfejs Qt i bezpieczny kontroler zadań."""
from __future__ import annotations

import json
import html
import math
import os
import shutil
import sys
import tempfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QToolBar, QVBoxLayout, QWidget, QHeaderView, QScrollArea, QSizePolicy
)

from .canvas import ImageCanvas
from .measurements import MEASUREMENT_TYPES, measurement_mm
from .core import (
    Project, Sample, STATUS_APPROVED, STATUS_ERROR, STATUS_NEW, STATUS_READY,
    STATUS_REVIEW, clip_mask_roi, clean_mask, export_results, from_png,
    image_read, load_project, metrics, now_iso, png_bytes, roi_tuple,
    save_project, scaled_roi
)

STATUS_DISPLAY = {
    STATUS_NEW: ('○','Nowa'), STATUS_READY: ('◐','Gotowa do AI'),
    STATUS_REVIEW: ('!','Wymaga weryfikacji'), STATUS_APPROVED: ('✓','Zatwierdzona'),
    STATUS_ERROR: ('×','Błąd')
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(1650, 970)
        self.setMinimumSize(960, 620)
        self.project = Project()
        self.current_id = None
        self._loading = False
        self.process = None
        self.job = None
        self.line_buffer = b''
        self.stderr_buffer = bytearray()
        self.process_kind = ''
        self.process_done = False
        self.reported_errors = []
        self.active_job_settings = None
        self._last_autosave_error = ''
        self.setStatusBar(QStatusBar())
        self._create_ui()
        self._make_actions()
        self._update_status()
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setInterval(120_000)
        self.autosave_timer.timeout.connect(self._autosave)
        self.autosave_timer.start()
        QTimer.singleShot(250, self._check_recovery)

    # ------------------ UI ------------------
    def _create_ui(self):
        self.canvas = ImageCanvas()
        self.canvas.changed.connect(self._canvas_changed)
        self.canvas.calibration_ready.connect(self._calibration_changed)
        self.canvas.status.connect(self._canvas_status)
        self.canvas.measurement_ready.connect(self._measurement_finished)

        self.list_widget = QListWidget()
        self.list_widget.setMinimumWidth(180)
        self.search_samples = QLineEdit()
        self.search_samples.setPlaceholderText('Szukaj próbki lub zdjęcia...')
        self.search_samples.textChanged.connect(self._filter_samples)
        self.list_widget.currentRowChanged.connect(self._select_row)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setToolTip('Każda próbka zachowuje własne ROI, maski FG/BG, skalę i wyniki')
        self.list_widget.setStyleSheet('QListWidget::item{padding:7px 4px;}')
        b_add = QPushButton('Dodaj zdjęcia')
        b_add.clicked.connect(self.add_images)
        b_remove = QPushButton('Usuń próbkę')
        b_remove.clicked.connect(self.remove_sample)
        b_prev = QPushButton('◀ Poprzednia')
        b_prev.clicked.connect(self.previous)
        b_next = QPushButton('Następna ▶')
        b_next.clicked.connect(self.next)
        for b in (b_add, b_remove, b_prev, b_next):
            b.setMinimumHeight(31)
        self.add_button = b_add
        self.remove_button = b_remove
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(5,5,5,5)
        left_layout.addWidget(QLabel('PRÓBKI'))
        left_layout.addWidget(self.search_samples)
        left_layout.addWidget(self.list_widget, 1)
        left_layout.addWidget(b_add)
        left_layout.addWidget(b_remove)
        nav = QHBoxLayout()
        nav.addWidget(b_prev)
        nav.addWidget(b_next)
        left_layout.addLayout(nav)
        b_exit=QPushButton('Zamknij program')
        b_exit.clicked.connect(self.close)
        left_layout.addWidget(b_exit)

        view = QWidget()
        view_l = QVBoxLayout(view)
        view_l.setContentsMargins(3,3,3,3)
        self.image_header = QLabel('Dodaj zdjęcie lub otwórz projekt')
        self.image_header.setStyleSheet('font-weight:600;padding:4px')
        view_l.addWidget(self.image_header)
        view_l.addWidget(self.canvas, 1)
        show = QHBoxLayout()
        self.show_mask = QCheckBox('Pokaż maskę')
        self.show_mask.setChecked(True)
        self.show_mask.toggled.connect(self._visibility)
        self.show_marks = QCheckBox('Pokaż znaczniki FG / BG')
        self.show_marks.setChecked(True)
        self.show_marks.toggled.connect(self._visibility)
        fit = QPushButton('Dopasuj obraz')
        fit.clicked.connect(self.canvas.fit)
        show.addWidget(self.show_mask)
        show.addWidget(self.show_marks)
        show.addStretch(1)
        show.addWidget(fit)
        view_l.addLayout(show)

        self.tabs = QTabWidget()
        self.tabs.setObjectName('analysis_tabs')
        self.tabs.setMinimumWidth(315)
        self._tab_measurement()
        self._tab_ai()
        self._tab_edit()
        self._tab_results()

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(view)
        split.addWidget(self.tabs)
        split.setChildrenCollapsible(False)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([235, 1000, 355])
        self.setCentralWidget(split)
        self.splitter = split
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(160)
        self.progress.setRange(0, 100)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.status_label = QLabel('Brak projektu')
        self.statusBar().addPermanentWidget(self.status_label)

    def _tab_measurement(self):
        panel = QWidget()
        l = QVBoxLayout(panel)
        f = QFormLayout()
        self.sample_name = QLineEdit()
        self.sample_name.setPlaceholderText('np. 3315_12')
        self.sample_name.textEdited.connect(self._sample_name_changed)
        self.source_name = QLabel('—')
        self.source_name.setWordWrap(True)
        f.addRow('Nazwa próbki:', self.sample_name)
        f.addRow('Plik oryginalny:', self.source_name)
        l.addLayout(f)
        group = QGroupBox('Kalibracja wymiarowa')
        cal = QFormLayout(group)
        self.known = QDoubleSpinBox()
        self.known.setRange(.001, 100_000)
        self.known.setDecimals(4)
        self.known.setValue(10.0)
        self.known.valueChanged.connect(self._known_changed)
        self.scale_lbl = QLabel('Wskaż dwa punkty na zdjęciu')
        self.scale_lbl.setWordWrap(True)
        button = QPushButton('Wskaż 2 punkty kalibracyjne')
        self.calibration_button = button
        button.setObjectName('calibration_button')
        button.clicked.connect(lambda: self._tool(ImageCanvas.CAL))
        cal.addRow('Znana długość [mm]:', self.known)
        cal.addRow(button)
        cal.addRow('Skala:', self.scale_lbl)
        l.addWidget(group)
        self.measurement_group = QGroupBox('Grubość spoiny i blach')
        ml = QVBoxLayout(self.measurement_group)
        self.measure_type = QComboBox()
        self.measure_type.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.measure_type.setMinimumContentsLength(18)
        self.measure_type.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.measure_type.setObjectName('measurement_type')
        for key, (title, _, _) in MEASUREMENT_TYPES.items():
            self.measure_type.addItem(title, key)
        self.measure_type.currentIndexChanged.connect(self._measurement_type_changed)
        ml.addWidget(self.measure_type)
        self.measure_hint = QLabel('Najpierw wykonaj kalibrację zdjęcia.')
        self.measure_hint.setWordWrap(True)
        ml.addWidget(self.measure_hint)
        self.measure_button = QPushButton('Wskaż punkty pomiarowe')
        self.measure_button.setObjectName('measure_button')
        self.measure_button.clicked.connect(self._start_measurement)
        ml.addWidget(self.measure_button)
        self.measure_table = QTableWidget(0, 3)
        self.measure_table.setObjectName('measurement_table')
        self.measure_table.setHorizontalHeaderLabels(['Nr', 'Wymiar', 'Wynik [mm]'])
        self.measure_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.measure_table.verticalHeader().hide()
        self.measure_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.measure_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.measure_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.measure_table.setMinimumHeight(135)
        self.measure_table.setMaximumHeight(200)
        self.measure_table.itemSelectionChanged.connect(self._measurement_selection_changed)
        ml.addWidget(self.measure_table)
        row = QHBoxLayout()
        self.remove_measure_button = QPushButton('Usuń wybrany')
        self.remove_measure_button.clicked.connect(self._remove_measurement)
        row.addWidget(self.remove_measure_button)
        self.cancel_measure_button = QPushButton('Anuluj (Esc)')
        self.cancel_measure_button.clicked.connect(self._cancel_measurement)
        row.addWidget(self.cancel_measure_button)
        ml.addLayout(row)
        self.measurement_group.setEnabled(False)
        l.addWidget(self.measurement_group)
        density_group = QGroupBox('Gęstość materiału')
        den = QFormLayout(density_group)
        self.density = QDoubleSpinBox()
        self.density.setRange(.001, 30)
        self.density.setDecimals(4)
        self.density.setValue(7.85)
        self.density.valueChanged.connect(self._density_changed)
        self.global_density = QDoubleSpinBox()
        self.global_density.setRange(.001,30)
        self.global_density.setDecimals(4)
        self.global_density.setValue(7.85)
        apply = QPushButton('Zastosuj gęstość do całej serii')
        apply.clicked.connect(self.apply_global_density)
        den.addRow('Aktywna próbka [g/cm³]:', self.density)
        den.addRow('Globalnie [g/cm³]:', self.global_density)
        den.addRow(apply)
        l.addWidget(density_group)
        self.copy_setup = QPushButton('Skopiuj skalę i ROI do wszystkich')
        self.copy_setup.clicked.connect(self.copy_settings)
        l.addWidget(self.copy_setup)
        self.cal_tip = QLabel('Wskazówka: korzystaj z podziałki siatki 10 mm lub grubości blachy. Dla każdej próbki zachowuje się odrębna skala.')
        self.cal_tip.setWordWrap(True)
        self.cal_tip.setStyleSheet('color:#64748b')
        l.addWidget(self.cal_tip)
        l.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        self.tabs.addTab(scroll, 'Pomiar')

    def _tab_ai(self):
        panel = QWidget()
        l = QVBoxLayout(panel)
        self.ai_model = QComboBox()
        self.ai_model.addItems(['facebook/sam-vit-base','facebook/sam-vit-large','facebook/sam-vit-huge'])
        self.ai_model.setCurrentIndex(1)
        self.ai_model.currentTextChanged.connect(self._settings_changed)
        self.ai_device = QComboBox()
        self.ai_device.addItems(['Auto','CUDA (GPU)','CPU'])
        self.ai_device.currentIndexChanged.connect(self._settings_changed)
        f = QFormLayout()
        f.addRow('Model:', self.ai_model)
        f.addRow('Urządzenie:', self.ai_device)
        l.addLayout(f)
        self.clamp_roi = QCheckBox('Ogranicz maskę wynikową do ROI')
        self.clamp_roi.setChecked(True)
        l.addWidget(self.clamp_roi)
        self.min_area = QSpinBox()
        self.min_area.setRange(0, 50_000)
        self.min_area.setValue(0)
        self.min_area.setToolTip('0 = bez usuwania drobnych obszarów; zmienia pole pomiarowe')
        self.morph_size = QSpinBox()
        self.morph_size.setRange(0, 15)
        self.morph_size.setValue(0)
        self.morph_size.setToolTip('0 = brak morfologii; większa wartość może zmienić pole')
        f2 = QFormLayout()
        f2.addRow('Min. wyspa [px]:', self.min_area)
        f2.addRow('Domknięcie [px]:', self.morph_size)
        l.addLayout(f2)
        self.ai_selected_btn = QPushButton('Analizuj bieżącą próbkę')
        self.ai_selected_btn.clicked.connect(lambda: self.start_ai(False))
        self.grabcut_btn = QPushButton('GrabCut bieżącej próbki (bez AI)')
        self.grabcut_btn.clicked.connect(lambda: self.start_ai(False,mode='grabcut'))
        self.ai_batch_btn = QPushButton('Analizuj przygotowane zdjęcia')
        self.ai_batch_btn.clicked.connect(lambda: self.start_ai(True))
        self.ai_batch_btn.setStyleSheet('font-weight:600')
        self.stop_btn = QPushButton('Anuluj analizę')
        self.stop_btn.clicked.connect(self.cancel_ai)
        self.stop_btn.setEnabled(False)
        l.addWidget(self.ai_selected_btn)
        l.addWidget(self.grabcut_btn)
        l.addWidget(self.ai_batch_btn)
        l.addWidget(self.stop_btn)
        diag = QPushButton('Sprawdź pakiety AI i CUDA')
        diag.clicked.connect(self.diagnose_ai)
        l.addWidget(diag)
        self.ai_info = QLabel('Analiza odbywa się w osobnym procesie. Gdy brakuje pakietu, program pokaże jego nazwę i interpreter.')
        self.ai_info.setWordWrap(True)
        l.addWidget(self.ai_info)
        self.ai_log = QTextEdit()
        self.ai_log.setReadOnly(True)
        self.ai_log.setPlaceholderText('Komunikaty analizy...')
        self.ai_log.setMinimumHeight(170)
        l.addWidget(self.ai_log, 1)
        self.tabs.addTab(panel, 'AI')

    def _tab_edit(self):
        panel = QWidget()
        l = QVBoxLayout(panel)
        label=QLabel('Zaznacz obszar spoiny, popraw wynik pędzlem i zatwierdź pomiar.')
        label.setWordWrap(True)
        l.addWidget(label)
        r=QHBoxLayout()
        for name, mode in [('ROI',ImageCanvas.ROI),('FG +',ImageCanvas.FG),('BG −',ImageCanvas.BG)]:
            b=QPushButton(name)
            b.clicked.connect(lambda checked=False, mode=mode: self._tool(mode))
            r.addWidget(b)
        l.addLayout(r)
        r=QHBoxLayout()
        for name, mode in [('Dodaj maskę',ImageCanvas.ADD),('Usuń z maski',ImageCanvas.ERASE)]:
            b=QPushButton(name)
            b.clicked.connect(lambda checked=False, mode=mode: self._tool(mode))
            r.addWidget(b)
        l.addLayout(r)
        self.brush = QSpinBox()
        self.brush.setRange(1,300)
        self.brush.setValue(18)
        self.brush.valueChanged.connect(lambda x: setattr(self.canvas,'brush_px',x))
        form=QFormLayout()
        form.addRow('Promień pędzla [px]:',self.brush)
        l.addLayout(form)
        b_poly=QPushButton('Dodaj wielokąt (PPM: zamknij)')
        b_poly.clicked.connect(lambda: self._tool(ImageCanvas.POLY))
        b_pan=QPushButton('Przesuwanie obrazu')
        b_pan.clicked.connect(lambda: self._tool(ImageCanvas.PAN))
        l.addWidget(b_poly)
        l.addWidget(b_pan)
        r=QHBoxLayout()
        self.undo_btn=QPushButton('Cofnij')
        self.undo_btn.clicked.connect(self.canvas.undo)
        self.redo_btn=QPushButton('Ponów')
        self.redo_btn.clicked.connect(self.canvas.redo)
        r.addWidget(self.undo_btn)
        r.addWidget(self.redo_btn)
        l.addLayout(r)
        b_clear=QPushButton('Usuń znaczniki FG/BG')
        b_clear.clicked.connect(self.canvas.clear_seeds)
        b_mask=QPushButton('Wyczyść maskę')
        b_mask.clicked.connect(self._clear_mask)
        l.addWidget(b_clear)
        l.addWidget(b_mask)
        self.approve_btn=QPushButton('Zatwierdź pomiar')
        self.approve_btn.clicked.connect(self.approve)
        l.addWidget(self.approve_btn)
        l.addStretch(1)
        self.tabs.addTab(panel, 'Korekta')

    def _tab_results(self):
        panel=QWidget()
        l=QVBoxLayout(panel)
        self.lbl_status=QLabel('Status próbki: —')
        l.addWidget(self.lbl_status)
        form=QFormLayout()
        self.lbl_px=QLabel('—')
        self.lbl_area=QLabel('—')
        self.lbl_vol=QLabel('—')
        self.lbl_gpm=QLabel('—')
        self.lbl_kgpm=QLabel('—')
        for a,b in [('Pole [px²]:',self.lbl_px),('Pole [mm²]:',self.lbl_area),
                    ('Objętość [cm³/m]:',self.lbl_vol),('Masa [g/m]:',self.lbl_gpm),
                    ('Masa [kg/m]:',self.lbl_kgpm)]:
            form.addRow(a,b)
        l.addLayout(form)
        self.science_note=QLabel('Ważne: oszacowana masa materiału zaznaczonego przekroju na 1 m. Nie oznacza automatycznie rzeczywistego uzysku spoiwa, jeśli obszar obejmuje przetopiony materiał rodzimy.')
        self.science_note.setWordWrap(True)
        self.science_note.setStyleSheet('color:#64748b')
        l.addWidget(self.science_note)
        b_summary=QPushButton('Pokaż tabelę wszystkich próbek')
        b_summary.clicked.connect(self.show_results_table)
        l.addWidget(b_summary)
        b_export=QPushButton('Eksport wyników do folderu')
        b_export.clicked.connect(self.export_all)
        l.addWidget(b_export)
        l.addStretch(1)
        self.tabs.addTab(panel,'Wyniki')

    def _make_actions(self):
        bar=QToolBar('Najważniejsze działania')
        bar.setMovable(False)
        self.addToolBar(bar)
        menu=self.menuBar().addMenu('Plik')
        self.action_new=self._action('Nowy projekt',self.new_project,'Ctrl+N')
        self.action_add=self._action('Dodaj zdjęcia', self.add_images, 'Ctrl+O')
        self.action_open=self._action('Otwórz projekt', self.open_project, 'Ctrl+Shift+O')
        self.action_save=self._action('Zapisz', self.save, 'Ctrl+S')
        self.action_save_as=self._action('Zapisz jako…', self.save_as, 'Ctrl+Shift+S')
        self.action_export=self._action('Eksport', self.export_all)
        self.action_close=self._action('Zamknij', self.close, 'Ctrl+Q')
        for a in (self.action_new,self.action_open,self.action_add,self.action_save,self.action_save_as,self.action_export):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.action_close)
        for a in (self.action_add,self.action_open,self.action_save):
            bar.addAction(a)
        bar.addSeparator()
        self.action_ai=self._action('Analizuj serię',lambda: self.start_ai(True))
        self.action_cancel=self._action('Anuluj AI', self.cancel_ai)
        self.action_cancel.setEnabled(False)
        bar.addAction(self.action_ai)
        bar.addAction(self.action_cancel)
        edit_menu=self.menuBar().addMenu('Edycja')
        edit_menu.addAction(self._action('Cofnij', self.canvas.undo,'Ctrl+Z'))
        edit_menu.addAction(self._action('Ponów', self.canvas.redo,'Ctrl+Y'))
        edit_menu.addAction(self._action('Anuluj wskazywanie pomiaru', self._cancel_measurement, 'Esc'))
        edit_menu.addAction(self._action('Poprzednia próbka', self.previous,'Alt+Left'))
        edit_menu.addAction(self._action('Następna próbka', self.next,'Alt+Right'))
        help_menu=self.menuBar().addMenu('Pomoc')
        help_menu.addAction(self._action('Diagnostyka AI i GPU',self.diagnose_ai))
        help_menu.addAction(self._action('O programie',self.about))

    def _action(self,label,callback,shortcut=None):
        a=QAction(label,self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(callback)
        return a

    def about(self):
        QMessageBox.information(self,'WeldVision AI 3.2',
            'WeldVision AI 3.2 — pomiary grubości, przekroju spoiny i wspomaganie SAM.\n'
            'Projekty .weldproj (v1 i v2), zapis awaryjny i obsługa GPU NVIDIA.\n'
            'Wyniki wymagają potwierdzenia przez użytkownika.')

    # ------------------ próbki ------------------
    def _sample(self):
        return self.project.get(self.current_id)

    def _sample_name_changed(self,text):
        if self._loading or (self.process and self.process_kind=='ai'):
            return
        s=self._sample()
        if s and s.name != text:
            s.name=text
            s.revision+=1
            self.project.mark_dirty()
            self._refresh_list()
            self._update_status()

    def _density_changed(self,value):
        if self._loading or (self.process and self.process_kind=='ai'):
            return
        s=self._sample()
        if s and s.density != value:
            s.density=value
            if s.state == STATUS_APPROVED:
                s.state = STATUS_REVIEW
                s.approved_at = ''
            s.revision+=1
            self.project.mark_dirty()
            self._update_results()
            self._update_status()

    def _known_changed(self,value):
        if self._loading or (self.process and self.process_kind=='ai'):
            return
        s=self._sample()
        if s and s.known_mm != value:
            s.known_mm=value
            s.recalc_scale()
            if s.state == STATUS_APPROVED:
                s.state = STATUS_REVIEW
                s.approved_at = ''
            s.revision+=1
            self.project.mark_dirty()
            self._update_scale()
            self._update_results()
            self._update_status()

    def _settings_changed(self,*args):
        if self._loading:
            return
        self.project.model_id=self.ai_model.currentText()
        self.project.device=self._device()
        if self.project.samples:
            self.project.mark_dirty()
            self._update_status()

    def _device(self):
        index=self.ai_device.currentIndex()
        return ('auto','cuda','cpu')[max(0,index)]

    def _visibility(self):
        self.canvas.show_overlay=self.show_mask.isChecked()
        self.canvas.show_seeds=self.show_marks.isChecked()
        self.canvas.update()

    def _tool(self, mode):
        if not self._sample():
            return
        if self.process and self.process_kind=='ai':
            return
        self.canvas.set_mode(mode)
        self.tabs.setCurrentIndex(0 if mode == ImageCanvas.CAL else 2)
        if mode == ImageCanvas.CAL:
            self.measure_hint.setText('Kalibracja: wskaż dwa różne punkty znanej długości na zdjęciu.')
            self.statusBar().showMessage('Wskaż dwa punkty kalibracyjne na zdjęciu.', 6000)

    def _canvas_status(self, message):
        self.statusBar().showMessage(message, 6000)
        if self.canvas.mode == ImageCanvas.MEASURE:
            self.measure_hint.setText(message)

    def _measurement_type_changed(self):
        if self.canvas.mode == ImageCanvas.MEASURE:
            self.canvas.set_mode(ImageCanvas.PAN)
        self.measure_hint.setText(MEASUREMENT_TYPES[self.measure_type.currentData()][2])

    def _start_measurement(self):
        if not self._sample() or (self.process and self.process_kind == 'ai'):
            return
        if self.canvas.start_measurement(self.measure_type.currentData()):
            self.tabs.setCurrentIndex(0)

    def _cancel_measurement(self):
        if self.canvas.mode == ImageCanvas.MEASURE:
            self.canvas.set_mode(ImageCanvas.PAN)
            self.measure_hint.setText('Anulowano pomiar. Wybierz wymiar i wskaż punkty, aby rozpocząć ponownie.')

    def _measurement_finished(self):
        item = self.canvas.measurements[-1]
        value = measurement_mm(item, self.canvas.mm_per_px)
        message = f'Zapisano {item["kind"]} = {value:.3f} mm. Możesz rozpocząć kolejny pomiar.'
        self.measure_hint.setText(message)
        self.statusBar().showMessage(message, 6000)

    def _measurement_selection_changed(self):
        self.remove_measure_button.setEnabled(self.measure_table.currentRow() >= 0)

    def _remove_measurement(self):
        if self._sample() and not (self.process and self.process_kind == 'ai'):
            self.canvas.remove_measurement(self.measure_table.currentRow())

    def _update_measurements(self):
        sample = self._sample()
        items = sample.measurements if sample else []
        self.measure_table.setRowCount(len(items))
        for index, item in enumerate(items):
            value = measurement_mm(item, sample.mm_per_px)
            for column, text in enumerate((str(index+1), item['kind'],
                                          'brak skali' if value is None else f'{value:.3f}')):
                cell = QTableWidgetItem(text)
                cell.setToolTip(MEASUREMENT_TYPES[item['kind']][0])
                self.measure_table.setItem(index, column, cell)
        self._measurement_selection_changed()

    def add_images(self):
        if self.process and self.process_kind=='ai':
            return
        files,_=QFileDialog.getOpenFileNames(self,'Dodaj zdjęcia makroskopowe','',
                        'Obrazy (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)')
        if files:
            self.add_paths(files)

    def add_paths(self, paths):
        if self.process and self.process_kind=='ai':
            return
        added=[]
        for path in paths:
            try:
                s=Sample.from_file(path, self.global_density.value())
                added.append(s)
            except Exception as exc:
                QMessageBox.warning(self,'Nie udało się wczytać obrazu',str(exc))
        if not added:
            return
        if self._sample():
            self._commit_current()
        self.project.samples.extend(added)
        self.project.mark_dirty()
        self._refresh_list()
        self._select_id(added[0].uid)

    def _select_id(self,uid):
        for i,s in enumerate(self.project.samples):
            if s.uid==uid:
                if self.list_widget.currentRow()==i:
                    self._show_sample(uid)
                else:
                    self.list_widget.setCurrentRow(i)
                break

    def _select_row(self,row):
        if self._loading or row<0 or row>=len(self.project.samples):
            return
        s=self.project.samples[row]
        if s.uid!=self.current_id:
            self._commit_current()
            self._show_sample(s.uid)

    def _show_sample(self,uid):
        s=self.project.get(uid)
        if not s:
            return
        self._loading=True
        try:
            self.current_id=uid
            self.project.active_id=uid
            self.canvas.load_image(s.image_path)
            self.canvas.mask=s.mask()
            self.canvas.fg=s.mask('fg')
            self.canvas.bg=s.mask('bg')
            self.canvas.roi_start=s.roi_start
            self.canvas.roi_end=s.roi_end
            self.canvas.cal_points=list(s.cal_points)
            self.canvas.measurements=deepcopy(s.measurements)
            self.canvas.history=list(s.undo_history)
            self.canvas.future=list(s.redo_history)
            self.canvas.set_mode(ImageCanvas.PAN)
            self.canvas.invalidate_layers()
            self.sample_name.setText(s.name)
            self.source_name.setText(s.source_name)
            self.known.setValue(s.known_mm)
            self.density.setValue(s.density)
            self.image_header.setText(f'{s.name} · {s.source_name} · {s.dimensions[1]}×{s.dimensions[0]} px')
            self._update_scale()
            self._update_results()
            self.measure_hint.setText(MEASUREMENT_TYPES[self.measure_type.currentData()][2]
                                     if s.mm_per_px else 'Najpierw wykonaj kalibrację zdjęcia.')
        finally:
            self._loading=False
        self._update_status()

    def _commit_current(self):
        if self._loading:
            return
        s=self._sample()
        if not s or not self.canvas.has_image():
            return
        # Obraz na canvasie jest aktywny dla s; inne próbki przechowują tylko skompresowane PNG.
        changed=False
        for key in ('mask','fg','bg'):
            current=png_bytes(getattr(self.canvas,key))
            if current!=getattr(s,f'{key}_png'):
                setattr(s,f'{key}_png',current)
                changed=True
        pts=[list(p) for p in self.canvas.cal_points]
        if s.cal_points!=pts:
            s.cal_points=pts
            s.recalc_scale()
            changed=True
        if s.measurements != self.canvas.measurements:
            s.measurements = deepcopy(self.canvas.measurements)
            changed = True
        for key in ('roi_start','roi_end'):
            value=getattr(self.canvas,key)
            if getattr(s,key)!=value:
                setattr(s,key,value)
                changed=True
        s.undo_history=list(self.canvas.history)
        s.redo_history=list(self.canvas.future)
        if changed:
            s.revision+=1
            if s.state==STATUS_APPROVED:
                s.approved_at=''
            s.state=(STATUS_REVIEW if np.any(self.canvas.mask)
                     else (STATUS_READY if s.ready() else STATUS_NEW))
            self.project.mark_dirty()

    def _canvas_changed(self):
        if self._loading:
            return
        self._commit_current()
        self._update_scale()
        self._update_results()
        self._refresh_list()
        self._update_status()

    def _calibration_changed(self,pixels):
        if self._sample() and pixels > 0:
            self._canvas_changed()
            self.measure_hint.setText('Kalibracja gotowa. '
                                     + MEASUREMENT_TYPES[self.measure_type.currentData()][2])

    def _update_scale(self):
        s=self._sample()
        scale = s.mm_per_px if s else None
        self.canvas.mm_per_px = scale
        self.canvas.update()
        self.measurement_group.setEnabled(bool(scale) and not (self.process and self.process_kind == 'ai'))
        if not s or not s.mm_per_px:
            self.scale_lbl.setText('Brak kalibracji')
        else:
            self.scale_lbl.setText(f'{s.mm_per_px:.8f} mm/px · {1/s.mm_per_px:.2f} px/mm')

    def _update_results(self):
        self._update_measurements()
        s=self._sample()
        if not s:
            for lbl in (self.lbl_px,self.lbl_area,self.lbl_vol,self.lbl_gpm,self.lbl_kgpm):
                lbl.setText('—')
            self.lbl_status.setText('Status próbki: —')
            return
        mask=self.canvas.mask if self.current_id==s.uid and self.canvas.mask is not None else s.mask()
        m=metrics(mask,s.mm_per_px,s.density)
        self.lbl_px.setText(str(m['px2']))
        for label,key,digits in [(self.lbl_area,'area_mm2',4),(self.lbl_vol,'volume_cm3_m',4),
                                 (self.lbl_gpm,'mass_g_m',4),(self.lbl_kgpm,'mass_kg_m',6)]:
            v=m[key]
            label.setText('— (najpierw kalibracja)' if v is None else f'{v:.{digits}f}')
        self.lbl_status.setText('Status próbki: '+STATUS_DISPLAY.get(s.state,('?',s.state))[1])

    def _refresh_list(self):
        row=self.list_widget.currentRow()
        self.list_widget.blockSignals(True)
        try:
            self.list_widget.clear()
            for i,s in enumerate(self.project.samples):
                display=STATUS_DISPLAY.get(s.state,('?',s.state))
                suffix=' · ROI/FG' if s.ready() and s.state==STATUS_NEW else ''
                self.list_widget.addItem(f'{display[0]} {i+1:03d}  {s.name}{suffix}')
                self.list_widget.item(i).setToolTip(
                    f'{s.name} | {s.source_name} | Status: {display[1]}')
            if self.project.samples and row>=0:
                self.list_widget.setCurrentRow(min(row,len(self.project.samples)-1))
        finally:
            self.list_widget.blockSignals(False)
        self._filter_samples(self.search_samples.text())

    def _filter_samples(self, text):
        term=(text or '').strip().casefold()
        for i,sample in enumerate(self.project.samples):
            item=self.list_widget.item(i)
            if item is not None:
                item.setHidden(bool(term and term not in sample.name.casefold()
                                    and term not in sample.source_name.casefold()))

    def remove_sample(self):
        if self.process and self.process_kind=='ai':
            return
        row=self.list_widget.currentRow()
        if row<0:
            return
        s=self.project.samples[row]
        if QMessageBox.question(self,'Usuń próbkę',f'Usunąć {s.name} z projektu?\nZdjęcie źródłowe pozostanie na dysku.',
                               QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
            return
        self._commit_current()
        self.project.samples.pop(row)
        self.project.mark_dirty()
        self.current_id=None
        self._refresh_list()
        if self.project.samples:
            self._select_id(self.project.samples[min(row,len(self.project.samples)-1)].uid)
        else:
            self._clear_view()
        self._update_status()

    def _clear_view(self):
        self.canvas.img=None
        self.canvas.mask=None
        self.canvas.fg=None
        self.canvas.bg=None
        self.canvas.measurements=[]
        self.canvas.cal_points=[]
        self.canvas.cancel_pending()
        self.canvas.update()
        self._loading=True
        self.sample_name.clear()
        self.source_name.setText('—')
        self._loading=False
        self.image_header.setText('Dodaj zdjęcie lub otwórz projekt')
        self._update_scale()
        self.measure_hint.setText('Najpierw wykonaj kalibrację zdjęcia.')
        self._update_results()

    def previous(self):
        row=self.list_widget.currentRow()
        if row>0:
            self.list_widget.setCurrentRow(row-1)

    def next(self):
        row=self.list_widget.currentRow()
        if 0<=row<self.list_widget.count()-1:
            self.list_widget.setCurrentRow(row+1)

    def apply_global_density(self):
        if self.process and self.process_kind=='ai':
            return
        self._commit_current()
        value=self.global_density.value()
        for s in self.project.samples:
            if s.density!=value:
                s.density=value
                if s.state == STATUS_APPROVED:
                    s.state = STATUS_REVIEW
                    s.approved_at = ''
                s.revision+=1
                self.project.mark_dirty()
        if self._sample():
            self._loading=True
            self.density.setValue(value)
            self._loading=False
            self._update_results()
        self._update_status()
        self.statusBar().showMessage(f'Gęstość {value:.4f} g/cm³ zastosowano do {len(self.project.samples)} próbek',5000)

    def copy_settings(self):
        if self.process and self.process_kind=='ai':
            return
        self._commit_current()
        src=self._sample()
        if not src or len(self.project.samples)<2:
            return
        if QMessageBox.question(self,'Kopiuj ustawienia',
             'Skopiować kalibrację i ROI do pozostałych próbek?\n'
             'Współrzędne ROI zostaną przeskalowane do ich rozdzielczości.\n'
             'Kopiowanie kalibracji ma sens tylko przy identycznej skali fotografii.',
             QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
            return
        for s in self.project.samples:
            if s.uid==src.uid:
                continue
            s.known_mm=src.known_mm
            s.mm_per_px=src.mm_per_px
            if src.cal_points:
                sy,sx=src.dimensions
                dy,dx=s.dimensions
                s.cal_points=[[p[0]*dx/sx,p[1]*dy/sy] for p in src.cal_points]
                # Uwaga: kopiowanie do innej rozdzielczości przelicza piksele i mm/px
                s.recalc_scale()
            s.roi_start,s.roi_end=scaled_roi(src.roi_start,src.roi_end,src.dimensions,s.dimensions)
            if s.state == STATUS_APPROVED:
                s.state = STATUS_REVIEW
                s.approved_at = ''
            s.revision+=1
            self.project.mark_dirty()
        self._refresh_list()
        self._update_status()
        self.statusBar().showMessage('Skopiowano ustawienia. Zweryfikuj kalibrację każdej fotografii.',6000)

    def _clear_mask(self):
        if self._sample() and QMessageBox.question(self,'Wyczyść maskę','Na pewno wyczyścić aktualną maskę?',
             QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.canvas.clear_mask()

    def approve(self):
        self._commit_current()
        s=self._sample()
        if not s:
            return
        if not s.mm_per_px or not np.any(s.mask()):
            QMessageBox.warning(self,'Nie można zatwierdzić','Potrzebne są kalibracja i niepusta maska spoiny.')
            return
        s.state=STATUS_APPROVED
        s.error=''
        s.approved_at=now_iso()
        s.revision+=1
        self.project.mark_dirty()
        self._refresh_list()
        self._update_results()
        self._update_status()

    # ------------------ projekty ------------------
    def _update_status(self):
        name=Path(self.project.path).name if self.project.path else 'Nowy projekt'
        star=' • niezapisane zmiany' if self.project.dirty else ''
        self.setWindowTitle(f'WeldVision AI 3.2 — {name}{star}')
        self.status_label.setText(f'{len(self.project.samples)} próbek · {"zmiany niezapisane" if self.project.dirty else "zapisane"}')
        self.action_save.setEnabled(bool(self.project.samples))

    def _save_path(self,dest,auto=False):
        self._commit_current()
        try:
            save_project(self.project,dest,backup=not auto,mark_clean=not auto)
            if auto:
                self.statusBar().showMessage('Zapisano kopię odzyskiwania',3000)
            else:
                # Nie podsuwaj starego autozapisu po poprawnym zapisie.
                for stale in (self._recovery_dir()/'ostatnia_sesja.autosave.weldproj',
                              Path(dest).with_name(Path(dest).name+'.autosave.weldproj')):
                    try:
                        if stale.is_file():
                            stale.unlink()
                    except OSError:
                        pass
                self._update_status()
                self.statusBar().showMessage(f'Zapisano projekt: {dest}',5000)
            return True
        except Exception as exc:
            if not auto:
                QMessageBox.critical(self,'Nie udało się zapisać',str(exc))
            elif str(exc)!=self._last_autosave_error:
                self._last_autosave_error=str(exc)
                self.statusBar().showMessage('Błąd autozapisu: '+str(exc),9000)
            return False

    def save(self):
        if not self.project.samples:
            return False
        if not self.project.path:
            return self.save_as()
        return self._save_path(self.project.path)

    def save_as(self):
        if not self.project.samples:
            return False
        suggested=self.project.path or str(Path.home()/'Documents'/'Badania_spoin.weldproj')
        dest,_=QFileDialog.getSaveFileName(self,'Zapisz projekt',suggested,'Projekt WeldVision (*.weldproj)')
        if not dest:
            return False
        if not dest.lower().endswith('.weldproj'):
            dest+='.weldproj'
        return self._save_path(dest)

    def _guard_dirty(self):
        self._commit_current()
        if not self.project.dirty:
            return True
        answer=QMessageBox.warning(self,'Niezapisane zmiany',
             'Projekt zawiera niezapisane zmiany. Co chcesz zrobić?',
             QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,
             QMessageBox.StandardButton.Save)
        if answer==QMessageBox.StandardButton.Cancel:
            return False
        if answer==QMessageBox.StandardButton.Save:
            return bool(self.save())
        return True

    def new_project(self):
        if self.process and self.process_kind=='ai':
            QMessageBox.warning(self,'Trwa AI','Zakończ lub anuluj analizę przed zmianą projektu.')
            return
        if not self._guard_dirty():
            return
        old=self.project
        self._loading=True
        try:
            self.project=Project()
            self.current_id=None
            self.list_widget.clear()
            self.search_samples.clear()
            self._clear_view()
        finally:
            self._loading=False
        old.close()
        self._update_status()

    def open_project(self):
        if self.process and self.process_kind=='ai':
            QMessageBox.warning(self,'Trwa AI','Anuluj analizę przed otwarciem innego projektu.')
            return
        if not self._guard_dirty():
            return
        dest,_=QFileDialog.getOpenFileName(self,'Otwórz projekt','',
                                            'Projekt WeldVision (*.weldproj)')
        if dest:
            self.open_project_path(dest)

    def open_project_path(self,path):
        # Odtwórz nowszy autosave (jeśli istnieje); zapis docelowy nadal do pliku głównego.
        requested_path=Path(path)
        recovery = requested_path.with_name(requested_path.name+'.autosave.weldproj')
        restore=False
        if not requested_path.name.endswith('.autosave.weldproj') and recovery.exists():
            try:
                newer = recovery.stat().st_mtime > requested_path.stat().st_mtime
            except OSError:
                newer = False
            if newer:
                answer=QMessageBox.question(self,'Znaleziono nowszy autozapis',
                    'Znaleziono nowszą kopię odzyskiwania tego projektu. Przywrócić?\n'
                    'Zapisz później Ctrl+S, aby zaktualizować oryginalny projekt.',
                    QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
                restore=answer==QMessageBox.StandardButton.Yes
        try:
            loaded=load_project(recovery if restore else requested_path)
            if restore:
                loaded.path=str(requested_path)
                loaded.dirty=True
            elif requested_path.name=='ostatnia_sesja.autosave.weldproj':
                loaded.path=None
                loaded.dirty=True
        except Exception as exc:
            QMessageBox.critical(self,'Nie można otworzyć projektu',str(exc))
            return False
        old=self.project
        self._loading=True
        try:
            self.project=loaded
            self.current_id=None
            self.list_widget.blockSignals(True)
            self.list_widget.clear()
            self.list_widget.blockSignals(False)
            self.ai_model.setCurrentText(loaded.model_id)
            self.ai_device.setCurrentIndex({'auto':0,'cuda':1,'cpu':2}.get(loaded.device,0))
            self._refresh_list()
            self._select_id(loaded.active_id)
            if not restore:
                self.project.dirty=False
            self._update_status()
        finally:
            self._loading=False
        # _select_id invoked with loading=True so force showing correct image after guard release.
        self._select_id(loaded.active_id)
        old.close()
        self.statusBar().showMessage(f'Otworzono {Path(path).name}',5000)
        return True

    def _recovery_dir(self):
        root=Path(os.getenv('LOCALAPPDATA') or Path.home()/'.weldvision')/'WeldVisionAI'/'recovery'
        root.mkdir(parents=True,exist_ok=True)
        return root

    def _recovery_path(self):
        if self.project.path:
            p=Path(self.project.path)
            return p.with_name(p.name+'.autosave.weldproj')
        return self._recovery_dir()/'ostatnia_sesja.autosave.weldproj'

    def _autosave(self):
        if not self.project.dirty or not self.project.samples:
            return
        if self.process and self.process_kind=='ai':
            return
        self._save_path(self._recovery_path(),auto=True)

    def _check_recovery(self):
        # Nie naruszamy otwartego projektu. Ostatnia niezapisana sesja może być wznowiona.
        recovery=self._recovery_dir()/'ostatnia_sesja.autosave.weldproj'
        if recovery.exists() and not self.project.samples:
            answer=QMessageBox.question(self,'Odzyskiwanie sesji',
                   'Znaleziono automatycznie zapisany projekt. Przywrócić ostatnią sesję?',
                   QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if answer==QMessageBox.StandardButton.Yes:
                self.open_project_path(str(recovery))

    def _cleanup_autosave_on_save(self):
        pass

    def export_all(self):
        if not self.project.samples:
            return
        self._commit_current()
        dest=QFileDialog.getExistingDirectory(self,'Folder eksportu wyników')
        if not dest:
            return
        try:
            out=export_results(self.project,dest)
            QMessageBox.information(self,'Zakończono eksport',
                 f'Wyniki zapisano w nowym folderze:\n{out}\n\nPlik zbiorczy: wyniki_zbiorcze.csv')
        except Exception as exc:
            QMessageBox.critical(self,'Błąd eksportu',str(exc))

    def show_results_table(self):
        if not self.project.samples:
            return
        self._commit_current()
        # Separate modal table dialog, responsive and easy copy via selection
        from PyQt6.QtWidgets import QDialog
        dialog=QDialog(self)
        dialog.setWindowTitle('WeldVision AI — wyniki wszystkich próbek')
        dialog.resize(1070,550)
        lay=QVBoxLayout(dialog)
        fields=['Próbka','Status','Pole [mm²]','Gęstość [g/cm³]','Masa [kg/m]','Model AI']
        table=QTableWidget(len(self.project.samples),len(fields))
        table.setHorizontalHeaderLabels(fields)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i,s in enumerate(self.project.samples):
            m=s.summary()
            vals=[s.name,STATUS_DISPLAY.get(s.state,('',s.state))[1],
                  '—' if m['pole_mm2'] is None else f'{m["pole_mm2"]:.4f}',
                  f'{s.density:.4f}', '—' if m['masa_kg_m'] is None else f'{m["masa_kg_m"]:.6f}', s.model_id]
            for j,v in enumerate(vals):
                table.setItem(i,j,QTableWidgetItem(v))
        lay.addWidget(table)
        b=QPushButton('Zamknij')
        b.clicked.connect(dialog.accept)
        lay.addWidget(b)
        dialog.exec()

    # ------------------ AI ------------------
    def _seed_points(self,arr,limit=40):
        ys,xs=np.where(arr>0)
        if len(xs)==0:
            return []
        indices=np.linspace(0,len(xs)-1,min(limit,len(xs)),dtype=int)
        return [[float(xs[i]),float(ys[i])] for i in indices]

    def _prepare_tasks(self,batch):
        self._commit_current()
        samples = self.project.samples if batch else [self._sample()]
        tasks=[]
        skipped=[]
        for s in samples:
            if s is None:
                continue
            if batch and s.state==STATUS_APPROVED:
                skipped.append(s.name+' (zatwierdzona)')
                continue
            roi=s.roi()
            pos=self._seed_points(s.mask('fg'))
            neg=self._seed_points(s.mask('bg'))
            if roi is None and not pos:
                skipped.append(s.name+' (brak ROI i FG)')
                continue
            tasks.append({'uid':s.uid,'revision':s.revision,'image_path':s.image_path,
                          'roi':roi,'pos':pos,'neg':neg})
        return tasks,skipped

    def start_ai(self,batch,mode='sam'):
        if self.process:
            QMessageBox.information(self,'Analiza AI','Inne zadanie już działa.')
            return
        if not self.project.samples:
            return
        if not batch and self._sample() and self._sample().state==STATUS_APPROVED:
            if QMessageBox.question(self,'Zatwierdzony wynik',
                'Wynik jest zatwierdzony. Ponowna segmentacja zastąpi jego maskę. Kontynuować?',
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                return
        tasks,skipped=self._prepare_tasks(batch)
        if not tasks:
            QMessageBox.information(self,'Analiza AI',
                'Brak zdjęć gotowych do analizy. Narysuj ROI lub FG na co najmniej jednej próbce.')
            return
        if batch:
            message=(f'Gotowych: {len(tasks)}. Pominiętych: {len(skipped)}.\n'
                     'Zatwierdzone wyniki zostaną zachowane.\n'
                     'Rozpocząć analizę wsadową?')
            if QMessageBox.question(self,'Analiza wsadowa',message,
               QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                return
        self.job=tempfile.TemporaryDirectory(prefix='weldvision_ai_')
        work=Path(self.job.name)
        data={'model_id':self.ai_model.currentText(),'device':self._device(),
              'mode':mode,'output_dir':str(work/'results'),'tasks':tasks}
        self.active_job_settings={
            'model_id':data['model_id'], 'mode':mode,
            'min_area':self.min_area.value(), 'morph_size':self.morph_size.value(),
            'limit_roi':self.clamp_roi.isChecked()}
        jobpath=work/'job.json'
        jobpath.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        self.reported_errors=[]
        self.ai_log.clear()
        self._start_process(['--worker',str(jobpath)],'ai')

    def diagnose_ai(self):
        if self.process:
            return
        self.ai_log.clear()
        self._start_process(['--diagnose'],'diagnose')

    def _start_process(self,args,kind):
        self.process_kind=kind
        self.process_done=False
        self.line_buffer=b''
        self.stderr_buffer=bytearray()
        self.process=QProcess(self)
        exe=Path(sys.executable)
        # pythonw.exe w GUI nie gwarantuje stdout procesowi AI; użyj python.exe
        # z TEGO SAMEGO wirtualnego środowiska, aby torch/transformers były identyczne.
        if exe.name.lower()=='pythonw.exe':
            exe=exe.with_name('python.exe')
        self.worker_python=str(exe)
        self.process.setProgram(self.worker_python)
        proc_env=QProcessEnvironment.systemEnvironment()
        proc_env.insert('PYTHONUTF8','1')
        self.process.setProcessEnvironment(proc_env)
        script=Path(__file__).resolve().parent.parent/'weldvision_ai.py'
        self.process.setArguments([str(script),*args])
        self.process.setWorkingDirectory(str(script.parent))
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._process_finished)
        if kind=='ai':
            self.canvas.setEnabled(False)  # brak edycji w trakcie AI
            self.measurement_group.setEnabled(False)
            for widget in (self.sample_name,self.density,self.known,self.global_density,
                           self.ai_model,self.ai_device,self.clamp_roi,self.min_area,self.morph_size):
                widget.setEnabled(False)
            self.add_button.setEnabled(False)
            self.action_add.setEnabled(False)
            self.remove_button.setEnabled(False)
            self.copy_setup.setEnabled(False)
            self.ai_selected_btn.setEnabled(False)
            self.grabcut_btn.setEnabled(False)
            self.ai_batch_btn.setEnabled(False)
            self.action_ai.setEnabled(False)
            self.action_cancel.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.progress.setValue(0)
            self.progress.show()
        self.tabs.setCurrentIndex(1)
        self._append_log('Interpreter procesu: '+self.worker_python)
        self.process.start()

    def _append_log(self,msg):
        self.ai_log.append(html.escape(msg))
        self.ai_info.setText(msg[:280])

    def _read_stdout(self):
        if not self.process:
            return
        self.line_buffer+=bytes(self.process.readAllStandardOutput())
        while b'\n' in self.line_buffer:
            raw,self.line_buffer=self.line_buffer.split(b'\n',1)
            if not raw:
                continue
            try:
                self._handle_worker_message(json.loads(raw.decode('utf-8-sig')))
            except (ValueError,UnicodeError):
                self._append_log(raw.decode('utf-8','replace')[:600])

    def _read_stderr(self):
        if not self.process:
            return
        self.stderr_buffer.extend(bytes(self.process.readAllStandardError()))
        if len(self.stderr_buffer)>100_000:
            del self.stderr_buffer[:-100_000]

    def _handle_worker_message(self,msg):
        kind=msg.get('kind')
        if kind=='progress':
            self._append_log(msg.get('message',''))
        elif kind=='diagnostic':
            packages=msg.get('packages',{})
            lines=['Python: '+msg.get('python','')]
            for name in ('torch','transformers','PIL','cv2','numpy','safetensors'):
                lines.append(f'{name}: {packages.get(name,"?")}')
            lines.append('CUDA: '+('TAK' if msg.get('cuda') else 'NIE'))
            if msg.get('gpu'):
                lines.append('GPU: '+msg['gpu'])
            for line in lines:
                self._append_log(line)
        elif kind=='result':
            uid=msg['uid']
            s=self.project.get(uid)
            if not s:
                return
            if s.revision!=msg.get('revision'):
                self.reported_errors.append(f'{s.name}: dane zostały zmienione podczas analizy — wynik pominięty')
                return
            try:
                raw=Path(msg['path']).read_bytes()
                mask=from_png(raw,s.dimensions)
                s.raw_png=png_bytes(mask)
                settings=self.active_job_settings or {}
                mask=clean_mask(mask,settings.get('min_area',0),settings.get('morph_size',0))
                if settings.get('limit_roi',True):
                    mask=clip_mask_roi(mask,s.roi())
                s.mask_png=png_bytes(mask)
                s.method=msg.get('method','SAM')
                s.model_id=settings.get('model_id','') if s.method=='SAM' else ''
                s.min_area=settings.get('min_area',0)
                s.close_size=settings.get('morph_size',0)
                s.analyzed_at=now_iso()
                s.approved_at=''
                s.state=STATUS_REVIEW
                s.revision+=1
                self.project.mark_dirty()
                if s.uid==self.current_id:
                    self._loading=True
                    self.canvas.begin_edit()
                    self.canvas.mask=mask.copy()
                    self.canvas.invalidate_layers()
                    self._loading=False
                    self._update_results()
                self._refresh_list()
                self._update_status()
                if msg.get('total'):
                    self.progress.setValue(int(100*msg['index']/msg['total']))
                self._append_log(f'Zapisano maskę: {s.name}')
            except Exception as e:
                self.reported_errors.append(f'{s.name}: {e}')
        elif kind=='sample_error':
            s=self.project.get(msg.get('uid'))
            if s:
                s.error=msg['error']
                s.state=STATUS_ERROR
                s.revision+=1
                self.project.mark_dirty()
                self._refresh_list()
            self.reported_errors.append(f'{s.name if s else msg.get("uid")}: {msg.get("error")}')
            self._append_log('Błąd próbki: '+msg.get('error',''))
        elif kind=='fatal':
            self.reported_errors.append(msg.get('error','Nieznany błąd'))
            self._append_log('Błąd procesu: '+msg.get('error',''))
        elif kind=='finished':
            self.process_done=True
            self._append_log(f"Zakończono: {msg.get('processed',0)}/{msg.get('total',0)}")

    def _process_error(self,error):
        self._append_log(f'Błąd uruchomienia procesu AI: {error}')
        if error == QProcess.ProcessError.FailedToStart and self.process:
            QMessageBox.warning(self,'Nie można uruchomić AI',
                'Nie udało się uruchomić procesu roboczego przez interpreter:\n'+self.worker_python)
            # QProcess może nie wyemitować finished po FailedToStart.
            self._process_finished(2,QProcess.ExitStatus.CrashExit)

    def _process_finished(self, code, status):
        if self.process is None:
            return
        self._read_stdout()
        self._read_stderr()
        was_ai=self.process_kind=='ai'
        diagnostic=self.process_kind=='diagnose'
        if code!=0:
            stderr=self.stderr_buffer.decode('utf-8','replace')
            reason='\n'.join(self.reported_errors[-4:]) or stderr[-1500:] or f'Kod {code}'
            self._append_log(f'Proces zakończył się kodem {code}: {reason}')
            if was_ai:
                log=self._recovery_dir()/'weldvision_ai_error.log'
                try:
                    log.write_text(reason+'\n\n'+stderr,encoding='utf-8')
                except OSError:
                    pass
                QMessageBox.warning(self,'Błąd AI',
                    'Analiza zakończyła się niepowodzeniem, ale aplikacja i wyniki pozostają dostępne.\n\n'
                    +reason[:950]+f'\n\nLog: {log.name}')
        elif self.reported_errors and was_ai:
            QMessageBox.warning(self,'Analiza zakończona z uwagami','\n'.join(self.reported_errors[:8]))
        if was_ai:
            self.canvas.setEnabled(True)
            for widget in (self.sample_name,self.density,self.known,self.global_density,
                           self.ai_model,self.ai_device,self.clamp_roi,self.min_area,self.morph_size):
                widget.setEnabled(True)
            self.add_button.setEnabled(True)
            self.remove_button.setEnabled(True)
            self.copy_setup.setEnabled(True)
            self.ai_selected_btn.setEnabled(True)
            self.grabcut_btn.setEnabled(True)
            self.ai_batch_btn.setEnabled(True)
            self.action_ai.setEnabled(True)
            self.action_cancel.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.progress.hide()
        self.process.deleteLater()
        self.process=None
        self.process_kind=''
        self.active_job_settings=None
        if self.job:
            self.job.cleanup()
            self.job=None
        self._update_scale()
        self._update_results()
        self._update_status()

    def cancel_ai(self):
        if self.process and self.process_kind=='ai':
            self._append_log('Anulowanie analizy...')
            self.process.kill()  # osobny proces można przerwać bez niszczenia GUI

    # ------------------ zamykanie ------------------
    def closeEvent(self,event):
        # Dwa potwierdzenia, lecz niczego nie przerywamy przed końcową zgodą.
        if self.process:
            answer=QMessageBox.question(self,'Zamknij WeldVision AI',
                 'Trwa proces AI lub diagnostyka. Przerwać go i zamknąć program?',
                 QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if not self._guard_dirty():
            event.ignore()
            return
        if self.process:
            self.process.kill()
            self.process.waitForFinished(5000)
        if self.job:
            self.job.cleanup()
        self.project.close()
        event.accept()
