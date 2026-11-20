"""Shared Qt renderer for the canvas, full-resolution preview, and export."""
from __future__ import annotations
from .i18n import tr

import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QApplication

from .paths import io_path
from .geometry import Scene, promote_measurement

FORMATS = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.bmp': 'BMP',
           '.tif': 'TIFF', '.tiff': 'TIFF'}
_headless_app = None


@dataclass
class Mark:
    uid: str
    kind: str
    style: dict
    result: object
    active: bool


def marks(objects, measurements, matrix, scalar, shape, selected=None,
          include=None, publication=False, preview=None, show_scales=True):
    legacy = []
    for index, original in enumerate(measurements):
        obj = promote_measurement(original)
        if obj:
            obj['id'] = f'legacy:{index}'
            legacy.append(obj)
    all_items = [*objects, *legacy]
    scene = Scene(all_items, matrix, shape)
    for item in all_items:
        uid, kind = item['id'], item['kind']
        if include is None and not item['visible'] and uid != preview:
            continue
        if include is not None and uid not in include:
            continue
        if kind == 'scale' and not show_scales:
            continue
        result = scene[uid]
        if result.paths or result.label:
            style = item['style']
            if publication:
                style = dict(style, font_family='Arial', font_pt=12., bold=False,
                             italic=False, line_width=2.)
            yield Mark(uid, kind, style, result, uid == selected)


def _alpha(ink, percent):
    color = QColor(ink)
    color.setAlphaF(percent/100)
    return color


def _qt_font(style):
    font = QFont(style['font_family'])
    # Points are resolved at 96 dpi to the original image's geometric pixels.
    font.setPixelSize(max(1, round(style['font_pt']*96/72)))
    font.setBold(style['bold'])
    font.setItalic(style['italic'])
    return font


def label_layout(mark, project, extent, offset_zoom=1.0, device=None):
    result, style = mark.result, mark.style
    if not result.label or not result.anchor:
        return None
    ax, ay = project(result.anchor)
    if mark.kind == 'scale':
        first, last = map(project, result.paths[0])
        ax, ay = (first[0]+last[0])/2, (first[1]+last[1])/2
    x0, y0, x1, y1 = extent
    font = _qt_font(style)
    fm = QFontMetricsF(font, device) if device else QFontMetricsF(font)
    lines = result.label.splitlines()[:12] or ['']
    width = max(fm.horizontalAdvance(line) for line in lines)
    height = fm.height()+(len(lines)-1)*fm.lineSpacing()
    pad, gap = style['padding'], style['label_gap']
    side = style['position']
    align = style['alignment']
    if align == 'anchor':
        align = 'center'
    x = ax - (width/2 if align == 'center' else width if align == 'right' else 0.)
    y = ay-height/2
    if side == 'above':
        y = ay-gap-height-pad
    elif side == 'below':
        y = ay+gap+pad
    elif side == 'left':
        x = ax-gap-pad-width
    else:
        x = ax+gap+pad
    x += style['label_x']*offset_zoom
    y += style['label_y']*offset_zoom
    # Keep labels inside when anchored within the image. Labels on a
    # construction whose intersection is off-image stay off-image.
    if x0 <= ax <= x1 and y0 <= ay <= y1:
        x = max(x0+pad, min(x1-width-pad, x))
        y = max(y0+pad, min(y1-height-pad, y))
    return QRectF(x-pad, y-pad, width+2*pad, height+2*pad), (x, y), lines, font, fm, align, width


_PATTERNS = {'solid': Qt.PenStyle.SolidLine, 'dash': Qt.PenStyle.DashLine,
             'dot': Qt.PenStyle.DotLine, 'dashdot': Qt.PenStyle.DashDotLine}
_CAPS = {'flat': Qt.PenCapStyle.FlatCap, 'square': Qt.PenCapStyle.SquareCap,
         'round': Qt.PenCapStyle.RoundCap}


def _draw_path(painter, path, pen, contrast=False):
    if len(path) < 2:
        return
    polygon = QPolygonF([QPointF(*pt) for pt in path])
    if contrast and pen.color().alpha() > 0:
        edge = QPen(pen)
        color = QColor('#ffffff' if pen.color().lightness() < 100 else '#172026')
        color.setAlpha(min(210, pen.color().alpha()))
        edge.setColor(color)
        edge.setWidthF(pen.widthF()+2)
        painter.setPen(edge)
        painter.drawPolyline(polygon)
    painter.setPen(pen)
    painter.drawPolyline(polygon)


def _arrow(painter, a, b, size, pen, contrast):
    dx, dy = a[0]-b[0], a[1]-b[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return
    dx, dy = dx/length, dy/length
    size = min(size, length*.42)
    pen = QPen(pen)
    pen.setStyle(Qt.PenStyle.SolidLine)
    tail = b[0]+dx*size, b[1]+dy*size
    wing = .4*size
    _draw_path(painter, ((tail[0]-dy*wing, tail[1]+dx*wing), b,
                        (tail[0]+dy*wing, tail[1]-dx*wing)), pen, contrast)


def _marker(painter, pt, style, pen):
    if style['center'] == 'none' or not pen.color().alpha():
        return
    x, y = pt
    size = style['center_size']
    marker = style['center']
    center = QPointF(x, y)
    pen = QPen(pen)
    pen.setStyle(Qt.PenStyle.SolidLine)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if marker == 'cross':
        _draw_path(painter, ((x-size, y), (x+size, y)), pen, True)
        _draw_path(painter, ((x, y-size), (x, y+size)), pen, True)
    elif marker == 'square':
        painter.drawRect(QRectF(x-size, y-size, 2*size, 2*size))
    else:
        if marker == 'dot':
            painter.setBrush(pen.color())
        painter.drawEllipse(center, size, size)


def paint_mark(painter, mark, project, extent, offset_zoom=1., show_controls=False):
    style, result = mark.style, mark.result
    color = _alpha(style['line_color'], style['line_opacity'])
    pen = QPen(color, style['line_width']+(1. if mark.active else 0.), _PATTERNS[style['line_pattern']])
    pen.setCapStyle(_CAPS[style['line_cap']])
    paths = [tuple(map(project, points)) for points in result.paths if len(points) > 1]
    if mark.kind != 'intersection':
        for path in paths:
            _draw_path(painter, path, pen, mark.kind == 'scale')
    if result.triangle:
        construction = QPen(pen)
        construction.setStyle(Qt.PenStyle.DashLine)
        _draw_path(painter, tuple(map(project, result.triangle)), construction)
    if paths:
        if mark.kind == 'scale':
            a, b = paths[0]
            dx, dy = b[0]-a[0], b[1]-a[1]
            length = math.hypot(dx, dy)
            if length > 1e-9:
                delta = -dy/length*style['tick'], dx/length*style['tick']
                for x, y in (a, b):
                    _draw_path(painter, ((x-delta[0], y-delta[1]), (x+delta[0], y+delta[1])), pen, True)
        radial = mark.kind in ('throat', 'circle') and len(paths) >= 2
        path = paths[1] if radial else paths[0]
        if style['arrows'] in ('start', 'both'):
            _arrow(painter, path[1], path[0], style['arrow_size'], pen, mark.kind == 'scale')
        if style['arrows'] in ('end', 'both'):
            _arrow(painter, path[-2], path[-1], style['arrow_size'], pen, mark.kind == 'scale')
    if result.center:
        _marker(painter, project(result.center), style, pen)
    elif mark.kind == 'intersection' and result.anchor:
        _marker(painter, project(result.anchor), style, pen)
    if show_controls and style['controls']:
        painter.setPen(QPen(color, 1.))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for point in result.handles:
            p = QPointF(*project(point))
            painter.drawEllipse(p, 3., 3.)

    label = label_layout(mark, project, extent, offset_zoom, painter.device())
    if label is None:
        return None
    box, (x, y), lines, font, fm, alignment, width = label
    background = style['background']
    if background != 'none' or style['border_width']:
        if background == 'none':
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            ink = {'white': '#ffffff', 'black': '#000000'}.get(background, style['background_color'])
            painter.setBrush(_alpha(ink, style['background_opacity']))
        painter.setPen(QPen(_alpha(style['border_color'], style['border_opacity']), style['border_width'])
                       if style['border_width'] else Qt.PenStyle.NoPen)
        painter.drawRoundedRect(box, style['corner'], style['corner'])
    ink = QColor(style['text_color'])
    painter.setFont(font)
    for i, line in enumerate(lines):
        length = fm.horizontalAdvance(line)
        left = x + ((width-length)/2 if alignment == 'center' else width-length if alignment == 'right' else 0)
        anchor = QPointF(left, y+fm.ascent()+i*fm.lineSpacing())
        if background == 'none' or style['background_opacity'] < 30:
            text_path = QPainterPath()
            text_path.addText(anchor, font, line)
            painter.strokePath(text_path, QPen(QColor('#ffffff' if ink.lightness() < 100 else '#182024'), 2.))
            painter.fillPath(text_path, ink)
        else:
            painter.setPen(ink)
            painter.drawText(anchor, line)
    return box


def native_photo(sample, variant, include=None, controls=False, uniform=False):
    global _headless_app
    if variant not in ('original', 'measurements', 'publication'):
        raise ValueError('Nieznany wariant eksportu.')
    if variant == 'publication' and include is None:
        raise ValueError('Wybierz oznaczenia do publikacji.')
    with Image.open(io_path(sample.image_path)) as original:
        image = ImageOps.exif_transpose(original)
        image.load()
        if variant == 'original':
            return image.copy(), original.info.copy()
        info = original.info.copy()
        rgb = image.convert('RGB')
    if rgb.size != tuple(reversed(sample.dimensions)):
        raise ValueError(tr('Orientacja pliku nie odpowiada widokowi w projekcie.'))
    if QApplication.instance() is None:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        _headless_app = QApplication([])
    w, h = rgb.size
    pix = QImage(rgb.tobytes(), w, h, w*3, QImage.Format.Format_RGB888).convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(pix)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for mark in marks(sample.geometry_objects, sample.measurements, sample.calibration_matrix(),
                          sample.mm_per_px, sample.dimensions,
                          include=include if variant == 'publication' else None,
                          publication=uniform and variant == 'publication'):
            paint_mark(painter, mark, lambda p: p, (0, 0, w, h), show_controls=controls)
    finally:
        painter.end()
    return qimage_to_pillow(pix), info


def qimage_to_pillow(pix):
    rgb = pix.convertToFormat(QImage.Format.Format_RGBA8888)
    bits = rgb.constBits()
    bits.setsize(rgb.sizeInBytes())
    return Image.frombytes('RGBA', (rgb.width(), rgb.height()), bytes(bits), 'raw', 'RGBA',
                           rgb.bytesPerLine()).convert('RGB')


def _same_path(destination, paths):
    for source in filter(None, paths):
        src = Path(source).resolve()
        if destination == src or (destination.exists() and src.exists() and
                                  os.path.samefile(destination, src)):
            return True
    return False


def export_photo(sample, destination, variant='measurements', include=None, protected=(),
                 controls=False, uniform=False):
    """A: original photograph, B: visible marks, C: explicitly selected marks."""
    destination = Path(destination).resolve()
    fmt = FORMATS.get(destination.suffix.lower())
    if fmt is None:
        raise ValueError(tr('Wybierz format PNG, JPEG, BMP lub TIFF.'))
    if _same_path(destination, [sample.image_path, sample.original_path, *protected]):
        raise ValueError(tr('Wybierz inną nazwę pliku, aby zachować fotografię źródłową.'))
    fd, temp = tempfile.mkstemp(dir=io_path(destination.parent), prefix='.weldvision-', suffix=destination.suffix)
    os.close(fd)
    try:
        with Image.open(io_path(sample.image_path)) as source:
            copy_original = variant == 'original' and source.format == fmt
        if copy_original:
            shutil.copyfile(io_path(sample.image_path), io_path(temp))
        else:
            image, info = native_photo(sample, variant, include, controls, uniform)
            if fmt == 'PNG' and image.mode in ('CMYK', 'F'):
                raise ValueError(tr('Format PNG nie zachowuje trybu obrazu. Wybierz TIFF.'))
            if fmt == 'PNG' and image.mode == 'I;16B':
                image = image.convert('I;16')
            if fmt in ('JPEG', 'BMP') and image.mode not in ('RGB','L'):
                image = image.convert('RGB')
            options = {key: info[key] for key in ('icc_profile', 'dpi') if info.get(key)}
            if fmt == 'JPEG':
                options.update(quality=97, subsampling=0)
            image.save(io_path(temp), format=fmt, **options)
        os.replace(io_path(temp), io_path(destination))
    finally:
        Path(io_path(temp)).unlink(missing_ok=True)
    return destination
