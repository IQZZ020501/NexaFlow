"""Pure, bounded expectations for actual delivered files."""

import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.artifacts.services import artifact_workspace_path


@dataclass(frozen=True)
class EvaluationFileExpectation:
    path: str
    text_contains: tuple[str, ...] = ()
    text_not_contains: tuple[str, ...] = ()
    cells: dict[str, Any] = field(default_factory=dict)
    min_pages: int | None = None
    min_slides: int | None = None
    changed: bool = False
    require_inspection: bool = True

    @classmethod
    def from_dict(cls, value: Any):
        if not isinstance(value, dict):
            raise ValueError("Each file expectation must be an object.")
        path = artifact_workspace_path(value.get("path"))
        texts = {}
        for key in ("text_contains", "text_not_contains"):
            items = value.get(key, [])
            if not isinstance(items, list) or len(items) > 50 or any(
                not isinstance(item, str) or not 0 < len(item) <= 2000 for item in items
            ):
                raise ValueError(f"files.{key} must contain at most 50 bounded strings.")
            texts[key] = tuple(items)
        cells = value.get("cells", {})
        if not isinstance(cells, dict) or len(cells) > 100:
            raise ValueError("files.cells must be an object with at most 100 cells.")
        for address, content in cells.items():
            if not isinstance(address, str) or not re.fullmatch(r"[^!\x00-\x1f]{1,31}![A-Z]{1,3}[1-9][0-9]{0,6}", address):
                raise ValueError("A file cell address must be Sheet!A1.")
            cell = address.rsplit("!", 1)[1]
            letters = cell.rstrip("0123456789")
            column = 0
            for letter in letters:
                column = column * 26 + ord(letter) - ord("A") + 1
            if column > 16384 or int(cell[len(letters):]) > 1048576:
                raise ValueError("A file cell address is outside spreadsheet bounds.")
            if not (content is None or isinstance(content, (str, bool, int, float))):
                raise ValueError("A file cell expectation must be a JSON scalar.")
            if isinstance(content, str) and len(content) > 2000 or isinstance(content, float) and not math.isfinite(content):
                raise ValueError("A file cell expectation is invalid.")
        counts = {}
        for key in ("min_pages", "min_slides"):
            count = value.get(key)
            if count is not None and (type(count) is not int or not 1 <= count <= 500):
                raise ValueError(f"files.{key} must be between 1 and 500.")
            counts[key] = count
        for key in ("changed", "require_inspection"):
            if key in value and type(value[key]) is not bool:
                raise ValueError(f"files.{key} must be boolean.")
        return cls(
            path=path, **texts, cells=cells, **counts,
            changed=value.get("changed", False),
            require_inspection=value.get("require_inspection", True),
        )


def file_expectations(value: Any) -> tuple[EvaluationFileExpectation, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("expect.files must be an array with at most 8 files.")
    result = tuple(EvaluationFileExpectation.from_dict(item) for item in value)
    if len({item.path for item in result}) != len(result):
        raise ValueError("File expectation paths must be unique within a turn.")
    return result


@dataclass(frozen=True)
class EvaluationFileObservation:
    path: str
    artifact_id: str = ""
    sha256: str = ""
    text: str = ""
    cells: dict[str, Any] = field(default_factory=dict)
    pages: int = 0
    slides: int = 0
    inspection_passed: bool = False
    changed: bool = False
    error: bool = False


def evaluate_files(expected, observed) -> list[str]:
    files = {item.path: item for item in observed}
    failures = []
    for number, item in enumerate(expected, 1):
        prefix = f"file:{number}"
        actual = files.get(item.path)
        if actual is None:
            failures.append(f"{prefix}:missing")
            continue
        if actual.error:
            failures.append(f"{prefix}:unreadable")
            continue
        if item.require_inspection and not actual.inspection_passed:
            failures.append(f"{prefix}:inspection_missing")
        for index, text in enumerate(item.text_contains, 1):
            if text not in actual.text:
                failures.append(f"{prefix}:text_missing:{index}")
        for index, text in enumerate(item.text_not_contains, 1):
            if text in actual.text:
                failures.append(f"{prefix}:text_forbidden:{index}")
        for index, (address, value) in enumerate(item.cells.items(), 1):
            if address not in actual.cells or actual.cells[address] != value or isinstance(actual.cells[address], bool) != isinstance(value, bool):
                failures.append(f"{prefix}:cell:{index}")
        if item.min_pages is not None and actual.pages < item.min_pages:
            failures.append(f"{prefix}:pages")
        if item.min_slides is not None and actual.slides < item.min_slides:
            failures.append(f"{prefix}:slides")
        if item.changed and not actual.changed:
            failures.append(f"{prefix}:unchanged")
    return failures
