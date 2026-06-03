# Approvers – Inspect

## Overview

[Approvers](./approval.html.md) enable you to create fine-grained policies for approving tool calls made by models. For example, the following are all supported:

1.  All tool calls are approved by a human operator.
2.  Select tool calls are approved by a human operator (the rest being executed without approval).
3.  Custom approvers that decide to either approve, reject, or escalate to another approver.

Approvers can be implemented in Python packages and the referred to by package and name from approval policy config files. For example, here is a simple custom approver that just reflects back a decision passed to it at creation time:

    approvers.py

``` python
@approver
def auto_approver(decision: ApprovalDecision = "approve") -> Approver:

    async def approve(
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval:
        return Approval(
            decision=decision,
            explanation="Automatic decision."
        )

    return approve
```

## Approver Registration

If you are publishing an approver within a Python package, you should register an `inspect_ai` [setuptools entry point](https://setuptools.pypa.io/en/latest/userguide/entry_point.html). This will ensure that inspect loads your extension before it attempts to resolve approvers by name.

For example, let’s say your package is named `evaltools` and has this structure:

    evaltools/
      approvers.py
      _registry.py
    pyproject.toml

The `_registry.py` file serves as a place to import things that you want registered with Inspect. For example:

    _registry.py

``` python
from .approvers import auto_approver
```

You can then register your `auto_approver` Inspect extension (and anything else imported into `_registry.py`) like this in `pyproject.toml`:

``` toml
[project.entry-points.inspect_ai]
evaltools = "evaltools._registry"
```

``` toml
[project.entry-points.inspect_ai]
evaltools = "evaltools._registry"
```

``` toml
[tool.poetry.plugins.inspect_ai]
evaltools = "evaltools._registry"
```

Once you’ve done this, you can refer to the approver within an approval policy config using its package qualified name. For example:

    approval.yaml

``` yaml
approvers:
  - name: evaltools/auto_approver
    tools: "harmless*"
    decision: approve
```
