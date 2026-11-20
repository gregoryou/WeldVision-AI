"""Exercise the public Qt 'Pomiar' interactions on a known affine grid."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from copy import deepcopy

import numpy as np
import pytest
from PyQt6.QtCore import QPoint, QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

from weldvision.core import image_write
from weldvision.geometry import norm, sub, to_mm
from weldvision.gui import MainWindow
from weldvision.photo_annotations import qimage_to_pillow

LEFT = Qt.MouseButton.LeftButton
RIGHT = Qt.MouseButton.RightButton


@pytest.fixture
def win(tmp_path):
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.autosave_timer.stop()
    w._check_recovery = lambda: None
    p = tmp_path/'trial.png'
    q = tmp_path/'trial2.png'
    image_write(p, np.full((360, 500, 3), 80, np.uint8))
    image_write(q, np.full((360, 500, 3), 72, np.uint8))
    w.resize(1500, 900)
    w.show()
    w.add_paths([str(p), str(q)])
    w.geometry_panel.settings = QSettings(str(tmp_path/'styles.ini'), QSettings.Format.IniFormat)
    w.geometry_panel.user_styles.clear()
    app.processEvents()
    w._start_grid_calibration()
    for pt in ((20, 20), (120, 20), (20, 70)):
        click(w, pt)
    w.tabs.setCurrentIndex(4)
    w.canvas.fit()
    w.canvas.geometry.snap = False
    app.processEvents()
    yield w
    w.project.dirty = False
    w.close()
    app.processEvents()


def widget(win, pt):
    return win.canvas.image_to_widget(pt).toPoint()


def click(win, pt, button=LEFT):
    QTest.mouseClick(win.canvas, button, pos=widget(win, pt))
    QApplication.processEvents()


def drag(win, a, b):
    A, B = widget(win, a), widget(win, b)
    QTest.mousePress(win.canvas, LEFT, pos=A)
    QTest.mouseMove(win.canvas, B)
    QTest.mouseRelease(win.canvas, LEFT, pos=B)
    QApplication.processEvents()


def create(win, kind, *pts, **kwargs):
    editor = win.canvas.geometry
    assert editor.start(kind, **kwargs)
    for pt in pts:
        click(win, pt)
    return editor.items[-1]


def test_live_circle_drag_edit_copy_and_history(win):
    panel, editor = win.geometry_panel, win.canvas.geometry
    panel.buttons['circle'].click()
    click(win, (180, 120))
    QTest.mouseMove(win.canvas, widget(win, (225, 120)))
    items, preview = editor.display_objects()
    assert len(editor.items) == 0 and items[-1]['id'] == preview
    click(win, (225, 120))
    uid = editor.selected
    assert panel.table.rowCount() == 1
    old_radius = editor.scene()[uid].radius
    assert old_radius == pytest.approx(4.5, abs=.14)
    drag(win, (180, 120), (210, 145))
    r = editor.scene()[uid]
    assert r.center == pytest.approx((210, 145), abs=1.1)
    assert r.radius == pytest.approx(old_radius, abs=.13)
    drag(win, r.handles[1], (280, 145))
    assert editor.scene()[uid].radius == pytest.approx(7., abs=.14)
    props = panel.properties
    props.length.setValue(8.25)
    assert editor.scene()[uid].radius != pytest.approx(8.25)
    assert editor.display_objects()[0][0] != editor.items[0]
    props.flush()
    assert editor.scene()[uid].radius == pytest.approx(8.25)
    panel.copy()
    assert len(editor.items) == 2
    win.canvas.undo()
    assert len(editor.items) == 1
    win.canvas.redo()
    assert len(editor.items) == 2


def test_style_live_label_drag_and_undo(win):
    panel, editor = win.geometry_panel, win.canvas.geometry
    circle = create(win, 'circle', (175, 135), (230, 135))
    uid = circle['id']
    before = editor.scene()[uid].radius
    props = panel.properties
    for key, value in {'font_family': 'Times New Roman', 'font_pt': 19., 'line_width': 4.5,
                       'line_color': '#e02034', 'background': 'white',
                       'background_opacity': 62, 'label_y': 12., 'bold': True}.items():
        props.change(key, value)
    assert editor.draft['style']['background'] == 'white'
    assert editor.items[0]['style']['background'] == 'none'
    props.flush()
    assert editor.scene()[uid].radius == before
    assert editor.item(uid)['style']['font_family'] == 'Times New Roman'
    canvas = win.canvas
    canvas.repaint()
    QApplication.processEvents()
    at = editor.labels[uid].center()
    start = canvas.widget_to_image(at)
    assert start is not None
    drag(win, start, (start[0]+40, start[1]+25))
    assert editor.item(uid)['style']['label_x'] == pytest.approx(40, abs=2.)
    canvas.undo()
    assert editor.item(uid)['style']['label_x'] == 0.
    canvas.undo()
    assert editor.item(uid)['style']['background'] == 'none'
    canvas.redo()
    assert editor.item(uid)['style']['background_opacity'] == 62.


def test_snap_intersection_tools_and_geometry_table(win):
    editor = win.canvas.geometry
    a = create(win, 'line', (50, 120), (160, 120))
    b = create(win, 'line', (100, 80), (100, 210))
    p = create(win, 'intersection', (150, 120), (100, 195))
    assert p['refs'] == [a['id'], b['id']]
    root = editor.scene()[p['id']].anchor
    editor.snap = True
    c = create(win, 'circle', (root[0]+2, root[1]+3), (root[0]+45, root[1]+32))
    assert editor.scene()[c['id']].center == root
    editor.snap = False
    rel = create(win, 'perpendicular', (142, 120), (220, 110), (230, 180))
    assert rel['refs'] == [a['id']]
    measured = create(win, 'angle', (145, 120), (100, 190))
    assert editor.scene()[measured['id']].value == pytest.approx(90., abs=1.)
    assert win.geometry_panel.table.rowCount() == 6


def test_scale_zoom_recalibration_no_mask_and_clear(win, monkeypatch):
    editor, canvas = win.canvas.geometry, win.canvas
    scale = create(win, 'scale', (95, 240), length_mm=10.)
    uid = scale['id']
    s = win._sample()
    mat = s.calibration_matrix()
    props = win.geometry_panel.properties
    props.orientation.setValue(90)
    props.flush()
    assert s.calibration_matrix() == mat
    path = editor.scene()[uid].paths[0]
    assert norm(to_mm(sub(*path), mat)) == pytest.approx(10.0)
    start = canvas.image_to_widget(path[0])
    end = canvas.image_to_widget(path[1])
    diff = (end-start).manhattanLength()
    canvas.zoom *= 1.5
    start = canvas.image_to_widget(path[0])
    end = canvas.image_to_widget(path[1])
    assert (end-start).manhattanLength() == pytest.approx(diff*1.5)
    assert editor.scene()[uid].value == 10.
    canvas.fit()
    canvas.mask[90:130, 200:235] = 255
    canvas.changed.emit()
    rgb = qimage_to_pillow(canvas.grab().toImage())
    assert rgb.getpixel(tuple(map(int, (widget(win, (215, 110)).x(), widget(win, (215, 110)).y())))) == (80,80,80)
    new_cal = [tuple(pt) for pt in ((20, 20), (220, 20), (20, 120))]
    canvas.begin_edit()
    canvas.cal_points = new_cal
    canvas.changed.emit()
    assert editor.scene()[uid].value == 10.
    assert norm(sub(*editor.scene()[uid].paths[0])) == pytest.approx(2*norm(sub(*path)), abs=2)
    expected_cal = deepcopy(s.cal_points)
    expected_mask = s.mask().copy()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    win.geometry_panel.clear()
    assert not s.geometry_objects and s.cal_points == expected_cal
    assert np.array_equal(s.mask(), expected_mask)
    canvas.undo()
    assert len(s.geometry_objects) == 1
    canvas.reset_calibration()
    assert not editor.scene()[uid].paths
    canvas.undo()
    assert editor.scene()[uid].value == 10.


def test_copy_style_bulk_and_application_on_series(win):
    panel, editor = win.geometry_panel, win.canvas.geometry
    a = create(win, 'line', (50, 80), (130, 80))
    panel.presets.setCurrentText('Naukowy')
    panel.apply_selected()
    assert editor.item(a['id'])['style']['background'] == 'white'
    panel.copy_style()
    b = create(win, 'line', (170, 115), (245, 115))
    panel.properties.change('signature', 'custom')
    panel.properties.change('custom_label', 'L własna')
    panel.paste_style()
    assert editor.item(b['id'])['style']['font_pt'] == editor.item(a['id'])['style']['font_pt']
    assert editor.item(b['id'])['style']['custom_label'] == 'L własna'
    extra = win.project.samples[1]
    extra.geometry_objects = [deepcopy(a)]
    panel.presets.setCurrentText('Prezentacyjny')
    panel.apply_series()
    assert extra.geometry_objects[0]['style']['line_width'] == 4.
    assert {i['style']['line_width'] for i in editor.items} == {4.}
    assert extra.undo_history
    win.canvas.undo()
    assert editor.item(a['id'])['style']['line_width'] == 1.3
