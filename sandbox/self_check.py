"""Behavioral checks inside the execution image, without business credentials."""

import base64
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

try:
    from .job import MAX_FILE, execute
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from job import MAX_FILE, execute


def check_execution():
    try:
        from .renderer_checks.entrypoints import check_builtin_skill_entrypoints
        from .renderer_checks.quality import check_builtin_skill_quality_guards
    except ImportError:
        from renderer_checks.entrypoints import check_builtin_skill_entrypoints
        from renderer_checks.quality import check_builtin_skill_quality_guards

    check_builtin_skill_entrypoints()
    check_builtin_skill_quality_guards()
    result = execute(
        {
            "code": "import json, sys; print(json.loads(sys.stdin.read())['value'] + 1)",
            "stdin": '{"value": 2}',
        }
    )
    assert result["ok"] and result["stdout"].strip() == "3", result
    secret = execute(
        {"code": "import os; print(os.environ.get('DATABASE_URL', 'absent'))"}
    )
    assert secret["stdout"].strip() == "absent", secret
    for request in (
        {"code": "while True: pass", "limits": {"timeout_ms": 200}},
        {"code": "print('x' * 200000)"},
    ):
        try:
            execute(request)
        except (TimeoutError, ValueError):
            pass
        else:
            raise AssertionError("A bounded program exceeded its limit")
    for skill, fmt, inputs in (
        ("documents", "docx", {"content": "# Functional check\n\nHello OpenSandbox"}),
        ("pdf", "pdf", {"content": "# Functional check\n\nHello OpenSandbox"}),
        (
            "spreadsheets",
            "xlsx",
            {
                "workbook": {
                    "sheets": [{"name": "Data", "rows": [["Name", "Value"], ["A", 3]]}]
                }
            },
        ),
        (
            "pptx",
            "pptx",
            {
                "presentation": {
                    "title": "Functional check",
                    "slides": [
                        {
                            "layout": "bullets",
                            "title": "Result",
                            "bullets": ["Hello OpenSandbox"],
                        }
                    ],
                }
            },
        ),
    ):
        result = execute(
            {
                "skill": skill,
                "stdin": json.dumps(inputs),
                "artifact": {"filename": "check." + fmt, "format": fmt},
                "limits": {"timeout_ms": 10000},
            }
        )
        assert result["ok"], result
        content = base64.b64decode(result["artifact"]["content_base64"])
        assert 0 < len(content) <= MAX_FILE
        assert content.startswith(b"%PDF" if fmt == "pdf" else b"PK")
    pptd = execute(
        {
            "skill": "pptx",
            "stdin": json.dumps(
                {
                    "presentation": {
                        "title": "PPTD functional check",
                        "scenario": "tech-engineering",
                        "design_system": "electric-violet-business",
                        "media": [
                            {
                                "filename": "pixel.png",
                                "content_base64": (
                                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
                                    "AAAAC0lEQVR42mP8/x8AAusB9Y9Zb6sAAAAASUVORK5CYII="
                                ),
                            }
                        ],
                        "slides": [
                            {
                                "page_type": "cover",
                                "background": {"type": "solid", "color": "$background"},
                                "elements": [
                                    {
                                        "elementId": "accent",
                                        "elementType": "shape",
                                        "bounds": [72, 72, 12, 396],
                                        "shapeName": "rect",
                                        "fill": {"type": "solid", "color": "$accent"},
                                    },
                                    {
                                        "elementId": "image",
                                        "elementType": "image",
                                        "bounds": [760, 72, 128, 128],
                                        "src": "media/pixel.png",
                                        "fit": {"mode": "cover"},
                                    },
                                    {
                                        "elementId": "title",
                                        "elementType": "text",
                                        "bounds": [118, 176, 720, 92],
                                        "content": {
                                            "style": "$title",
                                            "fontSize": 48,
                                            "text": "Offline PPTD",
                                        },
                                    },
                                    {
                                        "elementId": "body",
                                        "elementType": "text",
                                        "bounds": [120, 286, 650, 48],
                                        "content": {
                                            "style": "$body",
                                            "text": "Editable composition and native animation",
                                        },
                                    },
                                ],
                                "animations": [
                                    {
                                        "elementId": "title",
                                        "effect": "zoom-in",
                                        "trigger": "onClick",
                                        "durationMs": 600,
                                    },
                                    {
                                        "elementId": "body",
                                        "effect": "fade-in",
                                        "trigger": "afterPrevious",
                                    },
                                ],
                            }
                        ],
                    }
                }
            ),
            "artifact": {"filename": "pptd-check.pptx", "format": "pptx"},
            "limits": {"timeout_ms": 10000},
        }
    )
    assert pptd["ok"], pptd
    assert '"renderer":"open-kimi-pptd"' in pptd["stdout"], pptd
    pptd_content = base64.b64decode(pptd["artifact"]["content_base64"])
    with zipfile.ZipFile(io.BytesIO(pptd_content)) as archive:
        slide_xml = archive.read("ppt/slides/slide1.xml")
        assert b"<p:transition" in slide_xml
        assert b"<p:timing" in slide_xml
    for code in (
        "import os; os.symlink('/etc/passwd', output_path)",
        "import os; os.mkfifo(output_path)",
        "open(output_path, 'wb').write(b'x' * (5 * 1024 * 1024 + 1))",
    ):
        try:
            result = execute(
                {
                    "code": "import os; output_path = os.environ['NEXAFLOW_OUTPUT_PATH']; "
                    + code,
                    "artifact": {"filename": "invalid.txt", "format": "txt"},
                }
            )
        except (OSError, ValueError):
            pass
        else:
            assert not result["ok"], "Unsafe artifact accepted"
    # The configured image contains Python and Node; no host installations.
    with tempfile.TemporaryDirectory() as temporary:
        server = Path(temporary) / "server.py"
        server.write_text(
            "from mcp.server.mcpserver import MCPServer\ns = MCPServer('check', log_level='ERROR')\n"
            "@s.tool()\ndef echo(value: str) -> dict:\n return {'value': value}\ns.run('stdio')\n"
        )
        config = {
            "command": str(Path(os.sys.executable)),
            "args": [str(server)],
            "env": {},
        }
        discovered = execute(
            {
                "mcp": {"operation": "discover", "config": config, "timeout": 5},
                "limits": {"timeout_ms": 5000},
            }
        )
        assert discovered["ok"], discovered
        assert discovered["mcp"]["tools"][0]["name"] == "echo"
        called = execute(
            {
                "mcp": {
                    "operation": "call",
                    "config": config,
                    "timeout": 5,
                    "name": "echo",
                    "arguments": {"value": "isolated"},
                },
                "limits": {"timeout_ms": 5000},
            }
        )
        assert called["ok"], called
        payload = called["mcp"].get("structuredContent")
        if payload is None:
            payload = json.loads(called["mcp"]["content"][0]["text"])
        assert payload == {"value": "isolated"}, called


def main():
    assert os.geteuid() == 65532, (
        "Run the image checks as the unprivileged execution UID"
    )
    check_execution()
    print("EXECUTION_IMAGE_OK")


if __name__ == "__main__":
    main()
