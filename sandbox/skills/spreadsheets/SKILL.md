---
name: spreadsheets
description: Create formatted XLSX workbooks from structured sheet data.
entrypoint: scripts/render.py
artifact-format: xlsx
---

# NexaFlow spreadsheets

Use this Skill when the requested deliverable is an Excel `.xlsx` workbook.
The Tool accepts structured sheets and rows; the bundled renderer owns workbook
creation and verification.

## Runtime contract

- The Agent supplies sheet data, not Python source code.
- A row value beginning with `=` remains an Excel formula.
- `scripts/render.py` applies readable headers, filters, panes, and widths.
- The renderer reopens the XLSX and checks sheet names and representative cells.

## Workbook flow

1. Choose this Skill for XLSX output.
2. Provide one or more named sheets with rectangular row arrays.
3. Use formulas for derived values and explicit scalar values for inputs.

This Skill creates new workbooks. It does not preserve macros or perform
lossless edits of an uploaded XLSX binary.
