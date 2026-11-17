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
- Formulas are preserved without calculation. A formula without a saved cached
  result reads as an empty value in readers that do not recalculate workbooks.
- `scripts/render.py` applies readable headers, filters, panes, capped widths,
  wrap-aware row heights, semantic alignment, hidden gridlines, and light row
  banding.
- The renderer reopens the XLSX and checks every requested cell, sheet names,
  header alignment, and common formula-error tokens.

## Workbook flow

1. Choose this Skill for XLSX output.
2. Provide one or more named sheets with rectangular row arrays.
3. Follow the user's choice of stored values or formulas. If numeric amounts,
   totals, or directly readable values are required, calculate them first and
   write actual numbers. Formula strings do not meet a stored-value requirement.
4. Before delivery, reopen the saved workbook with `data_only=True` and verify
   the required values. The renderer and openpyxl do not calculate formulas;
   do not depend on Excel opening and recalculating the file later.
5. Preserve formulas when requested. Review `inspection.details.uncached_formulas`
   and inspection warnings; correct unmet value requirements before claiming
   completion, and explain any remaining need for formula recalculation.

This Skill creates new workbooks. It does not preserve macros or perform
lossless edits of an uploaded XLSX binary.
