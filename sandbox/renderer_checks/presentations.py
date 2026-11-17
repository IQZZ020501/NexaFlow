"""General Python authoring and three targeted PPTX revisions."""

try:
    from ..job import execute
except ImportError:
    from job import execute

AUTHORING_CHECK = r"""
import hashlib, io, json, os, tempfile, zipfile
from pathlib import Path
from PIL import Image
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

def preserved(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        return {name: hashlib.sha256(z.read(name)).hexdigest() for name in z.namelist()
                if name.startswith(('ppt/media/', 'ppt/embeddings/', 'ppt/charts/',
                                    'ppt/slideMasters/', 'ppt/slideLayouts/', 'ppt/theme/'))}

with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    deck = Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    title = slide.shapes.add_textbox(Inches(.8), Inches(.8), Inches(11), Inches(1.5))
    run = title.text_frame.paragraphs[0].add_run()
    run.text, run.font.bold, run.font.size = 'Original title', True, Pt(40)
    run.font.color.rgb = RGBColor.from_string('173C36')
    second = deck.slides.add_slide(deck.slide_layouts[6])
    data = ChartData()
    data.categories = ['A', 'B', 'C']
    data.add_series('Delivered', [4, 7, 9])
    second.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(1), Inches(8), Inches(5), data)
    second.notes_slide.notes_text_frame.text = 'Source: local test fixture. Preserve this note.'
    third = deck.slides.add_slide(deck.slide_layouts[6])
    image = io.BytesIO()
    Image.new('RGB', (240, 160), '#C9DED6').save(image, format='PNG')
    third.shapes.add_picture(io.BytesIO(image.getvalue()), Inches(1), Inches(1), width=Inches(6))
    source = root / 'source.pptx'
    deck.save(source)
    expected = preserved(source)
    current = source
    for revision in range(1, 4):
        edited = Presentation(current)
        target = edited.slides[0].shapes[0].text_frame.paragraphs[0].runs[0]
        if revision == 1:
            target.text = 'Revised title'
        elif revision == 2:
            target.font.size = Pt(44)
        else:
            target.font.color.rgb = RGBColor.from_string('296D60')
        current = root / f'revision-{revision}.pptx'
        edited.save(current)
        result = Presentation(current)
        assert len(result.slides) == 3
        assert result.slides[0].shapes[0].text_frame.paragraphs[0].runs[0].font.bold
        assert result.slides[1].notes_slide.notes_text_frame.text == second.notes_slide.notes_text_frame.text
        assert list(result.slides[1].shapes[0].chart.series[0].values) == [4, 7, 9]
        assert preserved(current) == expected
    Path(os.environ['NEXAFLOW_OUTPUT_PATH']).write_bytes(current.read_bytes())
    print(json.dumps({'revisions': 3, 'native_chart': True, 'preserved_parts': len(expected),
                      'notes_preserved': True, 'media_preserved': True}))
"""


def check_pptx_authoring():
    result = execute(
        {
            "code": AUTHORING_CHECK,
            "artifact": {"filename": "authoring-check.pptx", "format": "pptx"},
            "limits": {"timeout_ms": 15000},
        }
    )
    assert result["ok"], result
    assert result["artifact"]["inspection"]["status"] == "passed", result
    assert '"revisions": 3' in result["stdout"], result
    return result
