# <Feature Name> Implementation Plan

> **For agentic workers:** Execute this plan task-by-task. A task that carries a `task-meta` block is verified and checkbox-ticked by `scripts/harness/run_task.py` — never tick those by hand. Tasks without a `task-meta` block are human-run. (Execution skills such as superpowers `subagent-driven-development` work well here but are optional.)

**Goal:** <one sentence>

**Architecture:** <2-3 sentences>

**Tech Stack:** <key tech>

---

## File Structure

**Create:** <paths>

**Modify:** <paths>

---

### Task 1 — <Component Name>

**Files:**
- Create: `<path>`
- Test: `<path>`

- [ ] **Step 1: Write the failing test**

```python
# test body
```

- [ ] **Step 2: Run test to verify it fails**

```bash
<exact command>
```

Expected: <expected output>

- [ ] **Step 3: Implement**

```python
# impl
```

- [ ] **Step 4: Run tests to verify pass**

```bash
<exact command>
```

- [ ] **Step 5: Commit**

```bash
git add <paths>
git commit -m "feat(<scope>): <message>"
```

<!-- task-meta
id: T01
touches:
  - <path>
depends: []
verify: <exact command that proves done>
acceptance: null
-->
