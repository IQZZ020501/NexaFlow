"""Preserved renderer regression checks, independent of the retired Broker."""

import base64
import json
from io import BytesIO
from zipfile import ZipFile

try:
    from ..job import execute as execute_request
except ImportError:
    from job import execute as execute_request


def check_builtin_skill_entrypoints() -> None:
    requests = [
        (
            "documents",
            "docx",
            "skill-report.docx",
            {"content": "# Quarterly report\n\nReady for review.\n\n- Revenue\n- Cost"},
            "word/document.xml",
        ),
        (
            "pdf",
            "pdf",
            "skill-report.pdf",
            {"content": "# Quarterly report\n\nReady for review.\n\n- Revenue\n- Cost"},
            None,
        ),
        (
            "spreadsheets",
            "xlsx",
            "skill-report.xlsx",
            {
                "workbook": {
                    "sheets": [
                        {
                            "name": "Summary",
                            "rows": [
                                ["Metric", "Value"],
                                ["Revenue", 12],
                                ["Cost", 5],
                                ["Profit", "=B2-B3"],
                            ],
                        }
                    ]
                }
            },
            "xl/workbook.xml",
        ),
    ]
    for skill, artifact_format, filename, inputs, archive_member in requests:
        result = execute_request(
            {
                "skill": skill,
                "stdin": json.dumps(inputs),
                "artifact": {"format": artifact_format, "filename": filename},
            }
        )
        assert result["ok"] is True, result
        content = base64.b64decode(result["artifact"]["content_base64"])
        assert f'"renderer":"{skill}"' in result["stdout"], result
        if artifact_format == "pdf":
            assert content.startswith(b"%PDF"), content[:16]
        else:
            with ZipFile(BytesIO(content)) as archive:
                assert archive_member in archive.namelist(), archive.namelist()
