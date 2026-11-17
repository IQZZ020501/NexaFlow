# NexaFlow built-in Skills

These project-authored guides are maintained for the actual NexaFlow runtime;
they are not verbatim copies of third-party proprietary Skill files.

- `documents`: read/create/revise DOCX, preserving the source and previewing pages.
- `pdf`: PyMuPDF page operations, forms, extraction and rendering.
- `pptx`: free-form python-pptx design and targeted revisions of editable decks.
- `spreadsheets`: pandas analysis and openpyxl workbook preservation.
- `skill-creator`: author and validate importable workspace Skill packages.

Each selectable Tool accepts `{}` and loads the full version-pinned SKILL.md.
The model then uses already-authorized bash in the Run-private OpenSandbox guest.
Skill loading itself does not execute code or grant new permissions. The business
image contains only these Markdown guides; helper scripts and locked Python/Office
dependencies belong to the execution image.

PPTX helpers inventory existing packages and render previews. DOCX uses the same
Office preview support. Skill Creator validates package structure and limits;
it does not install/publish a Skill or guarantee script safety. Conversion and
structural validation do not constitute visual review or prove full format fidelity.

The old PPT fixed layout, composition, PPTD/WASM and compatibility implementations
have been removed. The three remaining render.py files serve only existing
DOCX/PDF/XLSX frozen legacy contracts. New calls use direct Python workflows;
Workflows use authorized MCP Tools or Agent nodes for file work. Standalone Python
Tools and Python Code nodes have been removed.

See [Skills](../../docs/SKILLS.md) for permissions, package imports, migration and
delivery, and [OpenSandbox deployment](../../deploy/opensandbox/README.md) for the
execution boundary.
