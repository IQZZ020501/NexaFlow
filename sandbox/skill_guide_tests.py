"""Draft Skill validation stays compatible with the platform import boundary."""

import importlib.util
import stat
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile, ZipInfo


def validator():
    source = Path(__file__).parent / "skills/skill-creator/scripts/validate.py"
    spec = importlib.util.spec_from_file_location("skill_validator", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MARKDOWN = b'---\nname: "example"\ndescription: "Use on supplied metrics."\n---\n\nInspect and report.\n'


class SkillGuideTests(unittest.TestCase):
    def test_every_maintained_guide_passes_import_structure_check(self):
        root = Path(__file__).parent / "skills"
        for name in ("documents", "pdf", "pptx", "spreadsheets", "skill-creator"):
            with self.subTest(skill=name):
                report = validator().validate(root / name)
                self.assertEqual(report["status"], "passed")

    def test_single_root_zip_and_markdown(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            (source / "SKILL.md").write_bytes(MARKDOWN)
            self.assertEqual(
                validator().validate(source / "SKILL.md")["name"], "example"
            )
            archive = source / "package.zip"
            with ZipFile(archive, "w") as output:
                output.writestr("example/SKILL.md", MARKDOWN)
                output.writestr("example/references/example.txt", b"Reference")
            self.assertEqual(validator().validate(archive)["files"], 2)

    def test_rejects_unsafe_paths_links_and_multiple_roots(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "bad.zip"
            link = ZipInfo("references/link")
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            for entry in (
                "../escape",
                "/absolute",
                "C:/host",
                "a\\b",
                "other/SKILL.md",
                link,
            ):
                with self.subTest(entry=str(entry)):
                    with ZipFile(source, "w") as archive:
                        archive.writestr("SKILL.md", MARKDOWN)
                        archive.writestr(entry, b"invalid")
                    with self.assertRaises(ValueError):
                        validator().validate(source)

    def test_rejects_oversized_body_and_expanded_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "package.zip"
            for content in (b"x" * 12001, b"x" * (2 * 1024 * 1024)):
                with ZipFile(source, "w") as archive:
                    archive.writestr("SKILL.md", MARKDOWN + content)
                with self.assertRaises(ValueError):
                    validator().validate(source)
