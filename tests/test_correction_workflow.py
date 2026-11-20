"""Exercise segmentation and approval through the same controls as the user."""
import os
import json
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import cv2
import numpy as np
import pytest
from PyQt6.QtCore import QSettings, QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QInputDialog, QMessageBox, QPlainTextEdit

from weldvision.canvas import ImageCanvas
from weldvision.core import STATUS_APPROVED, STATUS_READY, STATUS_REVIEW, from_png, image_write, png_bytes
from weldvision.gui import MainWindow


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from weldvision import gui
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    monkeypatch.setattr(gui, 'QSettings', lambda *_: settings)
    monkeypatch.setattr(MainWindow, '_check_recovery', lambda self: None)
    notes = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: notes.append(args[2]))
    img = np.full((250, 320, 3), 180, np.uint8)
    polygon = np.array([(109, 80), (233, 177), (102, 177)], np.int32)
    cv2.fillPoly(img, [polygon], (65, 110, 220))
    photo = tmp_path / 'spoina.png'
    image_write(photo, img)
    win = MainWindow()
    win.autosave_timer.stop()
    win.show()
    win.add_paths([str(photo)])
    win.tabs.setCurrentWidget(win.mask_settings_tab)
    app.processEvents()
    win.canvas.fit()
    yield win, notes
    if win.process is not None:
        win.cancel_ai()
        if win.process is not None:
            win.process.waitForFinished(1000)
    if win.job is not None:
        win.job.cleanup()
        win.job = None
    if win.language != 'pl':
        win.change_language('pl')
    win.project.dirty = False
    win.close()
    app.processEvents()


def point(win, x, y):
    return win.canvas.image_to_widget((x, y)).toPoint()


def click(win, x, y, button=Qt.MouseButton.LeftButton):
    QTest.mouseClick(win.canvas, button, pos=point(win, x, y))


def calibrate(win):
    win._start_grid_calibration()
    for xy in ((20, 20), (120, 20), (20, 120)):
        click(win, *xy)
    win.tabs.setCurrentWidget(win.calibration_tab)


def prepare(win):
    win._tool(ImageCanvas.ROI)
    start, end = point(win, 85, 65), point(win, 250, 200)
    QTest.mousePress(win.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(win.canvas, end)
    QTest.mouseRelease(win.canvas, Qt.MouseButton.LeftButton, pos=end)
    win._tool(ImageCanvas.FG)
    click(win, 131, 141)
    win._tool(ImageCanvas.BG)
    click(win, 223, 110)


def test_wizard_uses_sam_huge_then_edits_and_approves_mask(window, tmp_path, monkeypatch):
    win, notes = window
    calibrate(win)
    assert 'Ustawienia maski' in win.next_step.text()
    win.next_step.click()
    assert win.tabs.currentWidget() is win.mask_settings_tab
    prepare(win)
    sample = win._sample()
    assert sample.state == STATUS_READY
    assert sample.roi() and np.any(sample.mask('fg')) and np.any(sample.mask('bg'))
    assert not np.any(sample.mask())
    assert not win.approve_btn.isEnabled()
    assert 'utwórz maskę' in win.lbl_area.text()
    assert 'Dalej' in win.preparation_status.text()
    from PyQt6.QtWidgets import QPushButton
    assert not any('GrabCut' in button.text() or 'Zatwierdź' in button.text()
                   for button in win.mask_settings_tab.findChildren(QPushButton))
    assert not any('GrabCut' in button.text() for button in win.analysis_tab.findChildren(QPushButton))
    win.next_step.click()
    assert win.tabs.currentWidget() is win.analysis_tab
    win.back_step.click()
    assert win.tabs.currentWidget() is win.mask_settings_tab
    assert np.any(sample.mask('fg')) and np.any(sample.mask('bg'))
    win.next_step.click()

    # Exercise the actual SAM job builder and result handler with a deterministic
    # mask. The model itself is not downloaded or executed by this test.
    captured = {}
    def submit(args, kind):
        captured.update(json.loads(Path(args[-1]).read_text(encoding='utf-8')))
        assert kind == 'ai'
    monkeypatch.setattr(win, '_start_process', submit)
    win.show_mask.setChecked(False)
    win.ai_selected_btn.click()
    assert captured['model_id'] == 'facebook/sam-vit-huge'
    assert captured['mode'] == 'sam'
    task, = captured['tasks']
    assert task['roi'] and task['pos'] and task['neg']
    assert not win.approve_btn.isEnabled()
    mask = np.zeros(sample.dimensions, dtype=np.uint8)
    mask[105:179, 104:188] = 255
    output = tmp_path / 'sam.png'
    output.write_bytes(png_bytes(mask))
    win._handle_worker_message(dict(kind='result', uid=sample.uid, revision=task['revision'],
                                    path=str(output), method='SAM'))
    assert not notes
    assert sample.state == STATUS_REVIEW
    assert sample.mask()[141, 131] == 255
    assert np.count_nonzero(sample.mask()) > 2500
    assert win.show_mask.isChecked()
    assert not win.show_marks.isChecked()
    assert win.tabs.currentWidget() is win.analysis_tab
    win._tool(ImageCanvas.ERASE)
    click(win, 131, 141)
    assert win.tabs.currentWidget() is win.analysis_tab
    assert sample.mask()[141, 131] == 0
    assert from_png(sample.raw_png, sample.dimensions)[141, 131] == 255
    assert win.approve_btn.isEnabled()
    assert not sample.approved_at
    win.approve_btn.click()
    assert sample.state == STATUS_APPROVED
    assert sample.approved_at
    assert not win.approve_btn.isEnabled()
    tasks, skipped = win._prepare_tasks(True)
    assert not tasks and len(skipped) == 1
    win.next_step.click()
    assert win.tabs.currentWidget() is win.results_tab


def test_manual_polygon_requires_calibration_but_not_roi_or_seeds(window):
    win, notes = window
    win._tool(ImageCanvas.POLY)
    assert win.tabs.currentWidget() is win.analysis_tab
    for xy in ((109, 80), (233, 177), (102, 177)):
        click(win, *xy)
    click(win, 115, 174, Qt.MouseButton.RightButton)
    sample = win._sample()
    assert np.count_nonzero(sample.mask()) > 2000
    assert sample.roi() is None
    assert not win.approve_btn.isEnabled()
    assert 'zakładce Kalibracja' in win.correction_status.text()
    calibrate(win)
    assert win.approve_btn.isEnabled()
    win.approve_btn.click()
    assert sample.state == STATUS_APPROVED
    assert not notes


def test_empty_segmentation_leaves_approved_mask_intact(window, tmp_path):
    win, _ = window
    calibrate(win)
    prepare(win)
    win.canvas.mask[120:152, 120:146] = 255
    win.canvas.changed.emit()
    win.approve_btn.click()
    sample = win._sample()
    before = (sample.revision, sample.mask_png, sample.raw_png, sample.approved_at)
    output = tmp_path / 'mask.png'
    mask = np.zeros(sample.dimensions, dtype=np.uint8)
    mask[4:8, 4:8] = 255  # Completely outside the accepted ROI.
    output.write_bytes(png_bytes(mask))
    win._handle_worker_message(dict(kind='result', uid=sample.uid, revision=sample.revision,
                                    path=str(output), method='GrabCut'))
    assert 'pustą maskę' in win.reported_errors[-1]
    assert before == (sample.revision, sample.mask_png, sample.raw_png, sample.approved_at)
    assert sample.state == STATUS_APPROVED
    win._handle_worker_message(dict(kind='sample_error', uid=sample.uid, error='Brak próbek tła'))
    assert sample.state == STATUS_APPROVED
    assert sample.approved_at == before[-1]
    assert sample.mask_png == before[1]


def test_switch_language_preserves_unsaved_project_and_model(window):
    win, _ = window
    calibrate(win)
    prepare(win)
    win.ai_model.setCurrentText('facebook/sam-vit-large')
    project, uid = win.project, win.current_id
    sample = win._sample()
    fg = sample.fg_png
    undo = len(win.canvas.history)
    win.about()
    win.language_selector.setCurrentIndex(win.language_selector.findData('en'))
    assert win.language == 'en'
    assert win.ui_settings.value('language') == 'en'
    assert win.tabs.currentWidget() is win.about_tab
    assert [win.tabs.tabText(i) for i in range(win.tabs.count())] == [
        'Calibration', 'Mask settings', 'Analysis', 'Results', 'Measurements', 'About']
    assert win.project is project and win.current_id == uid and project.dirty
    assert len(win.canvas.history) == undo and sample.fg_png == fg
    assert win.ai_model.currentText() == 'facebook/sam-vit-large'
    assert win.ai_selected_btn.text() == 'Create AI mask — current sample'
    assert win.approve_btn.text() == 'Approve section area'
    assert win.geometry_panel.buttons['comment'].text() == 'Insert comment'
    win.tabs.setCurrentWidget(win.measurement_tab)
    assert win.geometry_panel.line_tool.itemText(
        win.geometry_panel.line_tool.findData('a_contour')) == 'Throat a — contour'


def test_comment_dialog_accepts_input_and_edits_existing_comment(window):
    win, _ = window
    win.tabs.setCurrentWidget(win.measurement_tab)
    panel = win.geometry_panel

    def modal_input(text, expected=''):
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QInputDialog)
        edit = dialog.findChild(QPlainTextEdit)
        assert edit.toPlainText() == expected
        edit.selectAll()
        QTest.keyClicks(edit, text)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()

    panel.buttons['comment'].click()
    QTimer.singleShot(0, lambda: modal_input('Weld toe A'))
    click(win, 130, 140)
    item, = win._sample().geometry_objects
    assert item['style']['custom_label'] == 'Weld toe A'
    QTimer.singleShot(0, lambda: modal_input('Weld toe B', 'Weld toe A'))
    panel.edit()
    updated, = win._sample().geometry_objects
    assert updated['id'] == item['id']
    assert updated['style']['custom_label'] == 'Weld toe B'
    win.canvas.undo()
    assert win._sample().geometry_objects[0]['style']['custom_label'] == 'Weld toe A'


def test_six_click_throat_uses_plate_corner_and_face(window):
    win, _ = window
    calibrate(win)
    win.tabs.setCurrentWidget(win.measurement_tab)
    editor = win.canvas.geometry
    assert editor.start('guided_throat')
    assert 'krok 1/3' in editor.message
    for xy in ((100, 70), (100, 145), (140, 175), (250, 175)):
        click(win, *xy)
    assert 'krok 3/3' in editor.message
    click(win, 100, 95)
    click(win, 180, 175)
    guides = editor.items[:3]
    item = editor.items[3]
    assert item['refs'] == [line['id'] for line in guides]
    result = editor.scene()[item['id']]
    assert result.center == pytest.approx((100, 175), abs=1)
    assert result.value == pytest.approx(8 / 2**.5, abs=.07)
    assert result.value == result.radius
    win.canvas.undo()
    assert not editor.items
