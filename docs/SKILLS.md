# NexaFlow Skills

NexaFlow Skills are read-only executable bundles. A file-producing Skill keeps
its format-specific instructions and renderer inside the bundle instead of
accepting Python source from an Agent. The platform still owns sandboxing,
limits, artifact validation, temporary storage, and download authorization.

A Skill directory has a required `SKILL.md`, the declared Python entrypoint,
and optional `references/`, `assets/`, and `requirements.txt` files.

## Built-in Skills

The repository ships three NexaFlow-authored bundles at
`sandbox/skills/documents`, `sandbox/skills/pdf`, and
`sandbox/skills/spreadsheets`. They are small project-specific guides and are
available to the Worker without a separate download. Each bundle owns its
renderer under `scripts/render.py` and is registered as a fixed Skill Tool, so
it appears in the Tools page, Agent Tool picker, and Workflow node palette.

- `documents_skill` accepts a DOCX filename and Markdown content.
- `pdf_skill` accepts a PDF filename and Markdown content.
- `spreadsheets_skill` accepts an XLSX filename and structured sheets/rows.

The Agent never supplies Python source to these Tools.

Workspace users can review the built-ins and manual installation flow at
`/app/tools/skills`.

## Create and install a Skill

1. Create a lowercase directory whose name matches `[a-z0-9][a-z0-9_-]{0,63}`.
2. Add a concise `SKILL.md` with YAML `name`, `description`, `entrypoint`, and
   `artifact-format` frontmatter.
3. Put the bundle under the directory configured by `SANDBOX_SKILLS_DIR`, or
   add it to the embedded `sandbox/skills` directory for a built-in bundle.
4. Register a matching Tool input contract in the platform catalog, then
   restart the Worker. Copying a directory alone does not add it to a picker.

For example, a manually managed bundle can look like this:

```text
$SANDBOX_SKILLS_DIR/invoice/
├── SKILL.md
├── scripts/
│   └── render.py
└── requirements.txt        # optional, one package spec per line
```

The executable contract is:

```yaml
---
name: invoice
description: Create a PDF invoice from structured invoice data.
entrypoint: scripts/render.py
artifact-format: pdf
---
```

The entrypoint reads one JSON object from standard input and writes exactly one
file to `NEXAFLOW_OUTPUT_PATH`. It should validate the input and reopen or parse
the result before exiting successfully. Keep bundles free of secrets; the
selected bundle is copied into a temporary run directory and exposed read-only.

`requirements.txt` is optional. It may contain package/version requirements,
one per line. NexaFlow installs those requirements into a temporary per-run
directory with pip, only from binary wheels, through the Worker-owned public
HTTP(S) egress proxy. The directory is removed after the run. Package URLs,
VCS/path requirements, pip options, source builds, and private destinations are
not accepted.

## Use a Skill

Authorize the required Skill Tools in an Agent or Workflow. During an Agent run,
the model sees the authorized Tool names, descriptions, and schemas and chooses
the matching Skill from that bounded set. Installing a Skill does not grant it
to every Agent.

For a fixed Skill invocation, the Worker stages only that bundle, installs its
optional dependencies, and runs its declared entrypoint. The request cannot
include caller-supplied code or stage additional Skills. The generic artifact
and inline Python runtimes remain internal compatibility components and are not
listed in the user-facing Tool catalog.

## Runtime boundaries

- `SANDBOX_NETWORK=public` permits only Worker-proxied public HTTP/HTTPS
  egress on ports 80 and 443; direct sockets and private/loopback/metadata
  destinations remain blocked.
- `SANDBOX_NETWORK=none` disables dependency downloads; a Skill with unmet
  requirements fails with `skill_network_unavailable`.
- Skill entrypoints cannot bypass the platform artifact size, process, CPU,
  memory, file, input, output, or wall-clock limits.
- Native Windows does not run the embedded POSIX sandbox; use WSL2.
