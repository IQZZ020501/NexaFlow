"""Direct DOCX/XLSX editing and PDF page/form operations in the guest."""

try:
    from ..job import execute
except ImportError:
    from job import execute

OFFICE_CHECK = r"""
import csv, hashlib, io, json, tempfile, zipfile
from pathlib import Path
from docx import Document
from docx.shared import Inches
from PIL import Image
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation

def hashes(path, prefixes):
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        return {name: hashlib.sha256(archive.read(name)).hexdigest()
                for name in archive.namelist() if name.startswith(prefixes)}

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    document = Document()
    document.sections[0].header.paragraphs[0].text = 'Preserved header'
    p = document.add_paragraph()
    p.add_run('Editable ').bold = True
    p.add_run('body').italic = True
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(1, 0).text = 'Name', 'Alice'
    image = io.BytesIO()
    Image.new('RGB', (100, 60), '#336659').save(image, format='PNG')
    document.add_picture(io.BytesIO(image.getvalue()), width=Inches(2))
    word = root / 'document.docx'
    document.save(word)
    media = hashes(word, ('word/media/',))
    for index in range(3):
        edited = Document(word)
        edited.paragraphs[0].runs[1].text = f'body revision {index+1}'
        edited.save(word)
        result = Document(word)
        assert result.paragraphs[0].runs[0].bold and result.paragraphs[0].runs[1].italic
        assert result.sections[0].header.paragraphs[0].text == 'Preserved header'
        assert result.tables[0].cell(1, 0).text == 'Alice'
        assert hashes(word, ('word/media/',)) == media

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Data'
    for row in csv.reader(io.StringIO('ID,Amount,Literal\n00123,4,=1+1\n00456,7,ordinary\n')):
        sheet.append(row)
    for row in (2, 3):
        sheet.cell(row, 2).value = int(sheet.cell(row, 2).value)
    sheet['C2'].data_type = 's'
    sheet['B4'] = '=SUM(B2:B3)'
    sheet['A1'].comment = Comment('Keep comment', 'Fixture')
    sheet.freeze_panes = 'A2'
    validation = DataValidation(type='whole', operator='between', formula1=0, formula2=100)
    sheet.add_data_validation(validation)
    validation.add('B2:B3')
    chart = BarChart()
    chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    sheet.add_chart(chart, 'E2')
    sheet.add_image(__import__('openpyxl').drawing.image.Image(io.BytesIO(image.getvalue())), 'E20')
    excel = root / 'workbook.xlsx'
    workbook.save(excel)
    preserved = hashes(excel, ('xl/media/', 'xl/charts/'))
    for index in range(3):
        edited = load_workbook(excel, data_only=False, keep_links=True)
        edited['Data']['B2'] = 5 + index
        edited.save(excel)
        result = load_workbook(excel, data_only=False)
        data = result['Data']
        assert data['A2'].value == '00123'
        assert data['C2'].value == '=1+1' and data['C2'].data_type == 's'
        assert data['B4'].value == '=SUM(B2:B3)'
        assert data['A1'].comment.text == 'Keep comment'
        assert data.freeze_panes == 'A2' and len(data.data_validations.dataValidation) == 1
        assert hashes(excel, ('xl/media/', 'xl/charts/')) == preserved
        result.close()
        edited.close()

    print(json.dumps({'docx_revisions': 3, 'xlsx_revisions': 3, 'csv_ids_preserved': True,
                      'formulas_preserved': True}))
"""


PDF_CHECK = r"""
import json, tempfile
from pathlib import Path
import pymupdf
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    pdf = pymupdf.open()
    for number in range(1, 4):
        page = pdf.new_page()
        page.insert_text((72, 72), f'Page {number}')
    widget = pymupdf.Widget()
    widget.field_name, widget.field_type = 'reviewer', pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.rect = pymupdf.Rect(72, 100, 240, 130)
    page = pdf[0]
    page.add_widget(widget)
    form = root / 'form.pdf'
    pdf.save(form)
    pdf.close()
    with pymupdf.open(form) as pdf:
        form_page = pdf[0]
        field = next(form_page.widgets())
        field.field_value = 'Ada'
        field.update()
        pdf.save(root / 'filled.pdf')
        subset = pymupdf.open()
        subset.insert_pdf(pdf, from_page=2, to_page=2)
        subset.insert_pdf(pdf, from_page=1, to_page=1)
        subset[0].set_rotation(90)
        subset.save(root / 'subset.pdf')
        subset.close()
    with pymupdf.open(root / 'filled.pdf') as filled:
        form_page = filled[0]
        assert next(form_page.widgets()).field_value == 'Ada'
    with pymupdf.open(root / 'subset.pdf') as subset:
        assert len(subset) == 2 and subset[0].rotation == 90
        assert 'Page 3' in subset[0].get_text() and 'Page 2' in subset[1].get_text()
        assert subset[0].get_pixmap().width > 0
    print(json.dumps({'pdf_pages_and_forms': True}))
"""


def check_office_authoring():
    result = execute({"code": OFFICE_CHECK, "limits": {"timeout_ms": 20000}})
    assert result["ok"], result
    assert '"xlsx_revisions": 3' in result["stdout"], result
    pdf = execute({"code": PDF_CHECK, "limits": {"timeout_ms": 10000}})
    assert pdf["ok"], pdf
    assert '"pdf_pages_and_forms": true' in pdf["stdout"], pdf
    return result
