"""Interaktywny obraz spoiny: pomiary, maski, markery, undo/redo."""
from __future__ import annotations
import math
from copy import deepcopy
import cv2
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QWheelEvent
from PyQt6.QtWidgets import QWidget
from .core import image_read, png_bytes, from_png
from .measurements import MEASUREMENT_TYPES, measurement_geometry, measurement_mm

def bgr_to_qimage(img):
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h,w,c = rgb.shape
    return QImage(rgb.data,w,h,rgb.strides[0],QImage.Format.Format_RGB888).copy()

class ImageCanvas(QWidget):
    changed = pyqtSignal()
    calibration_ready = pyqtSignal(float)
    measurement_ready = pyqtSignal()
    status = pyqtSignal(str)

    PAN = "pan"
    CAL = "cal"
    ROI = "roi"
    POLY = "poly"
    ADD = "add"
    ERASE = "erase"
    FG = "fg"
    BG = "bg"
    MEASURE = "measure"

    def __init__(self):
        super().__init__()
        self.setMinimumSize(440, 300)
        self.setMouseTracking(True)

        self.img = None
        self.qimg = QImage()
        self.mask = None
        self.fg = None
        self.bg = None

        self.mode = self.PAN
        self.zoom = 1.0
        self.offset = QPointF(0, 0)

        self.dragging = False
        self.last_pos = QPointF()
        self.stroke = False
        self.last_brush = None

        self.cal_points = []
        self.measurements = []
        self.measure_points = []
        self.measure_kind = 'a'
        self.mm_per_px = None
        self.poly_points = []
        self.roi_start = None
        self.roi_end = None

        self.brush_px = 18
        self.show_overlay = True
        self.show_seeds = True
        self.history = []
        self.future = []
        self.max_history = 20
        self._layer_cache = {}

    def invalidate_layers(self):
        self._layer_cache.clear()
        self.update()

    def _layer(self, key, arr, channel, opacity):
        if key in self._layer_cache:
            return self._layer_cache[key]
        if arr is None or not np.any(arr):
            self._layer_cache[key] = None
            return None
        rgba = np.zeros((*arr.shape, 4), np.uint8)
        rgba[..., channel] = 255
        rgba[..., 3] = np.where(arr > 0, opacity, 0).astype(np.uint8)
        rendered = QImage(rgba.data, rgba.shape[1], rgba.shape[0], rgba.strides[0],
                          QImage.Format.Format_RGBA8888).copy()
        self._layer_cache[key] = rendered
        return rendered

    def snapshot(self):
        if self.mask is None:
            return None
        return (png_bytes(self.mask), png_bytes(self.fg), png_bytes(self.bg),
                self.roi_start, self.roi_end, list(self.cal_points),
                deepcopy(self.measurements))

    def _restore(self, snapshot):
        if snapshot is None or self.img is None:
            return
        h,w = self.img.shape[:2]
        self.mask = from_png(snapshot[0], (h,w))
        self.fg = from_png(snapshot[1], (h,w))
        self.bg = from_png(snapshot[2], (h,w))
        self.roi_start, self.roi_end = snapshot[3], snapshot[4]
        self.cal_points = list(snapshot[5])
        self.measurements = deepcopy(snapshot[6]) if len(snapshot) > 6 else []
        self.measure_points = []
        self.changed.emit()
        self.invalidate_layers()

    def begin_edit(self):
        previous = self.snapshot()
        if previous:
            self.history.append(previous)
            self.history = self.history[-self.max_history:]
            self.future.clear()

    def undo(self):
        if self.history and self.img is not None:
            self.future.append(self.snapshot())
            self._restore(self.history.pop())

    def redo(self):
        if self.future and self.img is not None:
            self.history.append(self.snapshot())
            self._restore(self.future.pop())

    def has_image(self):
        return self.img is not None

    def load_image(self, path):
        img = image_read(path)
        if img is None:
            raise RuntimeError("Nie udało się wczytać zdjęcia.")
        self.img = img
        self.qimg = bgr_to_qimage(img)
        h, w = img.shape[:2]
        self.mask = np.zeros((h, w), np.uint8)
        self.fg = np.zeros((h, w), np.uint8)
        self.bg = np.zeros((h, w), np.uint8)
        self.cal_points = []
        self.measurements = []
        self.measure_points = []
        self.mm_per_px = None
        self.poly_points = []
        self.roi_start = self.roi_end = None
        self.history = []
        self.future = []
        self._layer_cache.clear()
        self.fit()
        self.update()

    def fit(self):
        if not self.has_image():
            return
        vw, vh = max(1, self.width()), max(1, self.height())
        iw, ih = self.qimg.width(), self.qimg.height()
        self.zoom = max(0.02, min(vw / iw, vh / ih) * 0.95)
        self.offset = QPointF((vw - iw*self.zoom)/2, (vh - ih*self.zoom)/2)
        self.update()

    def set_mode(self, mode):
        self.cancel_pending()
        self.mode = mode
        # Punkty kalibracyjne znikają dopiero po pierwszym nowym kliknięciu,
        # a nie już podczas wyboru narzędzia.
        if mode != self.POLY:
            self.poly_points = []
        self.update()

    def cancel_pending(self):
        self.measure_points = []
        self.stroke = self.dragging = False
        self.last_brush = None
        self.update()

    def start_measurement(self, kind):
        if not self.has_image() or not self.mm_per_px or kind not in MEASUREMENT_TYPES:
            return False
        self.set_mode(self.MEASURE)
        self.measure_kind = kind
        self.status.emit(MEASUREMENT_TYPES[kind][2])
        return True

    def remove_measurement(self, index):
        if 0 <= index < len(self.measurements):
            self.begin_edit()
            del self.measurements[index]
            self.changed.emit()
            self.update()

    def widget_to_image(self, p):
        if not self.has_image():
            return None
        x = (p.x() - self.offset.x()) / self.zoom
        y = (p.y() - self.offset.y()) / self.zoom
        h, w = self.img.shape[:2]
        if 0 <= x < w and 0 <= y < h:
            return float(x), float(y)
        return None

    def image_to_widget(self, pt):
        return QPointF(self.offset.x()+pt[0]*self.zoom,
                       self.offset.y()+pt[1]*self.zoom)

    def get_roi(self):
        if self.roi_start is None or self.roi_end is None:
            return None
        x1, y1 = self.roi_start
        x2, y2 = self.roi_end
        x1, x2 = sorted([int(round(x1)), int(round(x2))])
        y1, y2 = sorted([int(round(y1)), int(round(y2))])
        if x2-x1 < 5 or y2-y1 < 5:
            return None
        return x1, y1, x2, y2

    def points_from_seed(self, seed, max_points=40):
        """Z maski pędzla tworzy reprezentatywne punkty promptów dla SAM."""
        ys, xs = np.where(seed > 0)
        if len(xs) == 0:
            return []
        n = min(max_points, len(xs))
        idx = np.linspace(0, len(xs)-1, n, dtype=int)
        return [(float(xs[i]), float(ys[i])) for i in idx]

    def wheelEvent(self, e: QWheelEvent):
        if not self.has_image():
            return
        ip = self.widget_to_image(e.position())
        if ip is None:
            return
        factor = 1.15 if e.angleDelta().y() > 0 else 1/1.15
        nz = max(0.02, min(50.0, self.zoom*factor))
        self.zoom = nz
        self.offset = QPointF(e.position().x()-ip[0]*nz,
                              e.position().y()-ip[1]*nz)
        self.update()

    def mousePressEvent(self, e: QMouseEvent):
        if not self.has_image():
            return

        if e.button() == Qt.MouseButton.MiddleButton or (
            e.button() == Qt.MouseButton.LeftButton and self.mode == self.PAN
        ):
            self.dragging = True
            self.last_pos = e.position()
            return

        ip = self.widget_to_image(e.position())
        if ip is None:
            return

        if self.mode == self.MEASURE:
            if e.button() == Qt.MouseButton.RightButton:
                self.cancel_pending()
                self.status.emit('Anulowano wskazywanie punktów pomiarowych.')
                return
            if e.button() != Qt.MouseButton.LeftButton or not self.mm_per_px:
                return
            self.measure_points.append(ip)
            required = MEASUREMENT_TYPES[self.measure_kind][1]
            if len(self.measure_points) == required:
                try:
                    measurement_geometry(self.measure_kind, self.measure_points)
                except ValueError as exc:
                    self.measure_points = []
                    self.status.emit(str(exc))
                    self.update()
                    return
                self.begin_edit()
                self.measurements.append({'kind': self.measure_kind,
                                          'points': [list(pt) for pt in self.measure_points]})
                self.measure_points = []
                self.mode = self.PAN
                self.changed.emit()
                self.measurement_ready.emit()
            else:
                self.status.emit(f'Wskazano {len(self.measure_points)}/{required} punktów. '
                                 + MEASUREMENT_TYPES[self.measure_kind][2])
            self.update()
            return

        if self.mode == self.CAL and e.button() == Qt.MouseButton.LeftButton:
            self.begin_edit()
            if len(self.cal_points) >= 2:
                self.cal_points = []
            self.cal_points.append(ip)
            if len(self.cal_points) == 2:
                a, b = self.cal_points
                d = math.hypot(b[0]-a[0], b[1]-a[1])
                if d > 0:
                    self.calibration_ready.emit(d)
                    self.mode = self.PAN
                else:
                    self.cal_points.pop()
                    self.status.emit('Punkty kalibracyjne muszą być różne. Wskaż drugi punkt.')
            self.changed.emit()
            self.update()
            return

        if self.mode == self.ROI and e.button() == Qt.MouseButton.LeftButton:
            self.begin_edit()
            self.roi_start = ip
            self.roi_end = ip
            self.stroke = True
            self.update()
            return

        if self.mode == self.POLY:
            if e.button() == Qt.MouseButton.LeftButton:
                self.poly_points.append(ip)
            elif e.button() == Qt.MouseButton.RightButton:
                self.finish_polygon()
            self.update()
            return

        if self.mode in (self.ADD, self.ERASE, self.FG, self.BG) and e.button() == Qt.MouseButton.LeftButton:
            self.begin_edit()
            self.stroke = True
            self.last_brush = ip
            self.paint_brush(ip, ip)

    def mouseMoveEvent(self, e: QMouseEvent):
        if self.dragging:
            d = e.position() - self.last_pos
            self.offset += d
            self.last_pos = e.position()
            self.update()
            return

        ip = self.widget_to_image(e.position())
        if ip:
            self.status.emit(f"x={ip[0]:.1f} px, y={ip[1]:.1f} px")

        if self.mode == self.ROI and self.stroke and ip:
            self.roi_end = ip
            self.update()
            return

        if self.stroke and ip and self.mode in (self.ADD, self.ERASE, self.FG, self.BG):
            self.paint_brush(self.last_brush or ip, ip)
            self.last_brush = ip

    def mouseReleaseEvent(self, e):
        if self.dragging:
            self.dragging = False
        if self.stroke:
            self.stroke = False
            self.last_brush = None
            self.changed.emit()

    def mouseDoubleClickEvent(self, e):
        if self.mode == self.POLY and e.button() == Qt.MouseButton.LeftButton:
            ip = self.widget_to_image(e.position())
            if ip:
                self.poly_points.append(ip)
            self.finish_polygon()

    def finish_polygon(self):
        if self.mask is None or len(self.poly_points) < 3:
            return
        self.begin_edit()
        pts = np.array(self.poly_points, dtype=np.int32)
        cv2.fillPoly(self.mask, [pts], 255)
        self.poly_points = []
        self.changed.emit()
        self.invalidate_layers()

    def paint_brush(self, p1, p2):
        a = tuple(int(round(v)) for v in p1)
        b = tuple(int(round(v)) for v in p2)
        r = int(self.brush_px)

        if self.mode == self.ADD:
            target, value = self.mask, 255
        elif self.mode == self.ERASE:
            target, value = self.mask, 0
        elif self.mode == self.FG:
            target, value = self.fg, 255
        else:
            target, value = self.bg, 255

        cv2.line(target, a, b, value, max(2, 2*r), cv2.LINE_AA)
        cv2.circle(target, b, r, value, -1, cv2.LINE_AA)
        self.invalidate_layers()

    def clear_mask(self):
        if self.mask is not None:
            self.begin_edit()
            self.mask[:] = 0
            self.changed.emit()
            self.invalidate_layers()

    def clear_seeds(self):
        if self.fg is not None:
            self.begin_edit()
            self.fg[:] = 0
            self.bg[:] = 0
            self.changed.emit()
            self.invalidate_layers()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(28, 28, 30))

        if not self.has_image():
            p.setPen(QColor(230, 230, 230))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Wczytaj zdjęcie makroskopowe")
            return

        target = QRectF(self.offset.x(), self.offset.y(),
                        self.qimg.width()*self.zoom, self.qimg.height()*self.zoom)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(target, self.qimg)

        # Nakładki są przeliczane wyłącznie po zmianie danych, nie podczas zoom/pan.
        if self.show_overlay:
            layer=self._layer('mask',self.mask,0,100)
            if layer is not None:
                p.drawImage(target,layer)
        if self.show_seeds:
            fg=self._layer('fg',self.fg,1,180)
            bg=self._layer('bg',self.bg,2,180)
            if fg is not None:
                p.drawImage(target,fg)
            if bg is not None:
                p.drawImage(target,bg)

        # kalibracja
        if len(self.cal_points) >= 1:
            p.setPen(QPen(QColor(255, 230, 0), 2))
            for pt in self.cal_points:
                wp = self.image_to_widget(pt)
                p.drawEllipse(wp, 5, 5)
            if len(self.cal_points) == 2:
                p.drawLine(self.image_to_widget(self.cal_points[0]),
                           self.image_to_widget(self.cal_points[1]))

        # Wymiary w pikselach oryginału: zoom i przesuwanie nie zmieniają wyniku.
        for index, item in enumerate(self.measurements):
            start, end, _ = measurement_geometry(item['kind'], item['points'])
            a, b = self.image_to_widget(start), self.image_to_widget(end)
            p.setPen(QPen(QColor(70, 235, 255), 2))
            p.drawLine(a, b)
            for point in item['points']:
                p.drawEllipse(self.image_to_widget(point), 4, 4)
            if item['kind'] == 'a':
                p.setPen(QPen(QColor(70, 235, 255), 1, Qt.PenStyle.DashLine))
                p.drawLine(self.image_to_widget(item['points'][1]),
                           self.image_to_widget(item['points'][2]))
            value = measurement_mm(item, self.mm_per_px)
            label = f'{index+1}. {item["kind"]} = {value:.3f} mm' if value is not None else f'{index+1}. brak kalibracji'
            midpoint = (a + b) / 2 + QPointF(8, -8)
            bounds = p.fontMetrics().boundingRect(label)
            box = QRectF(midpoint.x()-3, midpoint.y()-bounds.height(),
                         bounds.width()+8, bounds.height()+6)
            p.fillRect(box, QColor(20, 25, 30, 220))
            p.setPen(QColor(70, 235, 255))
            p.drawText(midpoint, label)
        p.setPen(QPen(QColor(70, 235, 255), 2))
        for index, point in enumerate(self.measure_points):
            pos = self.image_to_widget(point)
            p.drawEllipse(pos, 5, 5)
            p.drawText(pos + QPointF(8, -8), str(index+1))

        # ROI
        roi = self.get_roi()
        if roi:
            x1, y1, x2, y2 = roi
            a = self.image_to_widget((x1, y1))
            b = self.image_to_widget((x2, y2))
            p.setPen(QPen(QColor(255, 180, 0), 2, Qt.PenStyle.DashLine))
            p.drawRect(QRectF(a, b))

        # wielokąt
        if self.poly_points:
            p.setPen(QPen(QColor(255, 255, 0), 2))
            pts = [self.image_to_widget(v) for v in self.poly_points]
            for i in range(len(pts)-1):
                p.drawLine(pts[i], pts[i+1])
            for qpt in pts:
                p.drawEllipse(qpt, 4, 4)



