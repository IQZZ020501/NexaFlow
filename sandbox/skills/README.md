# NexaFlow Skills

Each child directory is a Skill bundle. An executable artifact Skill contains
`SKILL.md` frontmatter with `entrypoint` and `artifact-format`, plus the named
Python entrypoint below `scripts/`. These fixed renderers and their locked
dependencies are baked into the OpenSandbox execution image. Calls accept JSON
content/data only, never a replacement program or runtime requirements install.

The built-in bundles below are NexaFlow-authored renderers:

- `documents` — Word and Google Docs-targeted DOCX workflows
- `pdf` — PDF creation, inspection, and rendering workflows
- `pptx` — new PowerPoint decks with templates, brand themes, icons, and tables
- `spreadsheets` — spreadsheet creation and analysis guidance

They are intentionally small and project-specific; they are not copies of an
upstream Skill distribution.

To add a platform renderer, add its bundle here and register a fixed published
Tool contract, then rebuild/version the execution image. There is no host Skills
directory or local Worker runner. Workspace-uploaded SKILL.md/ZIP packages are a
separate versioned control-plane feature with lazy loading and ledger-backed
scripts; see [Skills](../../docs/SKILLS.md) and
[OpenSandbox deployment](../../deploy/opensandbox/README.md).
