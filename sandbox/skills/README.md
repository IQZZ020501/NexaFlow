# NexaFlow Skills

Each child directory is a Skill bundle. An executable artifact Skill contains
`SKILL.md` frontmatter with `entrypoint` and `artifact-format`, plus the named
Python entrypoint below `scripts/`. It may also include references, assets, and
an optional `requirements.txt`. The Worker stages only the selected Skill and
runs its read-only entrypoint with JSON input from the Agent Tool call. Package
requirements are installed into an ephemeral per-run directory.

The built-in bundles below are NexaFlow-authored renderers:

- `documents` — Word and Google Docs-targeted DOCX workflows
- `pdf` — PDF creation, inspection, and rendering workflows
- `spreadsheets` — spreadsheet creation and analysis guidance

They are intentionally small and project-specific; they are not copies of an
upstream Skill distribution.

To add an executable managed Skill, create a lowercase directory under
`SANDBOX_SKILLS_DIR`, declare its entrypoint and artifact format in `SKILL.md`,
then restart the Worker. A corresponding published Tool contract is still
required before an Agent or Workflow can select it.
