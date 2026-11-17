"""Conversation upload boundaries and bounded ZIP tree imports."""

import stat
import unittest
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from app.domain.projects.imports import import_file_tree


def archive(files):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as target:
        for path, content in files:
            target.writestr(path, content)
    return output.getvalue()


class ImportTests(unittest.TestCase):
    def test_preserves_paths_and_original_bytes(self):
        nested_zip = archive([("inner.txt", b"keep zipped")])
        files = import_file_tree(
            [
                ("folder/source.csv", b"amount\n12\n"),
                ("folder/__init__.py", b""),
                ("folder/nested.zip", nested_zip),
                (
                    "project.zip",
                    archive(
                        [
                            ("src/main.py", b"print(12)"),
                            ("README", b"example"),
                            ("src/__init__.py", b""),
                            ("node_modules/dependency.js", b"ignored"),
                            (".git/config", b"ignored"),
                            ("__MACOSX/metadata", b"ignored"),
                        ]
                    ),
                ),
            ]
        )
        self.assertEqual(
            {item["path"]: item["content"] for item in files},
            {
                "folder/source.csv": b"amount\n12\n",
                "folder/__init__.py": b"",
                "folder/nested.zip": nested_zip,
                "src/main.py": b"print(12)",
                "README": b"example",
                "src/__init__.py": b"",
            },
        )

    def test_rejects_unsafe_entries_duplicates_and_path_collisions(self):
        for path in (
            "../escape.txt",
            "/escape.txt",
            "a//b.txt",
            "a\\b.txt",
            "a/./b.txt",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                import_file_tree([("files.zip", archive([(path, b"unsafe")]))])
        for files in [
            [("a.txt", b"a"), ("a.txt", b"b")],
            [("a.txt", b"a"), ("a.txt/child.txt", b"b")],
            [("large.txt", b"x" * (5 * 1024 * 1024 + 1))],
            [(f"{i}.txt", b"x") for i in range(65)],
        ]:
            with self.assertRaises(ValueError):
                import_file_tree([("files.zip", archive(files))])
        with self.assertRaises(ValueError):
            import_file_tree(
                [("a.txt", b"a"), ("files.zip", archive([("a.txt", b"b")]))]
            )

    def test_rejects_links_invalid_archives_and_empty_imports(self):
        link = ZipInfo("link.txt")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        corrupt = bytearray(archive([("a.txt", b"payload")]))
        corrupt[35:37] = b"\xff\xff"
        for content in (
            b"not a zip",
            bytes(corrupt),
            archive([(link, b"/etc/passwd")]),
            archive([(".git/config", b"ignored")]),
        ):
            with self.assertRaises(ValueError):
                import_file_tree([("files.zip", content)])


if __name__ == "__main__":
    unittest.main()
