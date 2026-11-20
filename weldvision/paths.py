"""Long absolute paths for Windows file operations."""
import os
from pathlib import Path


def io_path(path):
    path = os.fspath(path)
    if os.name == 'nt' and not Path(path).is_absolute():
        path = os.path.abspath(path)
    if os.name != 'nt' or len(path) < 240 or path.startswith('\\\\?\\'):
        return path
    prefix = '\\\\?\\UNC\\' if path.startswith('\\\\') else '\\\\?\\'
    return prefix + (path[2:] if path.startswith('\\\\') else path)
