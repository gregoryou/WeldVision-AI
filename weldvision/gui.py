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
from PyQt6.QtCore import QProcess, QProcessEnvironment, QLocale, QSettings, QTimer, Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QStatusBar, QTableWidget, QTableWidgetItem, QTabWidget,
    QTextEdit, QToolBar, QVBoxLayout, QWidget, QHeaderView, QScrollArea, QSizePolicy
)

from .canvas import ImageCanvas
from .geometry_panel import GeometryPanel
from .measurements import MEASUREMENT_TYPES, measurement_mm
from .i18n import set_language, tr
from .core import (
    DEFAULT_MODEL, Project, Sample, STATUS_APPROVED, STATUS_ERROR, STATUS_NEW, STATUS_READY,
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
        self.ui_settings = QSettings('WeldVisionAI', 'Application')
        self.language = set_language(self.ui_settings.value('language', 'pl', type=str))
        QLocale.setDefault(QLocale(self.language))
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
        self.search_samples.setPlaceholderText(tr('Szukaj próbki lub zdjęcia...'))
        self.search_samples.textChanged.connect(self._filter_samples)
        self.list_widget.currentRowChanged.connect(self._select_row)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setToolTip(tr('Każda próbka zachowuje własne ROI, maski FG/BG, skalę i wyniki'))
        self.list_widget.setStyleSheet('QListWidget::item{padding:7px 4px;}')
        b_add = QPushButton(tr('Dodaj zdjęcia'))
        b_add.clicked.connect(self.add_images)
        b_remove = QPushButton(tr('Usuń próbkę'))
        b_remove.clicked.connect(self.remove_sample)
        b_prev = QPushButton(tr('◀ Poprzednia'))
        b_prev.clicked.connect(self.previous)
        b_next = QPushButton(tr('Następna ▶'))
        b_next.clicked.connect(self.next)
        for b in (b_add, b_remove, b_prev, b_next):
            b.setMinimumHeight(31)
        self.add_button = b_add
        self.remove_button = b_remove
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(5,5,5,5)
        left_layout.addWidget(QLabel(tr('PRÓBKI')))
        left_layout.addWidget(self.search_samples)
        left_layout.addWidget(self.list_widget, 1)
        left_layout.addWidget(b_add)
        left_layout.addWidget(b_remove)
        nav = QHBoxLayout()
        nav.addWidget(b_prev)
        nav.addWidget(b_next)
        left_layout.addLayout(nav)
        b_exit=QPushButton(tr('Zamknij program'))
        b_exit.clicked.connect(self.close)
        left_layout.addWidget(b_exit)

        view = QWidget()
        view_l = QVBoxLayout(view)
        view_l.setContentsMargins(3,3,3,3)
        self.image_header = QLabel(tr('Dodaj zdjęcie lub otwórz projekt'))
        self.image_header.setStyleSheet('font-weight:600;padding:4px')
        view_l.addWidget(self.image_header)
        view_l.addWidget(self.canvas, 1)
        show = QHBoxLayout()
        self.show_mask = QCheckBox(tr('Pokaż maskę'))
        self.show_mask.setChecked(True)
        self.show_mask.toggled.connect(self._visibility)
        self.show_marks = QCheckBox(tr('Pokaż znaczniki FG / BG'))
        self.show_marks.setChecked(True)
        self.show_marks.toggled.connect(self._visibility)
        fit = QPushButton(tr('Dopasuj obraz'))
        fit.clicked.connect(self.canvas.fit)
        show.addWidget(self.show_mask)
        show.addWidget(self.show_marks)
        show.addStretch(1)
        show.addWidget(fit)
        view_l.addLayout(show)

        self.tabs = QTabWidget()
        self.tabs.setObjectName('analysis_tabs')
        self.tabs.setMinimumWidth(315)
        self._tab_calibration()
        self._tab_edit()
        self._tab_ai()
        self._tab_results()
        self._tab_linear_measurement()
        self._tab_about()
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addWidget(self.tabs, 1)
        steps = QHBoxLayout()
        self.back_step = QPushButton(tr('← Wstecz'))
        self.back_step.clicked.connect(lambda: self._move_step(-1))
        self.next_step = QPushButton(tr('Dalej →'))
        self.next_step.clicked.connect(lambda: self._move_step(1))
        self.step_counter = QLabel()
        steps.addWidget(self.back_step)
        steps.addStretch(1)
        steps.addWidget(self.step_counter)
        steps.addStretch(1)
        steps.addWidget(self.next_step)
        sidebar_layout.addLayout(steps)
        self.tabs.currentChanged.connect(self._tab_changed)
        self._tab_changed(0)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(left)
        split.addWidget(view)
        split.addWidget(sidebar)
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
        self.status_label = QLabel(tr('Brak projektu'))
        self.statusBar().addPermanentWidget(self.status_label)

    def _tab_calibration(self):
        panel = QWidget()
        l = QVBoxLayout(panel)
        f = QFormLayout()
        self.sample_name = QLineEdit()
        self.sample_name.setPlaceholderText('np. 3315_12')
        self.sample_name.textEdited.connect(self._sample_name_changed)
        self.source_name = QLabel('—')
        self.source_name.setWordWrap(True)
        f.addRow(tr('Nazwa próbki:'), self.sample_name)
        f.addRow(tr('Plik oryginalny:'), self.source_name)
        l.addLayout(f)
        group = QGroupBox(tr('Kalibracja wymiarowa'))
        cal = QFormLayout(group)
        self.known = QDoubleSpinBox()
        self.known.setRange(.001, 100_000)
        self.known.setDecimals(4)
        self.known.setValue(10.0)
        self.known.valueChanged.connect(self._known_changed)
        self.scale_lbl = QLabel(tr('Wskaż dwa punkty na zdjęciu'))
        self.scale_lbl.setWordWrap(True)
        button = QPushButton(tr('Wskaż 2 punkty kalibracyjne'))
        self.calibration_button = button
        button.setObjectName('calibration_button')
        button.clicked.connect(lambda: self._tool(ImageCanvas.CAL))
        cal.addRow(tr('Znana długość [mm]:'), self.known)
        cal.addRow(button)
        self.grid_calibration_button = QPushButton(tr('Kalibracja siatki 10×10 mm (3 punkty)'))
        self.grid_calibration_button.setToolTip(tr('Wskaż 3 sąsiednie przecięcia siatki: wspólny narożnik, sąsiad wzdłuż poziomej i sąsiad wzdłuż pionowej linii. Każda odległość odpowiada 10 mm.'))
        self.grid_calibration_button.clicked.connect(self._start_grid_calibration)
        cal.addRow(self.grid_calibration_button)
        cal.addRow(tr('Skala:'), self.scale_lbl)
        l.addWidget(group)
        self.reset_cal_btn=QPushButton(tr('Usuń kalibrację tej próbki'))
        self.reset_cal_btn.setToolTip(tr('Nie usuwa zdjęcia, maski ani pomiarów. Po usunięciu skali wyniki w mm wymagają ponownej kalibracji.'))
        self.reset_cal_btn.clicked.connect(self._delete_calibration)
        l.addWidget(self.reset_cal_btn)
        self.undo_cal_btn=QPushButton(tr('Cofnij ostatnią operację (Ctrl+Z)'))
        self.undo_cal_btn.clicked.connect(self.canvas.undo)
        l.addWidget(self.undo_cal_btn)
        density_group = QGroupBox(tr('Gęstość materiału'))
        den = QFormLayout(density_group)
        self.density = QDoubleSpinBox()
        self.density.setRange(.001, 30)
        self.density.setDecimals(4)
        self.density.setValue(2.66)
        self.density.valueChanged.connect(self._density_changed)
        self.global_density = QDoubleSpinBox()
        self.global_density.setRange(.001,30)
        self.global_density.setDecimals(4)
        self.global_density.setValue(2.66)
        apply = QPushButton(tr('Zastosuj gęstość do całej serii'))
        apply.clicked.connect(self.apply_global_density)
        den.addRow(tr('Aktywna próbka [g/cm³]:'), self.density)
        den.addRow(tr('Globalnie [g/cm³]:'), self.global_density)
        den.addRow(apply)
        l.addWidget(density_group)
        self.copy_calibration = QCheckBox(tr('Kopiuj kalibrację'))
        self.copy_calibration.setChecked(True)
        self.copy_roi = QCheckBox(tr('Kopiuj ROI'))
        self.copy_roi.setChecked(False)
        l.addWidget(self.copy_calibration)
        l.addWidget(self.copy_roi)
        self.copy_setup = QPushButton(tr('Zastosuj wybrane ustawienia do całej serii'))
        self.copy_setup.clicked.connect(self.copy_settings)
        l.addWidget(self.copy_setup)
        self.cal_tip = QLabel(tr('Siatka 10×10 mm: wskaż trzy przecięcia tej SAMEJ kratki (narożnik, następne przecięcie w osi X, następne w osi Y). Użyj siatki leżącej w płaszczyźnie zgładu, aby uniknąć paralaksy. Dla każdej próbki wymagana jest niezależna kontrola skali.'))
        self.cal_tip.setWordWrap(True)
        self.cal_tip.setStyleSheet('color:#64748b')
        l.addWidget(self.cal_tip)
        l.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        self.calibration_tab = scroll
        self.tabs.addTab(scroll, tr('Kalibracja'))

    def _tab_linear_measurement(self):
        panel=QWidget()
        l=QVBoxLayout(panel)
        tip=QLabel(tr('Na zdjęciu widać tylko oznaczenia pomiarowe. Powiększaj kółkiem myszy. Środkowy przycisk przesuwa obraz.'))
        tip.setWordWrap(True)
        l.addWidget(tip)
        self.geometry_panel = GeometryPanel(self)
        l.addWidget(self.geometry_panel)
        self.measurement_group = QGroupBox(tr('Grubość spoiny i blach'))
        ml = QVBoxLayout(self.measurement_group)
        self.measure_type = QComboBox()
        self.measure_type.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.measure_type.setMinimumContentsLength(18)
        self.measure_type.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.measure_type.setObjectName('measurement_type')
        for key, (title, _, _) in MEASUREMENT_TYPES.items():
            if key != 'a':  # Old 3.2.x method must not be offered
                self.measure_type.addItem(tr(title), key)
        self.measure_type.currentIndexChanged.connect(self._measurement_type_changed)
        ml.addWidget(self.measure_type)
        self.measure_hint = QLabel(tr('Najpierw wykonaj kalibrację zdjęcia.'))
        self.measure_hint.setWordWrap(True)
        ml.addWidget(self.measure_hint)
        self.measure_button = QPushButton(tr('Wskaż punkty pomiarowe'))
        self.measure_button.setObjectName('measure_button')
        self.measure_button.clicked.connect(self._start_measurement)
        ml.addWidget(self.measure_button)
        self.measure_table = QTableWidget(0, 3)
        self.measure_table.setObjectName('measurement_table')
        self.measure_table.setHorizontalHeaderLabels([tr('Nr'), tr('Wymiar'), tr('Wynik [mm]')])
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
        self.remove_measure_button = QPushButton(tr('Usuń wybrany'))
        self.remove_measure_button.clicked.connect(self._remove_measurement)
        row.addWidget(self.remove_measure_button)
        self.cancel_measure_button = QPushButton(tr('Anuluj (Esc)'))
        self.cancel_measure_button.clicked.connect(self._cancel_measurement)
        row.addWidget(self.cancel_measure_button)
        ml.addLayout(row)
        self.measurement_group.setEnabled(False)
        l.addWidget(self.measurement_group)
        hint=QLabel(tr('Gardziel a: po grani i pierwszym brzegu wskazuj kolejno punkty rzeczywistego lica, kończąc na drugim brzegu. Prawy przycisk kończy pomiar. Dla wklęsłego lica dodaj punkty w jego najgłębszym miejscu.'))
        hint.setWordWrap(True)
        l.addWidget(hint)
        l.addStretch(1)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        self.measurement_tab = scroll
        self.tabs.addTab(scroll,tr('Pomiar'))

    def _tab_changed(self, index):
        self.canvas.geometry.flush_pending()
        # Measurement tab keeps its annotations separate from mask, ROI and seeds.
        clean=self.tabs.currentWidget() is self.measurement_tab
        self.canvas.clean_measurement_view=clean
        self.canvas.show_measurement_annotations=False
        self.show_mask.setEnabled(not clean)
        self.show_marks.setEnabled(not clean)
        if clean:
            self.canvas.geometry.start("select")
            self.geometry_panel.refresh()
        elif self.canvas.mode != ImageCanvas.PAN:
            self.canvas.set_mode(ImageCanvas.PAN)
        if self.tabs.currentWidget() is self.mask_settings_tab and self._sample():
            self.show_marks.setChecked(True)
        self.canvas.update()
        self._update_steps()

    def _move_step(self, direction):
        index = self.tabs.currentIndex()
        target = index + direction
        if 0 <= target < self.workflow_steps:
            self._commit_current()
            self.tabs.setCurrentIndex(target)

    @property
    def workflow_steps(self):
        return self.tabs.indexOf(self.about_tab)

    def _update_steps(self):
        index = self.tabs.currentIndex()
        count = self.workflow_steps
        self.back_step.setVisible(index < count)
        self.next_step.setVisible(index < count)
        self.step_counter.setVisible(index < count)
        self.back_step.setEnabled(0 < index < count)
        self.next_step.setEnabled(0 <= index < count - 1)
        self.step_counter.setText(tr('Etap {0} z {1}').format(index+1, count))
        if 0 <= index < count - 1:
            self.next_step.setText(tr('Dalej → {}').format(f'{self.tabs.tabText(index + 1)}'))

    def _tab_ai(self):
        panel = QWidget()
        l = QVBoxLayout(panel)
        self.ai_model = QComboBox()
        self.ai_model.addItems(['facebook/sam-vit-base','facebook/sam-vit-large','facebook/sam-vit-huge'])
        self.ai_model.setCurrentText(self.project.model_id)
        self.ai_model.currentTextChanged.connect(self._settings_changed)
        self.ai_device = QComboBox()
        self.ai_device.addItems(['Auto','CUDA (GPU)','CPU'])
        self.ai_device.setCurrentIndex({'auto': 0, 'cuda': 1, 'cpu': 2}.get(self.project.device, 0))
        self.ai_device.currentIndexChanged.connect(self._settings_changed)
        f = QFormLayout()
        f.addRow(tr('Model:'), self.ai_model)
        f.addRow(tr('Urządzenie:'), self.ai_device)
        l.addLayout(f)
        self.clamp_roi = QCheckBox(tr('Ogranicz maskę wynikową do ROI'))
        self.clamp_roi.setChecked(True)
        l.addWidget(self.clamp_roi)
        self.min_area = QSpinBox()
        self.min_area.setRange(0, 50_000)
        self.min_area.setValue(0)
        self.min_area.setToolTip(tr('0 = bez usuwania drobnych obszarów; zmienia pole pomiarowe'))
        self.morph_size = QSpinBox()
        self.morph_size.setRange(0, 15)
        self.morph_size.setValue(0)
        self.morph_size.setToolTip(tr('0 = brak morfologii; większa wartość może zmienić pole'))
        f2 = QFormLayout()
        f2.addRow(tr('Min. wyspa [px]:'), self.min_area)
        f2.addRow(tr('Domknięcie [px]:'), self.morph_size)
        l.addLayout(f2)
        self.ai_selected_btn = QPushButton(tr('Utwórz maskę AI — bieżąca próbka'))
        self.ai_selected_btn.clicked.connect(lambda: self.start_ai(False))
        self.ai_batch_btn = QPushButton(tr('Analizuj przygotowane zdjęcia'))
        self.ai_batch_btn.clicked.connect(lambda: self.start_ai(True))
        self.ai_batch_btn.setStyleSheet('font-weight:600')
        self.stop_btn = QPushButton(tr('Anuluj analizę'))
        self.stop_btn.clicked.connect(self.cancel_ai)
        self.stop_btn.setEnabled(False)
        l.addWidget(self.ai_selected_btn)
        l.addWidget(self.ai_batch_btn)
        l.addWidget(self.stop_btn)
        diag = QPushButton(tr('Sprawdź pakiety AI i CUDA'))
        diag.clicked.connect(self.diagnose_ai)
        l.addWidget(diag)
        self._analysis_review(l)
        self.ai_info = QLabel(tr('Analiza odbywa się w osobnym procesie. Gdy brakuje pakietu, program pokaże jego nazwę i interpreter.'))
        self.ai_info.setWordWrap(True)
        l.addWidget(self.ai_info)
        self.ai_log = QTextEdit()
        self.ai_log.setReadOnly(True)
        self.ai_log.setPlaceholderText(tr('Komunikaty analizy...'))
        self.ai_log.setMinimumHeight(170)
        l.addWidget(self.ai_log)
        l.addStretch(1)
        self.analysis_tab = QScrollArea()
        self.analysis_tab.setWidgetResizable(True)
        self.analysis_tab.setWidget(panel)
        self.tabs.addTab(self.analysis_tab, tr('Analiza'))

    def _tab_edit(self):
        panel = QWidget()
        self.mask_settings_tab = panel
        l = QVBoxLayout(panel)
        self.preparation_status = QLabel(tr('Dodaj zdjęcie, aby przygotować segmentację.'))
        self.preparation_status.setWordWrap(True)
        l.addWidget(self.preparation_status)
        row = QHBoxLayout()
        for name, mode, hint in [
            ('ROI', ImageCanvas.ROI, tr('Zaznacz prostokąt obejmujący całą spoinę z niewielkim zapasem.')),
            ('FG +', ImageCanvas.FG, tr('Zaznacz pewne fragmenty wewnątrz spoiny (zielone).')),
            ('BG −', ImageCanvas.BG, tr('Zaznacz pewne fragmenty poza spoiną (niebieskie).')),
        ]:
            button = QPushButton(name)
            button.setToolTip(hint)
            button.clicked.connect(lambda checked=False, mode=mode: self._tool(mode))
            row.addWidget(button)
        l.addLayout(row)
        self.seed_brush = self._brush_field(l)
        self._mask_history_buttons(l)
        clear = QPushButton(tr('Usuń znaczniki FG/BG'))
        clear.clicked.connect(self.canvas.clear_seeds)
        l.addWidget(clear)
        l.addStretch(1)
        self.tabs.addTab(panel, tr('Ustawienia maski'))

    def _brush_field(self, layout):
        spin = QSpinBox()
        spin.setRange(1, 300)
        spin.setValue(18)
        spin.valueChanged.connect(lambda value: setattr(self.canvas, 'brush_px', value))
        form = QFormLayout()
        form.addRow(tr('Promień pędzla [px]:'), spin)
        layout.addLayout(form)
        return spin

    def _mask_history_buttons(self, layout):
        row = QHBoxLayout()
        for label, callback in ((tr('Cofnij'), self.canvas.undo), (tr('Ponów'), self.canvas.redo)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addLayout(row)

    def _analysis_review(self, layout):
        self.review_group = QGroupBox(tr('Sprawdź i popraw maskę wynikową'))
        l = QVBoxLayout(self.review_group)
        self.correction_status = QLabel(tr('Dodaj zdjęcie, aby utworzyć maskę spoiny.'))
        self.correction_status.setWordWrap(True)
        l.addWidget(self.correction_status)
        row = QHBoxLayout()
        for name, mode in [(tr('Dodaj do maski'), ImageCanvas.ADD), (tr('Usuń z maski'), ImageCanvas.ERASE)]:
            button = QPushButton(name)
            button.clicked.connect(lambda checked=False, mode=mode: self._tool(mode))
            row.addWidget(button)
        l.addLayout(row)
        self.brush = self._brush_field(l)
        for name, mode in [(tr('Dodaj wielokąt (prawy przycisk kończy)'), ImageCanvas.POLY),
                           ('Przesuwanie obrazu', ImageCanvas.PAN)]:
            button = QPushButton(name)
            button.clicked.connect(lambda checked=False, mode=mode: self._tool(mode))
            l.addWidget(button)
        self._mask_history_buttons(l)
        clear = QPushButton(tr('Wyczyść maskę'))
        clear.clicked.connect(self._clear_mask)
        l.addWidget(clear)
        self.approve_btn = QPushButton(tr('Zatwierdź pomiar pola'))
        self.approve_btn.setEnabled(False)
        self.approve_btn.setToolTip(tr('Oznacza maskę i pole przekroju jako sprawdzone przez użytkownika.'))
        self.approve_btn.clicked.connect(self.approve)
        l.addWidget(self.approve_btn)
        layout.addWidget(self.review_group)

    def _tab_results(self):
        panel=QWidget()
        l=QVBoxLayout(panel)
        self.lbl_status=QLabel(tr('Status próbki: —'))
        l.addWidget(self.lbl_status)
        form=QFormLayout()
        self.lbl_px=QLabel('—')
        self.lbl_area=QLabel('—')
        self.lbl_vol=QLabel('—')
        self.lbl_gpm=QLabel('—')
        self.lbl_kgpm=QLabel('—')
        for a,b in [(tr('Pole [px²]:'),self.lbl_px),(tr('Pole [mm²]:'),self.lbl_area),
                    (tr('Objętość [cm³/m]:'),self.lbl_vol),(tr('Masa [g/m]:'),self.lbl_gpm),
                    (tr('Masa [kg/m]:'),self.lbl_kgpm)]:
            form.addRow(a,b)
        l.addLayout(form)
        self.science_note=QLabel(tr('Pole [mm²] i objętość [cm³/m] mają tę samą LICZBĘ, ponieważ 1 mm² × 1 m = 1 cm³. Jednostki są różne. Jest to teoretyczna objętość i masa na metr przy niezmiennym przekroju; nie oznacza automatycznie zużycia drutu ani uzysku stopiwa. Dokładność zależy od kalibracji siatki i maski.'))
        self.science_note.setWordWrap(True)
        self.science_note.setStyleSheet('color:#64748b')
        l.addWidget(self.science_note)
        b_summary=QPushButton(tr('Pokaż tabelę wszystkich próbek'))
        b_summary.clicked.connect(self.show_results_table)
        l.addWidget(b_summary)
        b_export=QPushButton(tr('Zapisz wyniki do Excela (.xlsx) i folderu'))
        b_export.clicked.connect(self.export_all)
        l.addWidget(b_export)
        l.addStretch(1)
        self.results_tab = panel
        self.tabs.addTab(panel,tr('Wynik'))

    def _make_actions(self):
        self.main_toolbar = bar = QToolBar(tr('Najważniejsze działania'))
        self.window_actions = []
        bar.setMovable(False)
        self.addToolBar(bar)
        menu=self.menuBar().addMenu(tr('Plik'))
        self.action_new=self._action(tr('Nowy projekt'),self.new_project,'Ctrl+N')
        self.action_add=self._action(tr('Dodaj zdjęcia'), self.add_images, 'Ctrl+O')
        self.action_open=self._action(tr('Otwórz projekt'), self.open_project, 'Ctrl+Shift+O')
        self.action_save=self._action(tr('Zapisz'), self.save, 'Ctrl+S')
        self.action_save_as=self._action(tr('Zapisz jako…'), self.save_as, 'Ctrl+Shift+S')
        self.action_export=self._action(tr('Eksport'), self.export_all)
        self.action_close=self._action(tr('Zamknij'), self.close, 'Ctrl+Q')
        for a in (self.action_new,self.action_open,self.action_add,self.action_save,self.action_save_as,self.action_export):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(self.action_close)
        for a in (self.action_add,self.action_open,self.action_save):
            bar.addAction(a)
        bar.addSeparator()
        self.action_ai=self._action(tr('Analizuj serię'),lambda: self.start_ai(True))
        self.action_cancel=self._action(tr('Anuluj AI'), self.cancel_ai)
        self.action_cancel.setEnabled(False)
        bar.addAction(self.action_ai)
        bar.addAction(self.action_cancel)
        edit_menu=self.menuBar().addMenu(tr('Edycja'))
        edit_menu.addAction(self._action(tr('Cofnij'), self.canvas.undo,'Ctrl+Z'))
        edit_menu.addAction(self._action(tr('Ponów'), self.canvas.redo,'Ctrl+Y'))
        edit_menu.addAction(self._action(tr('Anuluj wskazywanie pomiaru'), self._cancel_measurement, 'Esc'))
        edit_menu.addAction(self._action(tr('Usuń zaznaczony obiekt'), self.geometry_panel.delete, 'Delete'))
        edit_menu.addAction(self._action(tr('Poprzednia próbka'), self.previous,'Alt+Left'))
        edit_menu.addAction(self._action(tr('Następna próbka'), self.next,'Alt+Right'))
        help_menu=self.menuBar().addMenu(tr('Pomoc'))
        help_menu.addAction(self._action(tr('Diagnostyka AI i GPU'),self.diagnose_ai))
        help_menu.addAction(self._action(tr('O programie'),self.about))

    def _action(self,label,callback,shortcut=None):
        a=QAction(label,self)
        self.window_actions.append(a)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(callback)
        return a

    def _tab_about(self):
        panel = QWidget()
        self.about_tab = panel
        layout = QVBoxLayout(panel)
        title = QLabel('WeldVision AI 3.5.0')
        title.setStyleSheet('font-size:20px; font-weight:600;')
        layout.addWidget(title)
        description = QLabel(tr('Pomiary przekrojów i gardzieli spoin na zdjęciach makroskopowych. Segmentacja SAM i ręczna korekta maski. Projekty .weldproj.'))
        description.setWordWrap(True)
        layout.addWidget(description)

        # Public project information: contact is through GitHub (no private address,
        # telephone number or unpublished e-mail is embedded in distributed code).
        author_group = QGroupBox(tr('Autor i kontakt'))
        author_form = QFormLayout(author_group)
        author = QLabel('Sławomir Krajewski')
        author.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        author_form.addRow(tr('Autor i kierownictwo projektu:'), author)

        affiliation = QLabel(tr('Zachodniopomorski Uniwersytet Technologiczny w Szczecinie (afiliacja naukowa autora)'))
        affiliation.setWordWrap(True)
        affiliation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        author_form.addRow(tr('Afiliacja:'), affiliation)

        repo = QLabel('<a href="https://github.com/gregoryou/WeldVision-AI">github.com/gregoryou/WeldVision-AI</a>')
        repo.setOpenExternalLinks(True)
        repo.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        author_form.addRow(tr('Kod źródłowy:'), repo)

        support = QLabel('<a href="https://github.com/gregoryou/WeldVision-AI/issues">github.com/gregoryou/WeldVision-AI/issues</a>')
        support.setOpenExternalLinks(True)
        support.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        author_form.addRow(tr('Kontakt / zgłaszanie błędów:'), support)
        author_form.addRow(tr('Licencja:'), QLabel('GNU GPL-3.0-only'))
        layout.addWidget(author_group)

        disclaimer = QLabel(tr('Afiliacja wskazuje miejsce pracy naukowej autora i nie oznacza, że uczelnia jest wydawcą, sponsorem lub oficjalnym podmiotem odpowiedzialnym za program.'))
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet('color: palette(mid); font-size: 11px;')
        layout.addWidget(disclaimer)

        form = QFormLayout()
        self.language_selector = QComboBox()
        self.language_selector.addItem('PL — Polski', 'pl')
        self.language_selector.addItem('EN — English', 'en')
        self.language_selector.setCurrentIndex(self.language_selector.findData(self.language))
        self.language_selector.currentIndexChanged.connect(
            lambda: self.change_language(self.language_selector.currentData()))
        form.addRow(tr('Język interfejsu'), self.language_selector)
        layout.addLayout(form)
        layout.addStretch(1)
        self.tabs.addTab(panel, tr('O programie'))

    def about(self):
        self.tabs.setCurrentWidget(self.about_tab)

    def change_language(self, language):
        if language == self.language or self.process is not None:
            return
        self.canvas.geometry.flush_pending()
        self._commit_current()
        uid = self.current_id
        step = self.tabs.currentIndex()
        sizes = self.splitter.sizes()
        zoom, offset = self.canvas.zoom, self.canvas.offset
        options = (self.clamp_roi.isChecked(), self.min_area.value(), self.morph_size.value(),
                   self.global_density.value(), self.show_mask.isChecked(), self.show_marks.isChecked(),
                   self.seed_brush.value(), self.brush.value(), self.search_samples.text(),
                   self.geometry_panel.snap.isChecked())
        selected = self.canvas.geometry.selected
        log = self.ai_log.toPlainText()
        self.language = set_language(language)
        QLocale.setDefault(QLocale(self.language))
        self.ui_settings.setValue('language', self.language)
        old = self.takeCentralWidget()
        old.hide()
        old.deleteLater()
        self.removeToolBar(self.main_toolbar)
        self.main_toolbar.hide()
        self.main_toolbar.deleteLater()
        self.menuBar().clear()
        for action in self.window_actions:
            action.setEnabled(False)
            action.deleteLater()
        self.setStatusBar(QStatusBar())
        self.current_id = None
        self._create_ui()
        self._make_actions()
        self.splitter.setSizes(sizes)
        self._refresh_list()
        if uid:
            self._select_id(uid)
        self.tabs.setCurrentIndex(step)
        (roi, min_area, closing, density, mask, marks, seed, brush, search, snap) = options
        self.clamp_roi.setChecked(roi)
        self.min_area.setValue(min_area)
        self.morph_size.setValue(closing)
        self.global_density.setValue(density)
        self.show_mask.setChecked(mask)
        self.show_marks.setChecked(marks)
        self.seed_brush.setValue(seed)
        self.brush.setValue(brush)
        self.search_samples.setText(search)
        self.geometry_panel.snap.setChecked(snap)
        self.ai_log.setPlainText(log)
        self.canvas.zoom, self.canvas.offset = zoom, offset
        if selected:
            self.canvas.geometry.select(selected)
        self._update_results()
        self._update_status()

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
        if s and len(s.cal_points)==3:
            return  # siatka 10×10 ma stały wymiar; nie zmieniaj macierzy
        if s and s.known_mm != value:
            self.canvas.begin_edit()
            self.canvas.known_mm = value
            self._canvas_changed()

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
        if mode in (ImageCanvas.CAL, ImageCanvas.GRID_CAL):
            self.tabs.setCurrentWidget(self.calibration_tab)
        elif mode in (ImageCanvas.ROI, ImageCanvas.FG, ImageCanvas.BG):
            self.tabs.setCurrentWidget(self.mask_settings_tab)
            self.canvas.brush_px = self.seed_brush.value()
        else:
            self.tabs.setCurrentWidget(self.analysis_tab)
            self.canvas.brush_px = self.brush.value()
        self.canvas.set_mode(mode)
        if mode == ImageCanvas.GRID_CAL:
            self.measure_hint.setText(tr('Siatka 10×10 mm: narożnik kratki → punkt sąsiedni w osi X → punkt sąsiedni w osi Y.'))
        if mode == ImageCanvas.CAL:
            self.measure_hint.setText(tr('Kalibracja: wskaż dwa różne punkty znanej długości na zdjęciu.'))
            self.statusBar().showMessage(tr('Wskaż dwa punkty kalibracyjne na zdjęciu.'), 6000)

    def _canvas_status(self, message):
        self.statusBar().showMessage(message, 6000)
        if self.canvas.mode == ImageCanvas.MEASURE:
            self.measure_hint.setText(message)

    def _measurement_type_changed(self):
        if self.canvas.mode == ImageCanvas.MEASURE:
            self.canvas.set_mode(ImageCanvas.PAN)
        self.measure_hint.setText(tr(MEASUREMENT_TYPES[self.measure_type.currentData()][2]))

    def _start_measurement(self):
        if not self._sample() or (self.process and self.process_kind == 'ai'):
            return
        self.tabs.setCurrentIndex(4)
        if self.canvas.start_measurement(self.measure_type.currentData()):
            self.geometry_panel.mode.setText(tr('Pomiar grubości — wskaż punkty zgodnie z instrukcją.'))

    def _cancel_measurement(self):
        if self.tabs.currentIndex() == 4 and self.canvas.mode == ImageCanvas.GEOMETRY:
            self.canvas.geometry.start("select")
        if self.canvas.mode == ImageCanvas.MEASURE:
            self.geometry_panel.pan()
            self.measure_hint.setText(tr('Anulowano pomiar. Wybierz wymiar i wskaż punkty, aby rozpocząć ponownie.'))

    def _measurement_finished(self):
        item = self.canvas.measurements[-1]
        value = measurement_mm(item, self.canvas.mm_per_px, self.canvas.calibration_matrix)
        self.canvas.geometry.start('select')
        message = tr('Zapisano {} = {} mm. Możesz rozpocząć kolejny pomiar.').format(f"{item['kind']}", f'{value:.3f}')
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
            try:
                value = measurement_mm(item, sample.mm_per_px, sample.calibration_matrix())
                error = tr('powtórz pomiar') if item['kind'] == 'a' else tr('brak skali')
            except ValueError:
                value, error = None, tr('nieważna geometria')
            for column, text in enumerate((str(index+1), item['kind'],
                                          error if value is None else f'{value:.3f}')):
                cell = QTableWidgetItem(text)
                cell.setToolTip(tr(MEASUREMENT_TYPES[item['kind']][0]))
                self.measure_table.setItem(index, column, cell)
        self._measurement_selection_changed()

    def add_images(self):
        if self.process and self.process_kind=='ai':
            return
        files,_=QFileDialog.getOpenFileNames(self,tr('Dodaj zdjęcia makroskopowe'),'',
                        tr('Obrazy (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)'))
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
                QMessageBox.warning(self,tr('Nie udało się wczytać obrazu'),str(exc))
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
        self.canvas.geometry.flush_pending()
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
            self.canvas.geometry.items=deepcopy(s.geometry_objects)
            self.canvas.history=list(s.undo_history)
            self.canvas.future=list(s.redo_history)
            self.canvas.set_mode(ImageCanvas.GEOMETRY if self.tabs.currentIndex() == 4 else ImageCanvas.PAN)
            self.canvas.invalidate_layers()
            self.sample_name.setText(s.name)
            self.source_name.setText(s.source_name)
            self.known.setValue(s.known_mm)
            self.density.setValue(s.density)
            self.image_header.setText(f'{s.name} · {s.source_name} · {s.dimensions[1]}×{s.dimensions[0]} px')
            self._update_scale()
            self._update_results()
            self.measure_hint.setText(tr(MEASUREMENT_TYPES[self.measure_type.currentData()][2])
                                     if s.mm_per_px else tr('Najpierw wykonaj kalibrację zdjęcia.'))
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
        if (s.cal_points, s.known_mm) != (pts, self.canvas.known_mm):
            s.cal_points, s.known_mm = pts, self.canvas.known_mm
            s.recalc_scale()
            changed=True
        if not pts and s.mm_per_px != self.canvas.mm_per_px:
            s.mm_per_px = self.canvas.mm_per_px
            changed = True
        geometry_changed = (s.geometry_objects != self.canvas.geometry.items or
                            s.measurements != self.canvas.measurements)
        if geometry_changed:
            s.geometry_objects = deepcopy(self.canvas.geometry.items)
            s.measurements = deepcopy(self.canvas.measurements)
        for key in ('roi_start','roi_end'):
            value=getattr(self.canvas,key)
            if getattr(s,key)!=value:
                setattr(s,key,value)
                changed=True
        s.undo_history=list(self.canvas.history)
        s.redo_history=list(self.canvas.future)
        if changed:
            if s.state==STATUS_APPROVED:
                s.approved_at=''
            s.state=(STATUS_REVIEW if np.any(self.canvas.mask)
                     else (STATUS_READY if s.ready() else STATUS_NEW))
        if changed or geometry_changed:
            s.revision += 1
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
        s = self._sample()
        if s and pixels > 0:
            if len(self.canvas.cal_points) == 3 and s.known_mm != 10.0:
                # Zmień wymiar fizyczny dopiero po trzecim punkcie; samo
                # rozpoczęcie kalibracji nie może unieważniać starego wyniku.
                self.canvas.known_mm = 10.0
                self._loading = True
                try:
                    self.known.setValue(10.0)
                finally:
                    self._loading = False
            self._canvas_changed()
            self.measure_hint.setText(tr('Kalibracja gotowa. ')
                                     + tr(MEASUREMENT_TYPES[self.measure_type.currentData()][2]))

    def _delete_calibration(self):
        s=self._sample()
        if not s or (self.process and self.process_kind=='ai'):
            return
        answer=QMessageBox.question(self,tr('Usuń kalibrację'),
            tr('Usunąć kalibrację bieżącej próbki?\nOryginalne zdjęcie, maska i pomiary zostaną zachowane.\nDo wykonania nowych wyników w mm konieczna będzie ponowna kalibracja.'),
            QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
        if answer!=QMessageBox.StandardButton.Yes:
            return
        self.canvas.reset_calibration()
        self._update_scale()
        self._update_results()
        self._refresh_list()
        self._update_status()
        self.statusBar().showMessage(tr('Kalibrację usunięto. Wróć do niej lub użyj Ctrl+Z.'),5000)

    def _start_grid_calibration(self):
        if not self._sample():
            return
        self._tool(ImageCanvas.GRID_CAL)
        self.statusBar().showMessage(tr('Siatka: wskaż narożnik, sąsiednie przecięcie w osi X, następnie w osi Y (po 10 mm).'), 15000)

    def _update_scale(self):
        s=self._sample()
        scale = s.mm_per_px if s else None
        self.canvas.mm_per_px = scale
        self.canvas.known_mm = s.known_mm if s else 10.0
        if s and self.known.value() != s.known_mm:
            self.known.blockSignals(True)
            self.known.setValue(s.known_mm)
            self.known.blockSignals(False)
        self.canvas.calibration_matrix = s.calibration_matrix() if s else None
        self.canvas.update()
        self.measurement_group.setEnabled(bool(scale) and not (self.process and self.process_kind == 'ai'))
        self.known.setEnabled(not (s and len(s.cal_points)==3))
        self.reset_cal_btn.setEnabled(bool(s and s.mm_per_px))
        if not s or not s.mm_per_px:
            self.scale_lbl.setText(tr('Brak kalibracji'))
        else:
            if len(s.cal_points) == 3:
                self.scale_lbl.setText(f'{tr('Siatka')} {s.known_mm:g}×{s.known_mm:g} mm (2D) · 1 px² = {s.area_per_pixel():.9f} mm² · s_eq={s.mm_per_px:.6f} mm/px')
            else:
                self.scale_lbl.setText(f'{s.mm_per_px:.8f} mm/px · {1/s.mm_per_px:.2f} px/mm')

    def _update_results(self):
        self._update_measurements()
        self.geometry_panel.refresh()
        s=self._sample()
        if not s:
            for lbl in (self.lbl_px,self.lbl_area,self.lbl_vol,self.lbl_gpm,self.lbl_kgpm):
                lbl.setText('—')
            self.lbl_status.setText(tr('Status próbki: —'))
            self._update_correction_workflow(None)
            return
        mask=self.canvas.mask if self.current_id==s.uid and self.canvas.mask is not None else s.mask()
        area_per_pixel = s.area_per_pixel()
        m=metrics(mask,s.mm_per_px,s.density,area_per_pixel)
        self.lbl_px.setText(str(m['px2']))
        missing = (tr('— (najpierw utwórz maskę)') if not m['px2'] else
                   tr('— (najpierw kalibracja)') if area_per_pixel is None else '')
        for label,key,digits in [(self.lbl_area,'area_mm2',4),(self.lbl_vol,'volume_cm3_m',4),
                                 (self.lbl_gpm,'mass_g_m',4),(self.lbl_kgpm,'mass_kg_m',6)]:
            label.setText(missing or f'{m[key]:.{digits}f}')
        self.lbl_status.setText(tr('Status próbki: ') + tr(STATUS_DISPLAY.get(s.state, ('?', s.state))[1]))
        self._update_correction_workflow(s, area_per_pixel is not None, m['px2'] > 0)

    def _update_correction_workflow(self, sample, calibrated=False, has_mask=False):
        analyzing = self.process is not None and self.process_kind == 'ai'
        prepared = sample is not None and (
            sample.roi() is not None or bool(np.any(self.canvas.fg))
        )
        self.review_group.setEnabled(bool(sample and not analyzing))
        self.mask_settings_tab.setEnabled(not analyzing)
        self.language_selector.setEnabled(self.process is None)
        if sample is None:
            prep_message = tr('Dodaj zdjęcie, aby przygotować segmentację.')
        elif prepared:
            prep_message = tr('Wskazówki zapisane. Kliknij „Dalej”, aby przejść do Analizy i uruchomić SAM.')
        else:
            prep_message = tr('Obejmij spoinę prostokątem ROI. Zaznacz FG wewnątrz spoiny i BG poza nią.')
        if sample and not calibrated:
            prep_message += tr(' Kalibracja jest potrzebna do obliczenia pola w mm².')
        self.preparation_status.setText(prep_message)
        self.approve_btn.setEnabled(bool(sample and calibrated and has_mask and
                                         not analyzing and sample.state != STATUS_APPROVED))
        if sample is None:
            message = tr('Dodaj zdjęcie, aby utworzyć maskę spoiny.')
        elif analyzing:
            message = tr('Trwa segmentacja. Po jej zakończeniu sprawdź maskę spoiny.')
        elif sample.state == STATUS_APPROVED and calibrated and has_mask:
            message = tr('Maska spoiny sprawdzona i zatwierdzona. Wynik pola znajdziesz w zakładce Wynik.')
        elif has_mask and calibrated:
            message = tr('Kalibracja i maska są gotowe. Sprawdź wypełniony obszar spoiny i kliknij „Zatwierdź pomiar pola”.')
        elif has_mask:
            message = tr('Maska jest gotowa. Ustaw skalę w zakładce Kalibracja, a potem zatwierdź pomiar.')
        elif prepared:
            message = tr('Uruchom analizę SAM. Po segmentacji sprawdź maskę i popraw ją w tej zakładce.')
            if not calibrated:
                message += tr(' Do zatwierdzenia potrzebna jest też kalibracja.')
        else:
            message = tr('Przygotuj ROI lub FG w Ustawieniach maski albo wypełnij spoinę wielokątem.')
            if not calibrated:
                message += tr(' Do zatwierdzenia potrzebna jest też kalibracja.')
        self.correction_status.setText(message)

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
                    tr('{} | {} | Status: {}').format(f'{s.name}', f'{s.source_name}', tr(display[1])))
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
        if QMessageBox.question(self,tr('Usuń próbkę'),tr('Usunąć {} z projektu?\nZdjęcie źródłowe pozostanie na dysku.').format(f'{s.name}'),
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
        self.canvas.geometry.items=[]
        self.canvas.geometry.selected=None
        self.canvas.cal_points=[]
        self.canvas.cancel_pending()
        self.canvas.update()
        self._loading=True
        self.sample_name.clear()
        self.source_name.setText('—')
        self._loading=False
        self.image_header.setText(tr('Dodaj zdjęcie lub otwórz projekt'))
        self._update_scale()
        self.measure_hint.setText(tr('Najpierw wykonaj kalibrację zdjęcia.'))
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
        self.statusBar().showMessage(tr('Gęstość {} g/cm³ zastosowano do {} próbek').format(f'{value:.4f}', f'{len(self.project.samples)}'),5000)

    def copy_settings(self):
        if self.process and self.process_kind=='ai':
            return
        self._commit_current()
        src=self._sample()
        do_cal=self.copy_calibration.isChecked()
        do_roi=self.copy_roi.isChecked()
        if not src or len(self.project.samples)<2 or not (do_cal or do_roi):
            return
        if do_cal and (not src.mm_per_px or len(src.cal_points) not in (2,3)):
            QMessageBox.warning(self,tr('Brak kalibracji'),
                tr('Najpierw poprawnie skalibruj próbkę źródłową. Historyczna sama liczba mm/px nie nadaje się do kopiowania.'))
            return
        if QMessageBox.question(self,tr('Zastosuj do całej serii'),
                tr('Kopiować do pozostałych {} próbek?\nKalibracja: {}\nROI: {}\n\nKopiowanie skali jest miarodajne WYŁĄCZNIE przy jednakowej skali i geometrii fotografowania. Różne próbki należy sprawdzić osobno.').format(f'{len(self.project.samples) - 1}', f"{('TAK' if do_cal else 'NIE')}", f"{('TAK' if do_roi else 'NIE')}"),
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
            return
        skipped=[]
        for s in self.project.samples:
            if s.uid==src.uid:
                continue
            sy,sx=src.dimensions
            dy,dx=s.dimensions
            changed=False
            if do_cal:
                # Never transfer a 1D scale to an image with different aspect ratio;
                # 2D grid can be rescaled, but physical equivalence remains the user's duty.
                if len(src.cal_points)==2 and abs(dx/sx-dy/sy)>1e-6:
                    skipped.append(s.name)
                else:
                    s.known_mm=src.known_mm
                    s.cal_points=[[p[0]*dx/sx,p[1]*dy/sy] for p in src.cal_points]
                    s.recalc_scale()
                    changed=True
            if do_roi:
                s.roi_start,s.roi_end=scaled_roi(src.roi_start,src.roi_end,src.dimensions,s.dimensions)
                changed=True
            if changed:
                if s.state==STATUS_APPROVED:
                    s.state=STATUS_REVIEW
                    s.approved_at=''
                s.revision+=1
                self.project.mark_dirty()
        self._refresh_list()
        self._update_status()
        if skipped:
            QMessageBox.warning(self,tr('Pominięto skalę'),
                tr('Pominięto skalę 1D dla różnych proporcji zdjęć: ')+', '.join(skipped[:15]))
        self.statusBar().showMessage(tr('Ustawienia zastosowano. Każdą skalę zweryfikuj na siatce.'),6000)

    def _clear_mask(self):
        if self._sample() and QMessageBox.question(self,tr('Wyczyść maskę'),tr('Na pewno wyczyścić aktualną maskę?'),
             QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:
            self.canvas.clear_mask()

    def approve(self):
        if self.process is not None and self.process_kind == 'ai':
            return
        self._commit_current()
        s=self._sample()
        if not s or s.state == STATUS_APPROVED:
            return
        if s.area_per_pixel() is None or not np.any(self.canvas.mask):
            self._update_results()
            self.statusBar().showMessage(self.correction_status.text(), 8000)
            return
        s.state=STATUS_APPROVED
        s.error=''
        s.approved_at=now_iso()
        s.revision+=1
        self.project.mark_dirty()
        self._refresh_list()
        self._update_results()
        self._update_status()
        self.statusBar().showMessage(tr('Zatwierdzono wynik pola spoiny: {}.').format(f'{s.name}'), 5000)

    # ------------------ projekty ------------------
    def _update_status(self):
        name=Path(self.project.path).name if self.project.path else tr('Nowy projekt')
        star=f' • {tr('niezapisane zmiany')}' if self.project.dirty else ''
        self.setWindowTitle(f'WeldVision AI 3.5.0 — {name}{star}')
        self.status_label.setText(tr('{} próbek · {}').format(f'{len(self.project.samples)}', tr('niezapisane zmiany' if self.project.dirty else 'zapisane')))
        self.action_save.setEnabled(bool(self.project.samples))

    def _save_path(self,dest,auto=False):
        self.canvas.geometry.flush_pending()
        self._commit_current()
        try:
            save_project(self.project,dest,backup=not auto,mark_clean=not auto)
            if auto:
                self.statusBar().showMessage(tr('Zapisano kopię odzyskiwania'),3000)
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
                self.statusBar().showMessage(tr('Zapisano projekt: {}').format(f'{dest}'),5000)
            return True
        except Exception as exc:
            if not auto:
                QMessageBox.critical(self,tr('Nie udało się zapisać'),str(exc))
            elif str(exc)!=self._last_autosave_error:
                self._last_autosave_error=str(exc)
                self.statusBar().showMessage(tr('Błąd autozapisu: ')+str(exc),9000)
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
        dest,_=QFileDialog.getSaveFileName(self,tr('Zapisz projekt'),suggested,tr('Projekt WeldVision (*.weldproj)'))
        if not dest:
            return False
        if not dest.lower().endswith('.weldproj'):
            dest+='.weldproj'
        return self._save_path(dest)

    def _guard_dirty(self):
        self._commit_current()
        if not self.project.dirty:
            return True
        answer=QMessageBox.warning(self,tr('Niezapisane zmiany'),
             tr('Projekt zawiera niezapisane zmiany. Co chcesz zrobić?'),
             QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,
             QMessageBox.StandardButton.Save)
        if answer==QMessageBox.StandardButton.Cancel:
            return False
        if answer==QMessageBox.StandardButton.Save:
            return bool(self.save())
        return True

    def new_project(self):
        if self.process and self.process_kind=='ai':
            QMessageBox.warning(self,tr('Trwa AI'),tr('Zakończ lub anuluj analizę przed zmianą projektu.'))
            return
        if not self._guard_dirty():
            return
        old=self.project
        self._loading=True
        try:
            self.project=Project()
            self.ai_model.setCurrentText(DEFAULT_MODEL)
            self.ai_device.setCurrentIndex(0)
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
            QMessageBox.warning(self,tr('Trwa AI'),tr('Anuluj analizę przed otwarciem innego projektu.'))
            return
        if not self._guard_dirty():
            return
        dest,_=QFileDialog.getOpenFileName(self,tr('Otwórz projekt'),'',
                                            tr('Projekt WeldVision (*.weldproj)'))
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
                answer=QMessageBox.question(self,tr('Znaleziono nowszy autozapis'),
                    tr('Znaleziono nowszą kopię odzyskiwania tego projektu. Przywrócić?\nZapisz później Ctrl+S, aby zaktualizować oryginalny projekt.'),
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
            QMessageBox.critical(self,tr('Nie można otworzyć projektu'),str(exc))
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
            answer=QMessageBox.question(self,tr('Odzyskiwanie sesji'),
                   tr('Znaleziono automatycznie zapisany projekt. Przywrócić ostatnią sesję?'),
                   QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            if answer==QMessageBox.StandardButton.Yes:
                self.open_project_path(str(recovery))

    def _cleanup_autosave_on_save(self):
        pass

    def export_all(self):
        if not self.project.samples:
            return
        self._commit_current()
        dest=QFileDialog.getExistingDirectory(self,tr('Folder eksportu wyników'))
        if not dest:
            return
        try:
            out=export_results(self.project,dest)
            QMessageBox.information(self,tr('Zakończono eksport'),
                 tr('Wyniki zapisano w nowym folderze:\n{}\n\nExcel: wyniki_zbiorcze.xlsx\nCSV: wyniki_zbiorcze.csv').format(f'{out}'))
        except Exception as exc:
            QMessageBox.critical(self,tr('Błąd eksportu'),str(exc))

    def show_results_table(self):
        if not self.project.samples:
            return
        self._commit_current()
        # Separate modal table dialog, responsive and easy copy via selection
        from PyQt6.QtWidgets import QDialog
        dialog=QDialog(self)
        dialog.setWindowTitle(tr('WeldVision AI — wyniki wszystkich próbek'))
        dialog.resize(1070,550)
        lay=QVBoxLayout(dialog)
        fields=[tr('Próbka'),tr('Status'),tr('Pole [mm²]'),tr('Gęstość [g/cm³]'),tr('Masa [kg/m]'),tr('Model AI')]
        table=QTableWidget(len(self.project.samples),len(fields))
        table.setHorizontalHeaderLabels(fields)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i,s in enumerate(self.project.samples):
            m=s.summary()
            vals=[s.name,tr(STATUS_DISPLAY.get(s.state,('',s.state))[1]),
                  '—' if m['pole_mm2'] is None else f'{m["pole_mm2"]:.4f}',
                  f'{s.density:.4f}', '—' if m['masa_kg_m'] is None else f'{m["masa_kg_m"]:.6f}', s.model_id]
            for j,v in enumerate(vals):
                table.setItem(i,j,QTableWidgetItem(v))
        lay.addWidget(table)
        b=QPushButton(tr('Zamknij'))
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
                skipped.append(s.name+tr(' (brak ROI i FG)'))
                continue
            tasks.append({'uid':s.uid,'revision':s.revision,'image_path':s.image_path,
                          'roi':roi,'pos':pos,'neg':neg})
        return tasks,skipped

    def start_ai(self,batch,mode='sam'):
        if self.process:
            QMessageBox.information(self,tr('Analiza AI'),tr('Inne zadanie już działa.'))
            return
        if not self.project.samples:
            return
        if not batch and self._sample() and self._sample().state==STATUS_APPROVED:
            if QMessageBox.question(self,tr('Zatwierdzony wynik'),
                tr('Wynik jest zatwierdzony. Ponowna segmentacja zastąpi jego maskę. Kontynuować?'),
                QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                return
        tasks,skipped=self._prepare_tasks(batch)
        if not tasks:
            QMessageBox.information(self,tr('Analiza AI'),
                tr('Brak zdjęć gotowych do analizy. Narysuj ROI lub FG na co najmniej jednej próbce.'))
            return
        if batch:
            message=(tr('Gotowych: {}. Pominiętych: {}.\nZatwierdzone wyniki zostaną zachowane.\nRozpocząć analizę wsadową?').format(f'{len(tasks)}', f'{len(skipped)}'))
            if QMessageBox.question(self,tr('Analiza wsadowa'),message,
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
        proc_env.insert('WELDVISION_LANGUAGE', self.language)
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
            self.ai_batch_btn.setEnabled(False)
            self.action_ai.setEnabled(False)
            self.action_cancel.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.progress.setValue(0)
            self.progress.show()
        self.tabs.setCurrentWidget(self.analysis_tab)
        self._update_results()
        self._append_log(tr('Interpreter procesu: ')+self.worker_python)
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
            lines.append('CUDA: '+(tr('TAK') if msg.get('cuda') else tr('NIE')))
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
                self.reported_errors.append(tr('{}: dane zostały zmienione podczas analizy — wynik pominięty').format(f'{s.name}'))
                return
            try:
                raw=Path(msg['path']).read_bytes()
                mask=from_png(raw,s.dimensions)
                if not np.any(mask):
                    raise ValueError(tr('Segmentacja nie znalazła spoiny. Sprawdź ROI i znaczniki FG/BG.'))
                raw_png=png_bytes(mask)
                settings=self.active_job_settings or {}
                mask=clean_mask(mask,settings.get('min_area',0),settings.get('morph_size',0))
                if settings.get('limit_roi',True):
                    mask=clip_mask_roi(mask,s.roi())
                if not np.any(mask):
                    raise ValueError(tr('Segmentacja dała pustą maskę po ograniczeniu do ROI lub filtracji. Sprawdź ROI, FG/BG i ustawienia w zakładce Analiza.'))
                s.raw_png=raw_png
                s.mask_png=png_bytes(mask)
                s.method=msg.get('method','SAM')
                s.model_id=settings.get('model_id','') if s.method=='SAM' else ''
                s.min_area=settings.get('min_area',0)
                s.close_size=settings.get('morph_size',0)
                s.analyzed_at=now_iso()
                s.approved_at=''
                s.error=''
                s.state=STATUS_REVIEW
                s.revision+=1
                self.project.mark_dirty()
                if s.uid==self.current_id:
                    self._loading=True
                    self.canvas.begin_edit()
                    self.canvas.mask=mask.copy()
                    self.canvas.invalidate_layers()
                    self.show_mask.setChecked(True)
                    self.show_marks.setChecked(False)
                    self._loading=False
                    self._update_results()
                self._refresh_list()
                self._update_status()
                if msg.get('total'):
                    self.progress.setValue(int(100*msg['index']/msg['total']))
                self._append_log(tr('Zapisano maskę: {}').format(f'{s.name}'))
            except Exception as e:
                self.reported_errors.append(f'{s.name}: {e}')
        elif kind=='sample_error':
            s=self.project.get(msg.get('uid'))
            if s:
                s.error=msg['error']
                if not np.any(s.mask()):
                    s.state=STATUS_ERROR
                s.revision+=1
                self.project.mark_dirty()
                self._refresh_list()
            self.reported_errors.append(f'{s.name if s else msg.get("uid")}: {msg.get("error")}')
            self._append_log(tr('Błąd próbki: ')+msg.get('error',''))
        elif kind=='fatal':
            self.reported_errors.append(msg.get('error',tr('Nieznany błąd')))
            self._append_log(tr('Błąd procesu: ')+msg.get('error',''))
        elif kind=='finished':
            self.process_done=True
            self._append_log(tr('Zakończono: {}/{}').format(f"{msg.get('processed', 0)}", f"{msg.get('total', 0)}"))

    def _process_error(self,error):
        self._append_log(tr('Błąd uruchomienia procesu AI: {}').format(f'{error}'))
        if error == QProcess.ProcessError.FailedToStart and self.process:
            QMessageBox.warning(self,tr('Nie można uruchomić AI'),
                tr('Nie udało się uruchomić procesu roboczego przez interpreter:\n')+self.worker_python)
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
            self._append_log(tr('Proces zakończył się kodem {}: {}').format(f'{code}', f'{reason}'))
            if was_ai:
                log=self._recovery_dir()/'weldvision_ai_error.log'
                try:
                    log.write_text(reason+'\n\n'+stderr,encoding='utf-8')
                except OSError:
                    pass
                QMessageBox.warning(self,tr('Błąd segmentacji'),
                    tr('Analiza zakończyła się niepowodzeniem, ale aplikacja i wyniki pozostają dostępne.\n\n')
                    +reason[:950]+f'\n\nLog: {log.name}')
        elif self.reported_errors and was_ai:
            QMessageBox.warning(self,tr('Analiza zakończona z uwagami'),'\n'.join(self.reported_errors[:8]))
        if was_ai:
            self.canvas.setEnabled(True)
            for widget in (self.sample_name,self.density,self.known,self.global_density,
                           self.ai_model,self.ai_device,self.clamp_roi,self.min_area,self.morph_size):
                widget.setEnabled(True)
            self.add_button.setEnabled(True)
            self.remove_button.setEnabled(True)
            self.copy_setup.setEnabled(True)
            self.ai_selected_btn.setEnabled(True)
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
            self._append_log(tr('Anulowanie analizy...'))
            self.process.kill()  # osobny proces można przerwać bez niszczenia GUI

    # ------------------ zamykanie ------------------
    def closeEvent(self,event):
        # Dwa potwierdzenia, lecz niczego nie przerywamy przed końcową zgodą.
        if self.process:
            answer=QMessageBox.question(self,tr('Zamknij WeldVision AI'),
                 tr('Trwa proces AI lub diagnostyka. Przerwać go i zamknąć program?'),
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
