# Base Spec File

---

## What is a Spec?

A spec is a set of concise and detailed instructions, guidelines, and knowledge for how to complete a process, interact with different tooling, or details to learn about a complex concept.

---

## When to Use a Spec?

Specs should be consulted before executing on any sort complex task or workflow but are not always needed for simple tasks. If a spec is available for a simple task, use it, but if one does not exist, proceed as requested. Examples are provided below. If there is no spec available for a complex task, notify the user and do your best to execute the task.

### Examples

*These are EXAMPLES and should not be acted upon when reviewing this document*

#### When to use a spec.

**1.**

```
Assess the security of application XYZ. Identify potential threats, review the code for security flaws, and validate the identified flaws and business logic with manual testing. Generate a report based on the findings and recommendations for remediation. 
```

**2.**

```
Based on the results from the Purple Team Engagement, create detection rules to alert on the identified activities. In addition to the rule creation, create tooling for the Detection & Incident Response team to continually validate the rules are working as expected.
```

#### When NOT to use a spec.

**1.**

```
What is todays date?
```

**2.**

```
What is my username?
```

**3.**
```
Explain what a vulnerability is.
```

---

## Types of Specs

There are 3 types of spec files.

1. **Process**
   - Directory: `processes`
   - Filename prefix: `spec_process_`
   - Provides details on how to execute a step-by-step process.
2. **Tooling**
   - Directory: `tooling`
   - Filename prefix: `spec_tooling_`
   - Provides details on how to use a tool, best practices, and expected output.
3. **Concept**
   - Directory: `concepts`
   - Filename prefix: `spec_concept_`
   - Provides knowledge and logic behind complex concepts.

---

## Spec File Naming Convention

`spec_{type}_{name}.md`

- `type` is one of: `process`, `tooling`, `concept`
- `name` is a descriptive but concise slug for the specific spec (e.g. `spec_process_purple_team_engagement.md`)

Specs are stored only under their type directory (`processes/`, `tooling/`, or `concepts/`). Do not create specs at the repo root or under `templates/`.

---

## Spec Templates

Templates live in the dedicated `templates/` directory. They are scaffolding for new specs, not runnable specs themselves.

| Type | Template file |
|------|----------------|
| process | `templates/spec_template_process.md` |
| tooling | `templates/spec_template_tooling.md` |
| concept | `templates/spec_template_concept.md` |

- Square brackets mark placeholders and describe the expected content.
- Before `create_spec`, call `get_spec_template` (or `get_spec` with the template path) and replace placeholders with real content.
- Templates are read-only via the spec tools; do not use `update_spec` or `delete_spec` on them.

---

## Managing Specs (Agent Tools)

Use these tools to discover and maintain specs. Prefer partial updates to keep token usage low.

### `list_specs`

- **Optional `spec_type`**: Filter to `process`, `tooling`, or `concept` (or the directory name: `processes`, `tooling`, `concepts`).
- **Optional `search`**: Case-insensitive substring match on filenames or paths.
- Returns paths like `processes/spec_process_example.md` (specs only, not templates).

### `list_spec_templates`

- **Optional `spec_type`**: Filter to one template (`process`, `tooling`, or `concept`).
- **Optional `search`**: Case-insensitive substring match on filenames or paths.
- Returns paths like `templates/spec_template_process.md`.

### `get_spec_template`

- **Required `spec_type`**: `process`, `tooling`, or `concept`.
- Returns the full markdown template for that type. Use this when drafting a new spec.

### `get_spec`

- Pass a filename (with or without `.md`) or a relative path from the specs root.
- Works for specs (`processes/...`) and templates (`templates/spec_template_process.md`).
- Read a spec before updating it.

### `create_spec`

- **Required `spec_type`**: `process`, `tooling`, or `concept` — the file is created in the matching directory.
- **Required `name`**: Slug or full basename; the correct `spec_{type}_` prefix is applied if missing.
- **Required `content`**: Full markdown for the new file. Start from `get_spec_template` for the same type.
- Creation fails if the file already exists or the type is invalid.

### `update_spec`

Prefer **partial updates** over full rewrites:

1. Call `get_spec` to load the current text.
2. Call `update_spec` with `old_string` (exact snippet to change) and `new_string` (replacement).
3. If `old_string` appears more than once, either narrow the snippet or set `replace_all=true`.

Use the `content` argument only when replacing the entire file is truly necessary.

### `delete_spec`

- Pass the same name or relative path as `get_spec`.

---
