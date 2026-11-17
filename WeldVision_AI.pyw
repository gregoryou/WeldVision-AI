"""Launcher bez konsoli: traceback zawsze trafia do pliku logu."""
import sys
from pathlib import Path
try:
    from weldvision_ai import main
    sys.exit(main())
except Exception:
    import traceback
    p=Path(__file__).resolve().parent/'weldvision_start_error.log'
    p.write_text(traceback.format_exc(),encoding='utf-8')
    try:
        from ctypes import windll
        windll.user32.MessageBoxW(0,f'Nie udało się uruchomić WeldVision AI.\nSzczegóły: {p}',
                                  'Błąd WeldVision AI',0x10)
    except Exception:
        pass
