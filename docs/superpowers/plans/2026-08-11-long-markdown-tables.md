# Long Markdown Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Markdown tables valid when flat or hierarchical knowledge chunks exceed their configured size.

**Architecture:** Extend the embedding splitter with a line-aware Markdown table detector. A table is emitted as header/alignment plus whole data rows; continuation chunks repeat only the two header lines and do not apply normal overlap. Synthetic continuation content carries its original source slice so hierarchical offsets remain verifiable without changing database schema.

**Tech Stack:** Python 3.11, FastAPI backend conventions, dataclasses, pure unit tests run with `uv`.

---

### Task 1: Add regression tests for table chunking

**Files:**
- Modify: `backend/tests/unit.py`

- [ ] **Step 1: Write failing tests**

Add pure tests that import `split_text`, `split_parent_chunks`, and `build_hierarchical_chunks` and assert: small tables stay intact; oversized tables start every continuation with the original header and alignment row; an oversized data row remains whole; custom separators do not change table handling; and hierarchical child slices remain valid against their parent source ranges.

- [ ] **Step 2: Run the focused unit suite**

Run `uv run python -m tests.unit` from `backend/`. The new assertions must fail against the current character-based splitter because continuation chunks begin with bare data rows and long rows are cut.

### Task 2: Implement table-aware spans

**Files:**
- Modify: `backend/app/capabilities/embedding/pipeline.py`

- [ ] **Step 1: Add table parsing and row-budget helpers**

Detect a header immediately followed by a Markdown alignment row and contiguous pipe-prefixed lines, while ignoring fenced code. Split only between complete data rows, repeat the header/alignment prefix on continuation chunks, allow a single over-budget row, and return source offsets for the original rows.

- [ ] **Step 2: Integrate tables into `split_text_spans`**

Constrain ordinary text spans at table boundaries, route table starts through the row splitter, and avoid applying ordinary overlap across table continuation chunks. Keep existing separator fallback behavior for non-table text.

- [ ] **Step 3: Preserve hierarchical offset validation**

Carry the original source slice for synthetic table spans in `ChildChunkDraft` and validate that slice against the parent content during replacement; retain existing offsets and validation for ordinary spans.

### Task 3: Verify and broaden checks

**Files:**
- No additional files.

- [ ] **Step 1: Run pure unit tests and compile touched packages**

Run `uv run python -m tests.unit` and `uv run python -m compileall app/capabilities/embedding app/shareddomain/knowledge` from `backend/`.

- [ ] **Step 2: Run the knowledge regression suite**

Run `uv run python -m tests.knowledge` from `backend/`; report any environment-dependent failures separately.

- [ ] **Step 3: Review the diff**

Confirm only the pipeline, unit regression tests, and this plan changed, and that ordinary text behavior remains covered by existing tests.
