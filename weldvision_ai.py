#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WeldVision AI 3.2. Proces izolowany używa *tego samego* sys.executable co GUI."""
from __future__ import annotations
import os
import sys
from pathlib import Path

os.environ.setdefault('PYTHONUTF8', '1')
os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')


def main():
    if len(sys.argv)>1 and sys.argv[1] in ('--worker','--diagnose'):
        from weldvision.ai import worker_main
        return worker_main(sys.argv[1:])
    if len(sys.argv)>1 and sys.argv[1] == '--version':
        print('WeldVision AI 3.2')
        return 0
    from PyQt6.QtWidgets import QApplication
    from weldvision.gui import MainWindow
    app=QApplication(sys.argv)
    app.setApplicationName('WeldVision AI')
    app.setStyle('Fusion')
    app.setStyleSheet('''
        QMainWindow { background: #f4f7fb; }
        QTabWidget::pane { border: 1px solid #cbd5e1; background: #fff; }
        QPushButton { padding: 6px 10px; min-height: 26px; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { min-height: 27px; }
        QGroupBox { font-weight: 600; margin-top: 12px; padding-top: 9px; }
        QGroupBox::title { subcontrol-origin: margin; left: 9px; }
        QToolBar { background: #eef2f8; spacing: 5px; padding: 3px; }
    ''')
    win=MainWindow()
    win.show()
    return app.exec()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        import traceback
        error=traceback.format_exc()
        logfile=Path(__file__).resolve().parent/'weldvision_start_error.log'
        logfile.write_text(error,encoding='utf-8')
        print(error,file=sys.stderr)
        # Worker has machine-readable fatal responses in ai.py, but hard import errors go to log.
        sys.exit(2)
