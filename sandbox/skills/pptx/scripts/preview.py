"""Render an existing PPTX to PDF and PNG with an isolated Office profile."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf


def preview_office(source: Path, output_dir: Path) -> dict:
    source = source.resolve(strict=True)
    filters = {".pptx": "pdf:impress_pdf_Export", ".docx": "pdf:writer_pdf_Export"}
    if source.suffix.lower() not in filters:
        raise ValueError("Preview input must be a .pptx or .docx file.")
    office = shutil.which("soffice") or shutil.which("libreoffice")
    if not office:
        raise RuntimeError(
            "LibreOffice is unavailable; visual previews were not generated."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="nexaflow-pptx-preview-") as temporary:
        root = Path(temporary)
        result = subprocess.run(
            [
                office,
                "-env:UserInstallation=" + (root / "profile").as_uri(),
                "--headless",
                "--norestore",
                "--nodefault",
                "--convert-to",
                filters[source.suffix.lower()],
                "--outdir",
                str(root),
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        pdf = root / (source.stem + ".pdf")
        if result.returncode or not pdf.is_file():
            raise RuntimeError(
                "PPTX preview conversion failed: "
                + (result.stderr or result.stdout)[-1500:]
            )
        with pymupdf.open(pdf) as document:
            count = len(document)
            if not 1 <= count <= 100:
                raise ValueError("Preview supports 1 to 100 slides per invocation.")
        images = []
        for index in range(count):
            target = output_dir / f"slide-{index + 1:03}.png"
            with pymupdf.open(pdf) as document:
                page = document[index]
                scale = min(1600 / page.rect.width, 900 / page.rect.height)
                page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).save(
                    target
                )
            images.append(str(target))
        final_pdf = output_dir / "preview.pdf"
        shutil.copyfile(pdf, final_pdf)
    return {
        "pdf": str(final_pdf),
        "images": images,
        "page_count": count,
        "visual_review": "not_performed",
    }


def preview_deck(source: Path, output_dir: Path) -> dict:
    if source.suffix.lower() != ".pptx":
        raise ValueError("Presentation input must be a .pptx file.")
    return preview_office(source, output_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("presentation", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(preview_deck(args.presentation, args.output_dir), ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
