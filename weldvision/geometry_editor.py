"""Mouse interaction for measurement objects on the existing ImageCanvas."""
from __future__ import annotations
from .i18n import tr

from copy import deepcopy
from math import hypot

from PyQt6.QtCore import QPointF, QRectF, Qt, QLineF
from PyQt6.QtGui import QColor, QPen

from .annotation_style import default_style
from .geometry import (DERIVED, LINES, THICKNESS, Scene, TYPES, add, intersection,
                       make_object, norm, projection, promote_measurement, sub,
                       validate_objects)
from .photo_annotations import label_layout, marks, paint_mark

GUIDE = {
    'select': 'Zaznacz na zdjęciu lub w tabeli. Przeciągnij obiekt lub jego uchwyt.',
    'circle': 'Wskaż środek, przesuń kursor i kliknij, aby ustalić promień.',
    'line': 'Wskaż początek i koniec odcinka.',
    'horizontal': 'Wskaż dwa punkty. Odcinek zostanie wyrównany poziomo na obrazie.',
    'vertical': 'Wskaż dwa punkty. Odcinek zostanie wyrównany pionowo na obrazie.',
    'infinite': 'Wskaż dwa punkty prostej konstrukcyjnej.',
    'parallel': 'Wybierz linię odniesienia, następnie punkt i kierunek nowej prostej.',
    'perpendicular': 'Wybierz linię odniesienia, następnie punkt i kierunek nowej prostej.',
    'polyline': 'Wskazuj punkty łamanej. Zakończ prawym przyciskiem (min. dwa punkty).',
    'angle': 'Wybierz dwie linie. Wynik to mniejszy kąt między ich prostymi.',
    'intersection': 'Wybierz dwie linie. Program przedłuży je do przecięcia.',
    'throat': 'Wybierz kolejno dwie linie powierzchni blach, następnie linię lub kontur lica.',
    'scale': 'Kliknij początek podziałki. Po dodaniu możesz ją przeciągnąć.',
    'point': 'Kliknij, aby wstawić punkt.',
    'comment': 'Kliknij miejsce podpisu na zdjęciu. Otworzy się pole wpisywania komentarza.',
    't1': 'Wskaż przeciwległe brzegi pierwszej blachy.',
    't2': 'Wskaż przeciwległe brzegi drugiej blachy.',
    'distance': 'Wskaż dwa punkty wymiaru.',
    'a_contour': 'Wskaż O, następnie pierwszy brzeg i kolejne punkty lica do drugiego brzegu. Zakończ prawym przyciskiem.',
}


class GeometryEditor:
    def __init__(self, canvas):
        self.canvas = canvas
        self.items = []
        self.selected = None
        self.snap = True
        self.tool = 'select'
        self.points = []
        self.refs = []
        self.options = {}
        self.cursor = None
        self.snapped = None
        self.drag = None
        self._scene_key = None
        self._scene = None
        self.labels = {}
        self.draft = None
        self.new_style = default_style
        self.flush_pending = lambda: None
        self.comment_text = lambda: None

    @property
    def matrix(self):
        return self.canvas.calibration_matrix

    @property
    def shape(self):
        return self.canvas.img.shape[:2]

    def scene(self):
        key = (self.items, self.matrix, self.shape)
        if key != self._scene_key:
            self._scene = Scene(self.items, self.matrix, self.shape)
            self._scene_key = key
        return self._scene

    def start(self, tool, **options):
        if not self.canvas.has_image():
            return False
        if tool in ('circle', 'scale', 'throat', 'a_contour', 'guided_throat') and self.matrix is None:
            self.canvas.status.emit(tr('Najpierw skalibruj zdjęcie.'))
            return False
        self.flush_pending()
        self.canvas.set_mode(self.canvas.GEOMETRY)
        self.tool, self.options = tool, options
        self.canvas.geometry_state.emit(self.message)
        return True

    @property
    def message(self):
        if self.tool == 'guided_throat':
            stage = len(self.points) // 2
            targets = ('powierzchnia pierwszej blachy', 'powierzchnia drugiej blachy', 'proste lico spoiny')
            return tr('Gardziel a · krok {0}/3: {1}. Kliknij punkt {2} z 2.').format(
                stage + 1, tr(targets[stage]), len(self.points) % 2 + 1)
        name = tr(TYPES.get(self.tool, 'Zaznaczanie'))
        if self.tool == 'throat' and len(self.refs) == 3:
            return tr('Gardziel a / r — wskaż koniec promienia i kliknij, aby zapisać.')
        count = tr(' Oznaczono: {0}.').format(len(self.refs)) if self.refs else ''
        return f'{name} — {tr(GUIDE[self.tool])}{count}'

    def reset(self):
        self.points, self.refs = [], []
        self.cursor = self.snapped = None
        self.drag = None
        self.tool = 'select'
        self.options = {}

    def select(self, uid):
        if uid != self.selected:
            self.flush_pending()
        self.selected = uid if any(x['id'] == uid for x in self.items) else None
        self.canvas.geometry_selected.emit(self.selected or '')
        self.canvas.update()

    def item(self, uid):
        return next((obj for obj in self.items if obj['id'] == uid), None)

    def _commit(self, new, uid):
        new = validate_objects(new, self.shape)
        self.canvas.begin_edit()
        self.items = new
        self.selected = uid
        self.canvas.changed.emit()
        self.select(uid)

    def promote(self, row):
        obj = promote_measurement(self.canvas.measurements[row])
        if not obj:
            return None
        self.flush_pending()
        self.canvas.begin_edit()
        self.items = [*self.items, obj]
        del self.canvas.measurements[row]
        self.selected = obj['id']
        self.canvas.changed.emit()
        self.select(obj['id'])
        return obj['id']

    def apply_styles(self, uids, fields):
        updated = [dict(item, style=dict(item['style'], **fields))
                   if item['id'] in uids else item for item in self.items]
        if updated != self.items:
            self._commit(updated, self.selected)

    def style(self, uid, **fields):
        if not self.item(uid):
            return
        new = [dict(obj, **fields) if obj['id'] == uid else obj for obj in self.items]
        if new != self.items:
            self._commit(new, uid)

    def dependents(self, uid):
        doomed = {uid}
        for obj in self.items:
            if any(ref in doomed for ref in obj['refs']):
                doomed.add(obj['id'])
        return doomed

    def delete(self, uid):
        doomed = self.dependents(uid)
        if self.item(uid):
            self._commit([obj for obj in self.items if obj['id'] not in doomed], None)

    def copy(self, uid):
        old = self.item(uid)
        if old:
            item = make_object(old['kind'], old['points'], old['refs'])
            clone = dict(deepcopy(old), id=item['id'], name=old['name'] + ' (kopia)')
            self._commit([*self.items, clone], clone['id'])

    def clear(self):
        if not (self.items or self.canvas.measurements):
            return
        self.canvas.cancel_pending()
        self.canvas.begin_edit()
        self.items, self.canvas.measurements = [], []
        self.selected = None
        self.canvas.changed.emit()
        self.select(None)

    @staticmethod
    def _distance(point, path):
        if not path:
            return float('inf')
        if len(path) == 1:
            return norm(sub(point, path[0]))
        return min(norm(sub(point, projection(point, a, b, True)))
                   if norm(sub(b, a)) > 1e-9 else norm(sub(point, a))
                   for a, b in zip(path, path[1:]))

    def _hit(self, point, allowed=None, exclude=()):
        scene = self.scene()
        tol = 9/self.canvas.zoom
        if allowed is None and self.selected:
            item = self.item(self.selected)
            if item and item['visible'] and item['style']['controls']:
                for index, handle in enumerate(scene[self.selected].handles):
                    if norm(sub(handle, point)) <= 6/self.canvas.zoom:
                        return self.selected, index
        if allowed is None:
            widget = self.canvas.image_to_widget(point)
            for uid, box in reversed(list(self.labels.items())):
                if box.contains(widget):
                    return uid, 'label'
        near = []
        for item in reversed(self.items):
            uid = item['id']
            if uid in exclude or not item['visible'] or (allowed is not None and item['kind'] not in allowed):
                continue
            result = scene[uid]
            distances = [self._distance(point, path) for path in result.paths]
            if result.triangle and allowed is None:
                distances.append(self._distance(point, result.triangle))
            distance = min(distances, default=float('inf'))
            if distance <= tol:
                near.append((distance, uid))
        if near:
            return min(near, key=lambda term: term[0])[1], None
        if allowed is None:
            for i, item in enumerate(self.canvas.measurements):
                obj = promote_measurement(item)
                if not obj:
                    continue
                r = Scene([obj], self.matrix, self.shape)[obj['id']]
                if any(self._distance(point, p) <= tol for p in r.paths):
                    return f'legacy:{i}', None
        return None, None

    def _snap(self, ip, exclude=None):
        self.snapped = None
        if not self.snap:
            return ip
        tol = 10/self.canvas.zoom
        nearby = []
        visible_lines = []
        scene = self.scene()
        for item in self.items:
            uid = item['id']
            if uid == exclude or not item['visible']:
                continue
            r = scene[uid]
            nearby.extend(r.handles)
            if item['kind'] == 'intersection' and r.anchor:
                nearby.append(r.anchor)
            if r.line and self._distance(ip, r.paths[0]) <= tol:
                visible_lines.append(r.line)
        # Limit pair checks to supporting lines near the cursor.
        visible_lines = visible_lines[-16:]
        for i, a in enumerate(visible_lines):
            for b in visible_lines[i+1:]:
                try:
                    nearby.append(intersection(a, b))
                except ValueError:
                    continue
        h, w = self.shape
        nearby = [p for p in nearby if 0 <= p[0] < w and 0 <= p[1] < h]
        if nearby:
            point = min(nearby, key=lambda p: norm(sub(ip, p)))
            if norm(sub(ip, point)) <= tol:
                self.snapped = point
        return self.snapped if self.snapped is not None else ip

    def _root(self, refs=None):
        scene = self.scene()
        a, b = (self.refs if refs is None else refs)[:2]
        return intersection(scene[a].line, scene[b].line)

    def _new(self, points, refs=None):
        try:
            obj = make_object(self.tool, points, self.refs if refs is None else refs,
                              style=self.new_style(self.tool), **self.options)
            if self.tool == 'comment':
                comment = self.comment_text()
                if comment is None:
                    return False
                obj['style'].update(signature='custom', custom_label=comment)
            result = Scene([*self.items, obj], self.matrix, self.shape)[obj['id']]
            if result.status and not result.paths and not result.label:
                raise ValueError(result.status)
            self._commit([*self.items, obj], obj['id'])
        except ValueError as exc:
            self.canvas.status.emit(str(exc))
            return False
        self.canvas.status.emit(result.status or tr('Zapisano {}.').format(f"{obj['name']}"))
        selected = self.selected
        self.reset()
        self.selected = selected
        self.canvas.geometry_state.emit(self.message)
        self.canvas.update()
        return True

    def _guided_point(self, point):
        if len(self.points) % 2 and norm(sub(point, self.points[-1])) < 1e-6:
            self.canvas.status.emit(tr('Wskaż dwa różne punkty prowadnicy.'))
            return
        self.points.append(point)
        if len(self.points) == 4:
            try:
                intersection(self.points[:2], self.points[2:4])
            except ValueError:
                del self.points[2:]
                self.canvas.status.emit(tr('Powierzchnie blach są równoległe. Wskaż drugą powierzchnię ponownie.'))
        if len(self.points) != 6:
            self.canvas.geometry_state.emit(self.message)
            self.canvas.update()
            return
        names = ('Prowadnica blachy 1', 'Prowadnica blachy 2', 'Prowadnica lica')
        guides = [make_object('infinite', self.points[i:i+2], name=tr(name),
                              style=self.new_style('infinite'))
                  for i, name in zip((0, 2, 4), names)]
        result = make_object('throat', [(0, 0)], refs=[g['id'] for g in guides],
                             method='straight', style=self.new_style('throat'))
        objects = [*self.items, *guides, result]
        measured = Scene(objects, self.matrix, self.shape)[result['id']]
        if not measured.paths:
            del self.points[4:]
            self.canvas.geometry_state.emit(self.message)
            self.canvas.status.emit(measured.status)
            self.canvas.update()
            return
        self._commit(objects, result['id'])
        self.reset()
        if measured.value is None:
            self.canvas.geometry_state.emit(
                tr('Zapisano r. Warunek a = r nie został spełniony. Spróbuj pomiaru z obrysu lica.'))
        else:
            self.canvas.geometry_state.emit(measured.label)
        self.canvas.update()

    def press(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            if self.tool == 'select':
                uid, _ = self._event_hit(event)
                if uid:
                    self.select(uid)
                    self.canvas.geometry_context.emit(event.globalPosition().toPoint())
            elif ((self.tool == 'polyline' and len(self.points) >= 2) or
                  (self.tool == 'a_contour' and len(self.points) >= 3)):
                self._new(self.points)
            else:
                self.reset()
                self.canvas.geometry_state.emit(self.message)
                self.canvas.update()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        ip = self.canvas.widget_to_image(event.position())
        if ip is None:
            return
        tool = self.tool
        if tool == 'select':
            uid, index = self._event_hit(event)
            self.select(uid)
            if uid:
                self.drag = (self.item(uid), index, ip)
            return
        if tool == 'guided_throat':
            self._guided_point(ip)
            return
        if (tool in (DERIVED | {'angle', 'intersection', 'throat'}) and
                len(self.refs) < (3 if tool == 'throat' else 1 if tool in DERIVED else 2)):
            allowed = LINES
            if tool == 'throat' and len(self.refs) == 2:
                method = self.options['method']
                allowed = {'polyline'} if method == 'contour' else (
                    LINES if method == 'straight' else LINES | {'polyline'})
            uid, _ = self._hit(ip, allowed=allowed, exclude=self.refs)
            if not uid:
                self.canvas.status.emit(tr('Kliknij widoczną linię lub kontur odpowiedniego typu.'))
                return
            self.refs.append(uid)
            if tool in ('angle', 'intersection') and len(self.refs) == 2:
                if not self._new(()) and self.refs:
                    self.refs.pop()
            if tool == 'throat' and len(self.refs) == 2:
                try:
                    self._root()
                except ValueError as exc:
                    self.refs.pop()
                    self.canvas.status.emit(str(exc))
            if tool == 'throat' and len(self.refs) == 3 and self.options['method'] != 'manual':
                if not self._new(((0, 0),)) and self.refs:
                    self.refs.pop()
            self.canvas.geometry_state.emit(self.message)
            self.canvas.update()
            return
        ip = self._snap(ip)
        if tool in ('scale', 'point', 'comment'):
            self._new((ip,))
        elif tool == 'throat':
            self._new(((0, 0), sub(ip, self._root())))
        elif tool in ('polyline', 'a_contour'):
            if len(self.points) < 500 and (not self.points or norm(sub(ip, self.points[-1])) > 1e-9):
                self.points.append(ip)
        elif not self.points:
            self.points.append(ip)
        else:
            self._new((self.points[0], ip))
        self.canvas.update()

    def _event_hit(self, event):
        ip = self.canvas.widget_to_image(event.position())
        if ip is None:
            return None, None
        uid, index = self._hit(ip)
        if uid and uid.startswith('legacy:'):
            uid = self.promote(int(uid.split(':')[1]))
        return uid, index

    def double_click(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.tool == 'select':
            uid, _ = self._event_hit(event)
            if uid:
                self.select(uid)
                self.drag = None
                self.canvas.geometry_properties.emit(uid)

    def _new_drag_obj(self, ip):
        original, index, start = self.drag
        kind = original['kind']
        points = list(map(tuple, original['points']))
        delta = sub(ip, start)
        if index == 'label':
            style = original['style']
            return dict(original, style=dict(style, label_x=style['label_x']+delta[0],
                                              label_y=style['label_y']+delta[1]))
        if kind == 'throat':
            root = self._root(original['refs'])
            if index == 0:
                points[0] = sub(ip, root)
            elif index == 1:
                vector = sub(ip, add(root, points[0]))
                return dict(original, method='manual', points=[list(points[0]), list(vector)])
            elif index is None:
                points[0] = add(points[0], delta)
        elif not points:
            return original
        elif index is None or (kind in ('circle', 'scale') and index == 0):
            if index == 0:
                delta = sub(ip, points[0])
            points = [add(p, delta) for p in points]
        else:
            points[index] = ip
        if kind in ('horizontal', 'vertical') and index == 0:
            axis = 1 if kind == 'horizontal' else 0
            p = list(points[1])
            p[axis] = ip[axis]
            points[1] = tuple(p)
        h, w = self.shape
        if kind != 'throat' and not all(0 <= x < w and 0 <= y < h for x, y in points):
            return original
        return dict(original, points=list(map(list, points)))

    def move(self, event):
        ip = self.canvas.widget_to_image(event.position())
        if ip is None:
            self.cursor = self.snapped = None
        elif self.drag:
            original, index, _ = self.drag
            self.cursor = self._snap(ip, original['id']) if isinstance(index, int) else ip
        else:
            self.cursor = (ip if self.tool == 'guided_throat' else
                           self._snap(ip) if self.tool != 'select' else None)
        self.canvas.update()

    def release(self, event):
        if not self.drag or event.button() != Qt.MouseButton.LeftButton:
            return
        ip = self.canvas.widget_to_image(event.position())
        original, index, start = self.drag
        if ip is not None and hypot(*sub(ip, start))*self.canvas.zoom >= 2:
            try:
                if isinstance(index, int):
                    ip = self._snap(ip, original['id'])
                changed = self._new_drag_obj(ip)
                if changed != original:
                    items = [changed if obj is original else obj for obj in self.items]
                    after = Scene(items, self.matrix, self.shape)[original['id']]
                    if not after.paths and original['kind'] not in ('scale', 'comment'):
                        raise ValueError(after.status or tr('Nieprawidłowa geometria.'))
                    self._commit(items, original['id'])
            except ValueError as exc:
                self.canvas.status.emit(str(exc))
        self.drag = self.cursor = self.snapped = None
        self.canvas.update()

    def display_objects(self):
        if self.draft is not None:
            obj = self.draft
            return [obj if item['id'] == obj['id'] else item for item in self.items], None
        if self.cursor is None:
            return self.items, None
        if self.drag:
            try:
                changed = self._new_drag_obj(self.cursor)
                return [changed if obj is self.drag[0] else obj for obj in self.items], None
            except ValueError:
                return self.items, None
        tool, points = self.tool, self.points
        if tool == 'guided_throat':
            return self.items, None
        if tool == 'throat' and len(self.refs) == 3 and self.options['method'] == 'manual':
            points = [(0, 0), sub(self.cursor, self._root())]
        elif tool in ('scale', 'point', 'comment'):
            points = [self.cursor]
        elif points and tool not in ('select', 'throat'):
            points = [*points, self.cursor]
        else:
            return self.items, None
        preview = make_object(tool, points, self.refs, style=self.new_style(tool), **self.options)
        return [*self.items, preview], preview['id']

    def paint(self, painter, image_rect):
        items, preview = self.display_objects()
        image_to_widget = self.canvas.image_to_widget
        def transform(pt):
            p = image_to_widget(pt)
            return p.x(), p.y()
        extent = (image_rect.left(), image_rect.top(), image_rect.right(), image_rect.bottom())
        painter.save()
        painter.setClipRect(image_rect)
        annotations = marks(items, self.canvas.measurements, self.matrix, self.canvas.mm_per_px,
                           self.shape, selected=self.selected, preview=preview,
                           show_scales=self.canvas.show_scale_bar)
        self.labels = {}
        for mark in annotations:
            box = paint_mark(painter, mark, transform, extent, self.canvas.zoom)
            if box is not None and mark.uid != preview:
                self.labels[mark.uid] = box
        scene = Scene(items, self.matrix, self.shape) if items is not self.items else self.scene()
        for uid in dict.fromkeys([self.selected, *self.refs, preview]):
            obj = self.item(uid)
            if uid not in scene or (obj and (not obj['visible'] or
                                               not obj['style']['controls'] and uid not in self.refs)):
                continue
            for pt in scene[uid].handles:
                p = image_to_widget(pt)
                painter.fillRect(QRectF(p.x()-4, p.y()-4, 8, 8), QColor('#17242d'))
                painter.setPen(QPen(QColor('#fff08a'), 1.5))
                painter.drawRect(QRectF(p.x()-4, p.y()-4, 8, 8))
        for pt in self.points:
            p = image_to_widget(pt)
            painter.setPen(QPen(QColor('#fff08a'), 2))
            painter.drawEllipse(p, 3, 3)
        if self.tool == 'guided_throat':
            vertices = list(self.points)
            if len(vertices) % 2 and self.cursor:
                vertices.append(self.cursor)
            painter.setPen(QPen(QColor('#fff08a'), 2))
            for a, b in zip(vertices[::2], vertices[1::2]):
                painter.drawLine(QLineF(image_to_widget(a), image_to_widget(b)))
        if self.snapped is not None:
            pt = image_to_widget(self.snapped)
            painter.setPen(QPen(QColor('#fff08a'), 1))
            painter.drawLine(QLineF(pt-QPointF(6, 0), pt+QPointF(6, 0)))
            painter.drawLine(QLineF(pt-QPointF(0, 6), pt+QPointF(0, 6)))
        painter.restore()
