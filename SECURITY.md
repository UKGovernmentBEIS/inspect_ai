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

When you evaluate an adversarial model, the sandbox is the security boundary. With `sandbox_agent_bridge()` the agent runs inside the sandbox and its model calls are passed to the host. By default it keeps the model API keys Inspect uses on the host and withholds web search, code execution and remote MCP servers. Inspect does not run the agent's own tools, so it records the agent's model calls but not what its tools did. The in-process `agent_bridge()` and `sandbox_service()` methods run code on the host. See [Adversarial Models](https://inspect.aisi.org.uk/agent-bridge.html#adversarial-models) for guidance.

### In scope

- Code execution or file access triggered by opening or reading an eval log, transcript, or dataset
- Escape from a Docker sandbox to the host, or from one sandbox to another
- An agent in a sandbox using the agent bridge to get a capability the evaluation did not grant, read API keys kept on the host, run code in the Inspect process, or reach another sample's model calls
- API keys, tokens, or other secrets written to logs, transcripts, or error messages
- Path traversal, unauthenticated access, or other flaws in the log viewer or its server
- Flaws in our release process, packaging, or CI that would let someone publish or modify a release

### Out of scope

- The `local` sandbox runs commands directly on your machine with no isolation. This is documented behavior and is not a vulnerability.
- Model-generated code running inside a sandbox is the purpose of the sandbox and is not a vulnerability.
- Capabilities you grant to an agent, such as agent bridge grants, writable host mounts, sandbox networking, or an ACP server on a TCP address the sandbox or other machines can reach.
- Credentials you put in a sandbox yourself, for example through an agent's environment. Code in the sandbox can read them.
- Tools you give to an in-process `agent_bridge()` agent, and methods you expose with `sandbox_service()`. These run on the host.
- Other processes in a sandbox calling that sandbox's agent bridge, when the bridge is set up to serve them. By default it serves every process in its sandbox. Where a bridge is limited to one sandbox user, another user calling it is in scope.
- A bridged agent misreporting its conversation history or tool results. Inspect does not run the agent's tools, so the transcript is the agent's own account.
- Root, or the user Inspect's tools run as, interfering with the agent bridge inside its own sandbox, when only that sandbox's sample is affected.
- Bypassing an agent's own permission prompts or sandboxing. Agents usually run with these turned off.
- Loading a task, solver, scorer, or config file from an untrusted source runs that code. Treat these files the same way you would treat any other Python you did not write.
- Docker provides limited isolation. If you run untrusted code, use a stronger sandbox such as gVisor. Weaknesses in Docker itself should be reported to Docker.
- An escape that depends on an unpatched Docker Engine, container runtime (such as runc) or host. Inspect's prerequisite checks do not check for security updates. Users are responsible for Docker and host security updates.
- Vulnerabilities in third-party dependencies should be reported to that project. Tell us if `inspect_ai` needs a change in response, such as a version pin.
- Reports produced by a scanner, or written mainly by an automated tool or a language model, with no working proof of concept. We will close these without a detailed response.

## Disclosure

We publish fixes as a GitHub security advisory on this repository and request a CVE where one applies. We will credit you by name unless you ask us not to.

Please keep the details private until the advisory is published.
