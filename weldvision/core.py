"""WeldVision: model danych, pomiary i bezpieczny zapis projektu (bez Qt)."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from .measurements import measurement_mm, measurement_geometry, validate_measurements
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

SCHEMA_VERSION = 2
MAX_ITEMS = 1000
MAX_MEMBER_BYTES = 400 * 1024 * 1024
STATUS_NEW = "nowa"
STATUS_READY = "gotowa"
STATUS_REVIEW = "do_weryfikacji"
STATUS_APPROVED = "zatwierdzona"
STATUS_ERROR = "blad"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_name(name: str, fallback: str = "probka") -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or '').strip(' .')
    return clean[:95] or fallback


def image_read(path):
    data = np.fromfile(str(path), np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def image_write(path, img):
    ext = Path(path).suffix.lower() or '.png'
    ok, enc = cv2.imencode(ext, img)
    if not ok:
        raise OSError(f"Nie można zakodować obrazu {path}")
    Path(path).write_bytes(enc.tobytes())


def png_bytes(img: np.ndarray | None) -> bytes | None:
    if img is None:
        return None
    arr = np.where(img > 0, 255, 0).astype(np.uint8)
    ok, enc = cv2.imencode('.png', arr)
    if not ok:
        raise ValueError("Nie można zakodować maski PNG")
    return enc.tobytes()


def from_png(blob: bytes | None, shape: tuple[int, int]) -> np.ndarray:
    if not blob:
        return np.zeros(shape, np.uint8)
    arr = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_GRAYSCALE)
    if arr is None or arr.shape != shape:
        raise ValueError(f"Maska ma błędne wymiary (oczekiwano {shape})")
    return np.where(arr > 0, 255, 0).astype(np.uint8)


def roi_tuple(start, end, shape=None):
    if start is None or end is None:
        return None
    x1, x2 = sorted((int(round(start[0])), int(round(end[0]))))
    y1, y2 = sorted((int(round(start[1])), int(round(end[1]))))
    if shape is not None:
        h, w = shape[:2]
        x1, x2 = max(0, min(w, x1)), max(0, min(w, x2))
        y1, y2 = max(0, min(h, y1)), max(0, min(h, y2))
    if x2 - x1 < 3 or y2 - y1 < 3:
        return None
    return x1, y1, x2, y2


def clip_mask_roi(mask: np.ndarray, roi):
    if roi is None:
        return mask
    x1, y1, x2, y2 = roi
    out = np.zeros_like(mask)
    out[y1:y2, x1:x2] = mask[y1:y2, x1:x2]
    return out


def clean_mask(mask: np.ndarray, min_area: int = 0, close_size: int = 0):
    """Domyślnie bez morfologii, bo każdy piksel wpływa na wynik metrologiczny."""
    m = (mask > 0).astype(np.uint8) * 255
    if close_size > 1:
        kernel = np.ones((close_size, close_size), np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel)
    if min_area > 0:
        n, labels, stats, _ = cv2.connectedComponentsWithStats((m > 0).astype(np.uint8), 8)
        filtered = np.zeros_like(m)
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] >= min_area:
                filtered[labels == i] = 255
        return filtered
    return m


def metrics(mask: np.ndarray | None, mm_per_px: float | None, density: float):
    count = int(np.count_nonzero(mask)) if mask is not None else 0
    area = count * mm_per_px ** 2 if mm_per_px and mm_per_px > 0 else None
    return {
        "px2": count,
        "area_mm2": area,
        "volume_cm3_m": area,
        "mass_g_m": area * density if area is not None else None,
        "mass_kg_m": area * density / 1000 if area is not None else None,
    }


def scaled_roi(start, end, src_shape, dst_shape):
    if start is None or end is None:
        return None, None
    sy, sx = src_shape[:2]
    dy, dx = dst_shape[:2]
    return ((start[0] * dx / sx, start[1] * dy / sy),
            (end[0] * dx / sx, end[1] * dy / sy))


def export_stems(samples):
    """Indeks i UUID eliminują kolizje A, A_02, A, także po sanizacji."""
    return [f"{i+1:03d}_{safe_name(s.name)}_{s.uid[:8]}" for i, s in enumerate(samples)]


@dataclass
class Sample:
    uid: str
    name: str
    image_path: str
    source_name: str
    original_path: str = ""
    dimensions: tuple[int, int] = (0, 0)  # H, W
    density: float = 7.85
    known_mm: float = 10.0
    cal_points: list = field(default_factory=list)
    measurements: list = field(default_factory=list)
    mm_per_px: float | None = None
    roi_start: tuple | None = None
    roi_end: tuple | None = None
    mask_png: bytes | None = None
    raw_png: bytes | None = None
    fg_png: bytes | None = None
    bg_png: bytes | None = None
    state: str = STATUS_NEW
    method: str = ""
    model_id: str = ""
    analyzed_at: str = ""
    approved_at: str = ""
    min_area: int = 0
    close_size: int = 0
    revision: int = 0
    error: str = ""
    undo_history: list = field(default_factory=list, repr=False)
    redo_history: list = field(default_factory=list, repr=False)

    @classmethod
    def from_file(cls, path, density=7.85):
        path = Path(path).resolve()
        img = image_read(path)
        if img is None:
            raise ValueError(f"Nie można otworzyć obrazu: {path}")
        return cls(uuid.uuid4().hex, path.stem, str(path), path.name,
                   str(path), img.shape[:2], density=float(density))

    def mask(self, kind="mask"):
        return from_png(getattr(self, f"{kind}_png"), self.dimensions)

    def set_mask(self, kind, img):
        if img.shape[:2] != self.dimensions:
            raise ValueError("Rozmiar maski nie zgadza się z obrazem")
        setattr(self, f"{kind}_png", png_bytes(img))

    def recalc_scale(self):
        if len(self.cal_points) == 2:
            p, q = self.cal_points
            distance = math.hypot(q[0] - p[0], q[1] - p[1])
            self.mm_per_px = self.known_mm / distance if distance > 0 else None
        else:
            self.mm_per_px = None

    def roi(self):
        return roi_tuple(self.roi_start, self.roi_end, self.dimensions)

    def ready(self):
        return self.roi() is not None or bool(self.fg_png and np.any(self.mask("fg")))

    def summary(self):
        m = metrics(self.mask(), self.mm_per_px, self.density)
        return {"id": self.uid, "probka": self.name, "zdjecie": self.source_name,
                "status": self.state, "metoda": self.method, "model": self.model_id,
                "piksele": m["px2"], "skala_mm_px": self.mm_per_px,
                "pole_mm2": m["area_mm2"], "gestosc_g_cm3": self.density,
                "objetosc_cm3_m": m["volume_cm3_m"], "masa_g_m": m["mass_g_m"],
                "masa_kg_m": m["mass_kg_m"], "kalibracja_mm": self.known_mm,
                "data_analizy": self.analyzed_at, "data_zatwierdzenia": self.approved_at,
                "komentarz": "Masa teoretyczna zaznaczonego przekroju, niekoniecznie uzysk stopiwa"}

    def meta(self):
        return {
            "uid": self.uid, "name": self.name, "source_name": self.source_name,
            "original_path": self.original_path, "dimensions": list(self.dimensions),
            "density": self.density, "known_mm": self.known_mm,
            "cal_points": self.cal_points, "mm_per_px": self.mm_per_px,
            "measurements": self.measurements,
            "roi_start": self.roi_start, "roi_end": self.roi_end,
            "state": self.state, "method": self.method, "model_id": self.model_id,
            "analyzed_at": self.analyzed_at, "approved_at": self.approved_at,
            "min_area": self.min_area, "close_size": self.close_size,
            "revision": self.revision, "error": self.error,
            "image_suffix": Path(self.image_path).suffix.lower() or '.png',
        }

    @classmethod
    def from_meta(cls, md, image_path, masks):
        dims = tuple(md["dimensions"])
        sample = cls(
            uid=md["uid"], name=md["name"], image_path=str(image_path),
            source_name=md["source_name"], original_path=md.get("original_path", ""),
            dimensions=dims, density=float(md.get("density", 7.85)),
            known_mm=float(md.get("known_mm", 10)),
            cal_points=[list(p) for p in md.get("cal_points", [])],
            measurements=validate_measurements(md.get('measurements', []), dims),
            mm_per_px=md.get("mm_per_px"),
            roi_start=tuple(md["roi_start"]) if md.get("roi_start") else None,
            roi_end=tuple(md["roi_end"]) if md.get("roi_end") else None,
            state=md.get("state", STATUS_NEW), method=md.get("method", ""),
            model_id=md.get("model_id", ""), analyzed_at=md.get("analyzed_at", ""),
            approved_at=md.get("approved_at", ""), min_area=int(md.get("min_area", 0)),
            close_size=int(md.get("close_size", 0)), revision=int(md.get("revision", 0)),
            error=md.get("error", ""), **masks)
        return sample


class Project:
    def __init__(self, samples=None, path=None, storage=None):
        self.samples = samples or []
        self.path = str(path) if path else None
        self.storage = storage  # TemporaryDirectory for extracted project images
        self.dirty = False
        self.active_id = self.samples[0].uid if self.samples else None
        self.model_id = "facebook/sam-vit-large"
        self.device = "auto"

    def get(self, uid):
        return next((s for s in self.samples if s.uid == uid), None)

    def mark_dirty(self):
        self.dirty = True

    def close(self):
        if self.storage is not None:
            self.storage.cleanup()
            self.storage = None


FIELDS = ["id", "probka", "zdjecie", "status", "metoda", "model", "piksele", "skala_mm_px",
          "pole_mm2", "gestosc_g_cm3", "objetosc_cm3_m", "masa_g_m", "masa_kg_m",
          "kalibracja_mm", "data_analizy", "data_zatwierdzenia", "komentarz"]


def csv_content(project):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, delimiter=';', extrasaction='ignore')
    w.writeheader()
    for sample in project.samples:
        w.writerow(sample.summary())
    return buf.getvalue().encode('utf-8-sig')


def _archive_bytes(info, zf):
    if info.file_size > MAX_MEMBER_BYTES:
        raise ValueError(f"Element projektu jest zbyt duży: {info.filename}")
    return zf.read(info)


def save_project(project: Project, dest, backup=True, mark_clean=True):
    """Atomowy ZIP, test CRC, backup .bak; stary projekt pozostaje bez zmian przy błędzie."""
    dest = Path(dest).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=dest.stem + '_', suffix='.tmp', dir=dest.parent)
        os.close(fd)
        tmp_path = Path(temp_name)
        meta = {"schema": SCHEMA_VERSION, "saved_at": now_iso(),
                "active_id": project.active_id, "model_id": project.model_id,
                "device": project.device, "items": []}
        with zipfile.ZipFile(tmp_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3,
                             allowZip64=True) as z:
            for s in project.samples:
                if not Path(s.image_path).is_file():
                    raise FileNotFoundError(f"Nie odnaleziono obrazu: {s.image_path}")
                src = Path(s.image_path)
                suffix = src.suffix.lower() if src.suffix.lower() in ('.png','.jpg','.jpeg','.tif','.tiff','.bmp') else '.png'
                image_arc = f"images/{s.uid}{suffix}"
                z.write(src, image_arc)
                data = s.meta()
                data["image_file"] = image_arc
                data["masks"] = {}
                for key in ("mask", "fg", "bg", "raw"):
                    blob = getattr(s, f"{key}_png")
                    if blob:
                        arc = f"masks/{s.uid}_{key}.png"
                        z.writestr(arc, blob)
                        data["masks"][key] = arc
                meta["items"].append(data)
            z.writestr('project.json', json.dumps(meta, ensure_ascii=False, indent=2))
            z.writestr('summary.csv', csv_content(project))
            z.writestr('pomiary_liniowe.csv', measurements_csv(project.samples))
        with zipfile.ZipFile(tmp_path) as z:
            bad = z.testzip()
            if bad:
                raise IOError(f"Błąd CRC pliku {bad}")
            saved_meta = json.loads(z.read('project.json').decode('utf-8'))
            if len(saved_meta['items']) != len(project.samples):
                raise IOError("Niepełna lista próbek po zapisie")
        if backup and dest.exists():
            backup_path = dest.with_suffix(dest.suffix + '.bak')
            shutil.copy2(dest, backup_path)
        os.replace(tmp_path, dest)
        tmp_path = None
        if mark_clean:
            project.path = str(dest)
            project.dirty = False
        return str(dest)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


def _zip_checked(z):
    names = z.namelist()
    if 'project.json' not in names:
        raise ValueError('Projekt nie zawiera project.json')
    if len(names) != len(set(names)):
        raise ValueError('Projekt zawiera zduplikowane nazwy plików')
    if len(names) > MAX_ITEMS * 8 + 12:
        raise ValueError('Zbyt wiele elementów w archiwum')
    total_size = 0
    for member in z.infolist():
        total_size += member.file_size
        if member.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f'Zbyt duży plik w projekcie: {member.filename}')
    if total_size > 10 * 1024**3:
        raise ValueError('Archiwum przekracza limit 10 GB danych po rozpakowaniu')
    if z.testzip() is not None:
        raise ValueError('Błędna suma kontrolna ZIP')
    md = json.loads(z.read('project.json').decode('utf-8'))
    items = md.get('items', [])
    if not isinstance(items, list) or not (0 <= len(items) <= MAX_ITEMS):
        raise ValueError('Nieprawidłowa lista próbek')
    return md


def load_project(path):
    """Czyta format v2 oraz archiwa legacy v1. Stan UI zmienia się dopiero po sukcesie."""
    path = Path(path).resolve()
    tmp = tempfile.TemporaryDirectory(prefix='weldvision_project_')
    samples = []
    try:
        with zipfile.ZipFile(path) as z:
            md = _zip_checked(z)
            for i, info in enumerate(md['items']):
                legacy = 'schema' not in md or md.get('schema') == 1
                if legacy:
                    paths = info.get('files', {})
                    image_arc = paths.get('image')
                    if not image_arc or image_arc not in z.namelist():
                        raise ValueError(f'Brak obrazu próbki {i+1}')
                    uid = uuid.uuid4().hex
                    ext = Path(image_arc).suffix or '.png'
                    dest = Path(tmp.name) / f'{uid}{ext}'
                    dest.write_bytes(_archive_bytes(z.getinfo(image_arc), z))
                    image = image_read(dest)
                    if image is None:
                        raise ValueError(f'Uszkodzony obraz próbki {i+1}')
                    shape = image.shape[:2]
                    masks = {}
                    for key, legacy_name in (("mask", "mask"), ("fg", "fg"), ("bg", "bg")):
                        p = paths.get(legacy_name)
                        if p and p in z.namelist():
                            blob = _archive_bytes(z.getinfo(p), z)
                            from_png(blob, shape)
                            masks[f'{key}_png'] = blob
                    s = Sample(uid=uid, name=info.get('sample_name', Path(image_arc).stem),
                               image_path=str(dest), source_name=info.get('source_name', Path(image_arc).name),
                               original_path=info.get('source_name', ''), dimensions=shape,
                               density=float(info.get('density', 7.85)),
                               known_mm=float(info.get('known_mm') or 10),
                               mm_per_px=info.get('mm_per_px'),
                               roi_start=tuple(info['roi_start']) if info.get('roi_start') else None,
                               roi_end=tuple(info['roi_end']) if info.get('roi_end') else None,
                               state=STATUS_REVIEW if masks.get('mask_png') else STATUS_NEW, **masks)
                else:
                    if md.get('schema') != SCHEMA_VERSION:
                        raise ValueError('Nieznana wersja formatu projektu')
                    uid = info['uid']
                    if not re.fullmatch(r'[a-fA-F0-9]{32}', uid):
                        raise ValueError('Nieprawidłowy identyfikator próbki')
                    image_arc = info['image_file']
                    if image_arc not in z.namelist():
                        raise ValueError(f'Brak obrazu {info.get("name", i)}')
                    dest = Path(tmp.name) / f'{uid}{Path(image_arc).suffix}'
                    dest.write_bytes(_archive_bytes(z.getinfo(image_arc), z))
                    image = image_read(dest)
                    if image is None:
                        raise ValueError('Uszkodzony obraz')
                    if tuple(info['dimensions']) != image.shape[:2]:
                        raise ValueError('Niezgodne wymiary obrazu')
                    masks = {}
                    for key, arc in info.get('masks', {}).items():
                        if key not in ('mask', 'raw', 'fg', 'bg'):
                            continue
                        blob = _archive_bytes(z.getinfo(arc), z)
                        from_png(blob, image.shape[:2])
                        masks[f'{key}_png'] = blob
                    s = Sample.from_meta(info, dest, masks)
                samples.append(s)
        if not samples:
            raise ValueError('Projekt nie zawiera próbek')
        ids = [s.uid for s in samples]
        if len(set(ids)) != len(ids):
            raise ValueError('Zduplikowane identyfikatory próbek')
        proj = Project(samples, path=str(path), storage=tmp)
        proj.active_id = md.get('active_id', samples[0].uid) if not legacy else samples[max(0, min(int(md.get('current_index', 0)), len(samples)-1))].uid
        if proj.active_id not in ids:
            proj.active_id = samples[0].uid
        proj.model_id = md.get('model_id', 'facebook/sam-vit-large')
        proj.device = md.get('device', 'auto')
        return proj
    except Exception:
        tmp.cleanup()
        raise


def render_overlay(img, mask, mm_per_px, density, sample_name="", annotate=True, measurements=None):
    out = img.copy()
    if mask is not None and np.any(mask):
        use = mask > 0
        tint = out.copy()
        tint[use] = (40, 70, 245)
        out = cv2.addWeighted(out, .7, tint, .3, 0)
        contours, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(out, contours, -1, (0, 255, 255), 2)
    if annotate:
        m = metrics(mask, mm_per_px, density)
        label = f'{sample_name}: A={m["area_mm2"]:.3f} mm2' if m['area_mm2'] is not None else f'{sample_name}: bez kalibracji'
        cv2.rectangle(out, (0, 0), (min(out.shape[1], max(400,len(label)*14)), 56), (22,22,22), -1)
        cv2.putText(out, label[:90], (14,35), cv2.FONT_HERSHEY_SIMPLEX, .7,
                    (255,255,255), 2, cv2.LINE_AA)
    for index, item in enumerate(measurements or []):
        start, end, _ = measurement_geometry(item['kind'], item['points'])
        to_int = lambda pt: tuple(int(round(v)) for v in pt)
        cv2.line(out, to_int(start), to_int(end), (255, 235, 70), 2, cv2.LINE_AA)
        for point in item['points']:
            cv2.circle(out, to_int(point), 5, (255, 235, 70), 2, cv2.LINE_AA)
        if item['kind'] == 'a':
            cv2.line(out, to_int(item['points'][1]), to_int(item['points'][2]),
                     (255, 235, 70), 1, cv2.LINE_AA)
        value = measurement_mm(item, mm_per_px)
        label = f'{index+1}. {item["kind"]} = {value:.3f} mm' if value is not None else f'{index+1}. bez kalibracji'
        size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, .6, 2)
        x = max(0, min(out.shape[1]-size[0]-6, int((start[0]+end[0])/2)+8))
        y = max(size[1]+4, min(out.shape[0]-baseline-4, int((start[1]+end[1])/2)-8))
        cv2.rectangle(out, (x,y-size[1]-4), (x+size[0]+4,y+baseline+3), (22,22,22), -1)
        cv2.putText(out, label, (x+2,y), cv2.FONT_HERSHEY_SIMPLEX, .6,
                    (255,235,70), 2, cv2.LINE_AA)
    return out


def measurements_csv(samples):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=';')
    writer.writerow(['id_probki', 'probka', 'nr_pomiaru', 'rodzaj', 'wymiar_mm',
                     'skala_mm_px', 'punkty_px'])
    for sample in samples:
        for index, item in enumerate(sample.measurements):
            writer.writerow([sample.uid, sample.name, index+1, item['kind'],
                             measurement_mm(item, sample.mm_per_px), sample.mm_per_px,
                             json.dumps(item['points'], ensure_ascii=False)])
    return buffer.getvalue().encode('utf-8-sig')


def export_results(project, destination, current_only=None):
    """Eksport zawsze do nowego podkatalogu, bez nadpisywania istniejących wyników."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    base = datetime.now().strftime('WeldVision_wyniki_%Y%m%d_%H%M%S')
    out = destination / base
    suffix = 2
    while out.exists():
        out = destination / f'{base}_{suffix}'
        suffix += 1
    out.mkdir()
    samples = [project.get(current_only)] if current_only else project.samples
    if any(s is None for s in samples):
        raise ValueError('Nie wybrano próbki')
    stems = export_stems(samples)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, delimiter=';')
    writer.writeheader()
    for sample, stem in zip(samples, stems):
        img = image_read(sample.image_path)
        if img is None:
            raise FileNotFoundError(sample.image_path)
        original_ext = Path(sample.image_path).suffix.lower()
        if original_ext not in ('.jpg','.jpeg','.png','.tif','.tiff','.bmp'):
            original_ext = '.png'
        shutil.copy2(sample.image_path, out / f'{stem}_oryginal{original_ext}')
        image_write(out / f'{stem}_maska.png', sample.mask())
        if sample.raw_png:
            (out / f'{stem}_maska_AI_surowa.png').write_bytes(sample.raw_png)
        image_write(out / f'{stem}_wynik.png', render_overlay(img, sample.mask(), sample.mm_per_px,
                    sample.density, sample.name, measurements=sample.measurements))
        writer.writerow(sample.summary())
    (out / 'wyniki_zbiorcze.csv').write_bytes(buffer.getvalue().encode('utf-8-sig'))
    (out / 'pomiary_liniowe.csv').write_bytes(measurements_csv(samples))
    return out
