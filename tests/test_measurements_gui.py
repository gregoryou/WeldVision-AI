import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import cv2
import numpy as np
import pytest

pytest.importorskip('PyQt6')
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from weldvision.canvas import ImageCanvas
from weldvision.core import load_project, save_project, image_write
from weldvision.gui import MainWindow
from weldvision.measurements import measurement_mm


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    paths = []
    for index in range(2):
        path = tmp_path/f'sample{index}.png'
        image_write(path, np.full((240, 320, 3), 120, np.uint8))
        paths.append(str(path))
    win = MainWindow()
    win._check_recovery = lambda: None
    win.add_paths(paths)
    win.show()
    app.processEvents()
    win.canvas.zoom = 1
    win.canvas.offset = QPointF(0, 0)
    yield win
    win.autosave_timer.stop()
    win.project.dirty = False
    win.close()
    win.deleteLater()
    app.processEvents()


def click(win, x, y, button=Qt.MouseButton.LeftButton):
    pos = win.canvas.image_to_widget((x, y)).toPoint()
    QTest.mouseClick(win.canvas, button, pos=pos)
    QApplication.processEvents()


def calibrate(win):
    win.tabs.setCurrentIndex(2)
    QTest.mouseClick(win.calibration_button, Qt.MouseButton.LeftButton)
    assert win.tabs.currentIndex() == 0
    assert win.canvas.mode == ImageCanvas.CAL
    click(win, 10, 10)
    assert not win.measure_button.isEnabled()
    click(win, 110, 10)
    assert win._sample().mm_per_px == pytest.approx(.1)
    assert win.measure_button.isEnabled()
    assert win.canvas.mode == ImageCanvas.PAN


def measure(win, kind, points):
    win.measure_type.setCurrentIndex(win.measure_type.findData(kind))
    QTest.mouseClick(win.measure_button, Qt.MouseButton.LeftButton)
    assert win.canvas.mode == ImageCanvas.MEASURE
    for x, y in points:
        click(win, x, y)


def test_calibrate_measure_navigate_save_and_recalibrate(window, tmp_path):
    win = window
    assert not win.measure_button.isEnabled()
    calibrate(win)
    measure(win, 't1', [(190, 30), (190, 80)])
    measure(win, 't2', [(220, 30), (250, 70)])
    measure(win, 'a', [(20, 20), (20, 120), (120, 20)])
    assert win.tabs.currentIndex() == 0
    assert win.measure_table.rowCount() == 3
    sample = win._sample()
    assert measurement_mm(sample.measurements[0], sample.mm_per_px) == pytest.approx(5)
    assert measurement_mm(sample.measurements[1], sample.mm_per_px) == pytest.approx(5)
    assert measurement_mm(sample.measurements[2], sample.mm_per_px) == pytest.approx(50**.5)
    assert not np.any(win.canvas.mask)
    win.next()
    assert not win.canvas.measurements
    assert not win.measure_button.isEnabled()
    win.previous()
    assert win.measure_table.rowCount() == 3
    win.known.setValue(20)
    assert win.measure_table.item(0, 2).text() == '10.000'
    save_project(win.project, tmp_path/'test.weldproj')
    restored = load_project(tmp_path/'test.weldproj')
    try:
        assert restored.samples[0].measurements == sample.measurements
    finally:
        restored.close()


def test_delete_undo_redo_and_cancel(window):
    win = window
    calibrate(win)
    measure(win, 't1', [(180, 30), (180, 60)])
    win.canvas.undo()
    assert not win._sample().measurements
    win.canvas.redo()
    assert len(win._sample().measurements) == 1
    win.measure_table.selectRow(0)
    QTest.mouseClick(win.remove_measure_button, Qt.MouseButton.LeftButton)
    assert not win._sample().measurements
    win.canvas.undo()
    assert len(win._sample().measurements) == 1
    measure(win, 'a', [(20, 20)])
    QTest.keyClick(win, Qt.Key.Key_Escape)
    assert not win.canvas.measure_points
    assert len(win._sample().measurements) == 1
    assert win.canvas.mode == ImageCanvas.PAN


def test_invalid_points_zoom_pan_and_recalibration_undo(window):
    win = window
    calibrate(win)
    # Identical endpoints are rejected; the next attempt starts cleanly.
    measure(win, 't1', [(80, 30), (80, 30)])
    assert not win._sample().measurements
    assert not win.canvas.measure_points
    win.canvas.zoom = 2
    win.canvas.offset = QPointF(31, 44)
    measure(win, 't1', [(80, 40), (80, 80)])
    assert measurement_mm(win._sample().measurements[0], win._sample().mm_per_px) == pytest.approx(4)
    win.calibration_button.click()
    click(win, 10, 10)
    click(win, 60, 10)
    assert win.measure_table.item(0, 2).text() == '8.000'
    win.canvas.undo()
    assert not win.measure_button.isEnabled()
    win.canvas.undo()
    assert win.measure_button.isEnabled()
    assert win.measure_table.item(0, 2).text() == '4.000'
