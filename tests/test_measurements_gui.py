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
    win.tabs.setCurrentIndex(0)
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
    if kind=='a_contour':
        click(win,points[-1][0],points[-1][1],Qt.MouseButton.RightButton)


def test_calibrate_measure_navigate_save_and_recalibrate(window, tmp_path):
    win = window
    assert not win.measure_button.isEnabled()
    calibrate(win)
    measure(win, 't1', [(190, 30), (190, 80)])
    measure(win, 't2', [(220, 30), (250, 70)])
    measure(win, 'a_contour', [(20, 20), (20, 120), (120, 20)])
    assert win.tabs.currentIndex() == 4
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
    measure(win, 'a_contour', [(20, 20)])
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
    # Change of two-point calibration commits atomically, so one undo is enough.
    win.canvas.undo()
    assert win.measure_button.isEnabled()
    assert win.measure_table.item(0, 2).text() == '4.000'


def test_grid_calibration_10mm_two_axes_and_roundtrip(window, tmp_path):
    win=window
    win.grid_calibration_button.click()
    assert win.canvas.mode == ImageCanvas.GRID_CAL
    assert win.tabs.currentIndex()==0
    click(win,10,20)
    click(win,110,20)
    click(win,10,70)
    s=win._sample()
    assert len(s.cal_points)==3
    assert s.mm_per_px == pytest.approx(0.02**.5)
    assert s.area_per_pixel()==pytest.approx(.02)
    measure(win,'t1',[(50,20),(50,70)])
    assert win.measure_table.item(0,2).text()=='10.000'
    save_project(win.project,tmp_path/'grid.weldproj')
    p=load_project(tmp_path/'grid.weldproj')
    try:
        assert p.samples[0].area_per_pixel()==pytest.approx(.02)
    finally:
        p.close()


def test_measurement_tab_is_clean_and_reset_is_reversible(window,monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    win=window
    calibrate(win)
    mask=np.zeros_like(win.canvas.mask)
    mask[50:90,70:120]=255
    win.canvas.mask=mask.copy()
    win.canvas.changed.emit()
    old_cal=list(win._sample().cal_points)
    old_mask=win._sample().mask().copy()
    win.tabs.setCurrentIndex(4)
    assert win.canvas.clean_measurement_view
    assert win.canvas.show_scale_bar
    assert np.array_equal(win.canvas.mask, old_mask)
    win.tabs.setCurrentIndex(0)
    assert not win.canvas.clean_measurement_view
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k: QMessageBox.StandardButton.Yes)
    win._delete_calibration()
    assert win._sample().mm_per_px is None
    assert not win.measure_button.isEnabled()
    assert np.array_equal(win._sample().mask(),old_mask)
    win.canvas.undo()
    assert win._sample().cal_points==old_cal
    assert win._sample().mm_per_px == pytest.approx(.1)
    assert np.array_equal(win._sample().mask(),old_mask)


def test_partial_recalibration_never_changes_old_scale(window):
    win=window
    calibrate(win)
    original=list(win._sample().cal_points)
    win.calibration_button.click()
    click(win,30,40)
    assert win._sample().cal_points==original
    assert win._sample().mm_per_px == pytest.approx(.1)
    win.canvas.set_mode(ImageCanvas.PAN)
    win.grid_calibration_button.click()
    click(win,60,30)
    click(win,160,30)
    assert win._sample().cal_points==original
    win.canvas.set_mode(ImageCanvas.PAN)
    assert win._sample().cal_points==original
