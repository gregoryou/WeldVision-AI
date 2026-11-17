"""Optional Qt smoke test (runs on a machine with PyQt6, also offscreen)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import cv2
import numpy as np
import pytest

PyQt6 = pytest.importorskip('PyQt6')
from PyQt6.QtWidgets import QApplication
from weldvision.gui import MainWindow
from weldvision.core import image_write


def test_navigation_preserves_markers_and_calibration(tmp_path):
    app = QApplication.instance() or QApplication([])
    a = np.full((200,300,3),(120,130,140),np.uint8)
    paths=[]
    for i in range(3):
        p=tmp_path/f'test{i}.png'
        image_write(p,a)
        paths.append(str(p))
    win = MainWindow()
    win._check_recovery=lambda: None
    win.add_paths(paths)
    assert len(win.project.samples)==3
    win.canvas.roi_start=(30,40)
    win.canvas.roi_end=(180,160)
    win.canvas.fg[70:90,70:90]=255
    win.canvas.bg[10:20,10:20]=255
    win.canvas.changed.emit()
    original=win.project.samples[0]
    win.next(); win.next(); win.previous(); win.previous()
    assert win.current_id==original.uid
    assert win.canvas.roi_start==(30,40)
    assert win.canvas.roi_end==(180,160)
    assert np.count_nonzero(win.canvas.fg)==400
    assert np.count_nonzero(win.canvas.bg)==100
    # Explicit manual teardown; do not invoke close() because it prompts save.
    win.autosave_timer.stop()
    win.project.close()
    win.deleteLater()
