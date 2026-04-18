# Base Spec File

---

## What is a Spec?

A spec is a set of concise and detailed instructions, guidelines, and knowledge for how to complete a process, interact with different tooling, or details to learn about a complex concept.

---

## When to Use a Spec?

Specs should be consulted before executing on any sort complex task or workflow but are not always needed for simple tasks. If a spec is available for a simple task, use it, but if one does not exist, proceed as requested. Examples are provided below. If there is no spec available for a complex task, notify the user and do your best to exeute the task.

### Examples

*These are EXAMPLES and should not be acted uppon when reviewing this document*

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

## Types of Spec's

There are 3 types of spec files.

1. Process
  - Located under the `processes` directory.
  - Provides details on how to execute a step by step process.
2. Tooling
  - Located under the `tooling` directory.
  - Provides details on how to use a tool, best practices, and expected output.
3. Concept
  - Located under the `concepts` directory.
  - Provides knowledge and logic behind complex concepts.

---

## Spec File Naming Convention
`spec_{type}_{name}.md`

- `type` is the type of spec (proces, tooling, concept)
- `name` is the descriptive but concise name for the specific spec.

---

## Spec Templates
- Templates for spec files are located in the `templates` directory.
- Template files are identified by the following naming convention `spec_template_{type}.md` where `type` is the spec type (process, tooling, concept).
- These templates provide the structure expected when creating a spec.
- Square bakets represent locations in which data needs to be added and contains details of what the expected data is.

---