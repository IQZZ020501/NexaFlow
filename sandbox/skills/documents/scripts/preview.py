"""Generate DOCX page previews without changing the source document."""

import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if args.document.suffix.lower() != ".docx":
        raise ValueError("Document input must be a .docx file.")
    source = Path(__file__).resolve().parents[2] / "pptx/scripts/preview.py"
    spec = importlib.util.spec_from_file_location("office_preview", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print(
        json.dumps(
            module.preview_office(args.document, args.output_dir), ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
