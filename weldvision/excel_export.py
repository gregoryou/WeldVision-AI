"""Portable, dependency-free OOXML .xlsx export for WeldVision on Windows.

Exports snapshot numerical values (not recalculated Excel formulas): the source
and metadata remain in the .weldproj archive. Uses inline strings; no macros or
external links and no additional installation dependency.
"""
from __future__ import annotations
from .i18n import tr
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED
import math


def _xml(value):
    # XML 1.0 forbids most control characters even in escaped strings.
    value=''.join(ch for ch in str(value)
                  if ord(ch) in (9,10,13) or 32 <= ord(ch) <= 0xD7FF
                  or 0xE000 <= ord(ch) <= 0xFFFD or 0x10000 <= ord(ch) <= 0x10FFFF)
    return escape(value, {'"':'&quot;', "'":'&apos;'})


def _column(number):
    text=''
    while number:
        number, rem=divmod(number-1,26)
        text=chr(65+rem)+text
    return text


def _sheet_xml(rows, widths):
    rows=list(rows)
    xml=['<?xml version="1.0" encoding="utf-8"?>',
         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
         '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" '
         'topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
         '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
         '</sheetView></sheetViews>',
         '<sheetFormatPr defaultRowHeight="16"/>',
         '<cols>']
    for i,w in enumerate(widths,1):
        xml.append(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>')
    xml.append('</cols><sheetData>')
    for row_num,values in enumerate(rows,1):
        xml.append(f'<row r="{row_num}" ht="{27 if row_num == 1 else 18}" customHeight="1">')
        for col_num,value in enumerate(values,1):
            coord=f'{_column(col_num)}{row_num}'
            style=' s="1"' if row_num==1 else ''
            if value is None or isinstance(value,float) and not math.isfinite(value):
                continue
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                xml.append(f'<c r="{coord}"{style}><v>{value}</v></c>')
            else:
                xml.append(f'<c r="{coord}"{style} t="inlineStr"><is><t xml:space="preserve">{_xml(value)}</t></is></c>')
        xml.append('</row>')
    xml.append('</sheetData>')
    if rows and rows[0]:
        xml.append(f'<autoFilter ref="A1:{_column(len(rows[0]))}{max(1,len(rows))}"/>')
    xml.append('</worksheet>')
    return ''.join(xml)


def export_xlsx(path, samples, fields):
    path=Path(path)
    result_rows=[[name for name in fields]]
    measure_rows=[[tr('ID próbki'),tr('Próbka'),tr('Nr'),tr('Typ'),tr('Wymiar [mm]'),
                   tr('Status'),tr('Punkty [px]'),tr('Skala [mm/px]'),tr('Tryb kalibracji'),
                   tr('Jednostka'),tr('Podpis na fotografii'),tr('Nazwa'),tr('Metoda'),tr('ID obiektu'),
                   tr('Odniesienia'),'r [mm]','d [mm]',tr('Widoczność'),tr('Macierz px → mm'),tr('Kąt [°]')]]
    from .measurements import measurement_mm
    from .geometry import Scene, METHODS, legacy_caption
    import json
    for sample in samples:
        summary=sample.summary()
        result_rows.append([summary.get(k) for k in fields])
        matrix = sample.calibration_matrix()
        calibration = ('siatka_2d' if len(sample.cal_points) == 3 else
                       'odcinek_1d' if len(sample.cal_points) == 2 else
                       'skala_legacy' if matrix else 'brak')
        for j, m in enumerate(sample.measurements, 1):
            try:
                value = measurement_mm(m, sample.mm_per_px, matrix)
            except ValueError:
                value = None
            status = (tr('WYMAGA POWTÓRZENIA - algorytm 3.2') if m['kind']=='a' else
                      tr('BRAK KALIBRACJI') if matrix is None else
                      tr('NIEPRAWIDŁOWA GEOMETRIA') if value is None else 'OK')
            measure_rows.append([sample.uid, sample.name, j, m['kind'], value,
                                 status, json.dumps(m['points'], ensure_ascii=False),
                                 sample.mm_per_px, calibration, 'mm',
                                 legacy_caption(m, value), None, None, None, None,
                                 None, None, tr('Tak'), json.dumps(matrix)])
        scene = Scene(sample.geometry_objects, matrix, sample.dimensions)
        for j, item in enumerate(sample.geometry_objects, len(sample.measurements)+1):
            r = scene[item['id']]
            diameter = 2*r.radius if item['diameter'] and r.radius is not None else None
            measure_rows.append([
                sample.uid, sample.name, j, item['kind'], r.value if r.unit == 'mm' else None,
                r.status or 'OK', json.dumps(item['points'], ensure_ascii=False),
                sample.mm_per_px, calibration, r.unit, r.label, item['name'],
                METHODS.get(item.get('method')), item['id'], json.dumps(item['refs']),
                r.radius, diameter, tr('Tak') if item['visible'] else tr('Nie'), json.dumps(matrix),
                r.value if r.unit == '°' else None
            ])
    info_rows=[[tr('Metadane'),tr('Wartość')],
               [tr('Wersja'),'WeldVision AI 3.5.0'],
               [tr('Utworzono UTC'),datetime.now(timezone.utc).isoformat(timespec='seconds')],
               [tr('Definicja a'),tr('Największy równoramienny trójkąt wpisany w ręcznie wyznaczony kontur spoiny; ISO 2553:2019')],
               [tr('Dokładność a'),tr('Przybliżenie zależne od gęstości punktów konturu, wskazania powierzchni i brzegów. Promień odrzuconego pomiaru pozostaje w kolumnie r.')],
               [tr('Kalibracja'),tr('Siatka 10×10 mm: 3 sąsiednie przecięcia, w płaszczyźnie próbki')],
               [tr('Uwaga'),tr('Pole [mm²] i objętość [cm³/m] są liczbowo równe na metr długości')],
               [tr('Obliczenia'),tr('Eksport zawiera migawkę wyników. Po zmianie projektu wykonaj nowy eksport.')],
               [tr('Pomiary historyczne'),tr('a z wersji 3.2.x nie jest traktowane jako wynik i wymaga ponownego pomiaru.')]]
    sheets=[(tr('Wyniki'),result_rows,[36,27,28,18,18,30,15,16,22,17,32,16,17,18,17,18,17,27,27,40]),
            (tr('Pomiary'),measure_rows,[36,27,8,20,17,32,62,18,19,13,40,24,28,36,55,14,14,14,34,14]),
            (tr('Opis'),info_rows,[28,92])]
    with ZipFile(path,'w',ZIP_DEFLATED,compresslevel=6) as zipf:
        zipf.writestr('[Content_Types].xml',
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          +''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,4))
          +'</Types>')
        zipf.writestr('_rels/.rels',
          '<?xml version="1.0" encoding="UTF-8"?>'
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
          '</Relationships>')
        zipf.writestr('xl/workbook.xml',
          '<?xml version="1.0" encoding="UTF-8"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          '<bookViews><workbookView activeTab="0"/></bookViews><sheets>'
          +''.join(f'<sheet name="{_xml(name)}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_,_) in enumerate(sheets,1))
          +'</sheets></workbook>')
        zipf.writestr('xl/_rels/workbook.xml.rels',
          '<?xml version="1.0" encoding="UTF-8"?>'
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
          +''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,4))
          +'<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
          '</Relationships>')
        zipf.writestr('xl/styles.xml',
          '<?xml version="1.0" encoding="UTF-8"?>'
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
          '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts>'
          '<fills count="3"><fill><patternFill patternType="none"/></fill>'
          '<fill><patternFill patternType="gray125"/></fill>'
          '<fill><patternFill patternType="solid"><fgColor rgb="FF175B8B"/><bgColor indexed="64"/></patternFill></fill></fills>'
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
          '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
          '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/></cellXfs>'
          '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
          '</styleSheet>')
        for i,(_,rows,widths) in enumerate(sheets,1):
            zipf.writestr(f'xl/worksheets/sheet{i}.xml',_sheet_xml(rows,widths))
    return path
