# Security Policy

## Reporting a vulnerability

Email **security@meridianlabs.ai**. The address is monitored by Meridian Research Labs, which maintains Inspect. Please do not open a public issue, discussion, or pull request for a suspected vulnerability.

Include as much of the following as you can:

- The version of `inspect_ai` you tested, your Python version and operating system
- A description of the problem and what an attacker could do with it
- Steps to reproduce it, ideally a small script or task file
- Any logs, stack traces, or output that help show the behavior

## What to expect

- We will acknowledge your email within 3 business days.
- We will tell you within 10 business days whether we consider it a vulnerability and what we plan to do.
- We aim to release a fix within 30 days of the report. If a fix will take longer, we will tell you why.

We will keep you updated as we work on a fix, and we will let you know before we publish anything.

We do not run a bug bounty program and cannot pay for reports.

## Supported versions

We only fix security issues in the most recent release of `inspect_ai` on PyPI. We do not backport fixes to older versions. If you are running an older version, upgrade before reporting.

## Scope

Inspect runs evaluations that execute model-generated code, and tasks, solvers, and scorers are Python programs. Running an untrusted task or an untrusted model is equivalent to running untrusted code. Much of what Inspect does by design looks unsafe in isolation, so the sections below describe what we treat as a vulnerability and what we do not.

### In scope

- Code execution or file access triggered by opening or reading an eval log, transcript, or dataset
- Escape from a Docker sandbox to the host, or from one sandbox to another
- API keys, tokens, or other secrets written to logs, transcripts, or error messages
- Path traversal, unauthenticated access, or other flaws in the log viewer or its server
- Flaws in our release process, packaging, or CI that would let someone publish or modify a release

### Out of scope

- The `local` sandbox runs commands directly on your machine with no isolation. This is documented behavior and is not a vulnerability.
- Model-generated code running inside a sandbox is the purpose of the sandbox and is not a vulnerability.
- Loading a task, solver, scorer, or config file from an untrusted source runs that code. Treat these files the same way you would treat any other Python you did not write.
- Docker provides limited isolation. If you run untrusted code, use a stronger sandbox such as gVisor. Weaknesses in Docker itself should be reported to Docker.
- Vulnerabilities in third-party dependencies should be reported to that project. Tell us if `inspect_ai` needs a change in response, such as a version pin.
- Reports produced by a scanner, or written mainly by an automated tool or a language model, with no working proof of concept. We will close these without a detailed response.

## Disclosure

We publish fixes as a GitHub security advisory on this repository and request a CVE where one applies. We will credit you by name unless you ask us not to.

Please keep the details private until the advisory is published.
