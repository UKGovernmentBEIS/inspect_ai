# inspect_ai.approval – Inspect

## Approvers

### auto_approver

Automatically apply a decision to tool calls.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0250d6d10e06b35c1da2c7bb963b712a557b22c0/src/inspect_ai/approval/_auto.py#L9)

``` python
@approver(name="auto")
def auto_approver(decision: ApprovalDecision = "approve") -> Approver
```

`decision` [ApprovalDecision](../reference/inspect_ai.approval.html.md#approvaldecision)  
Decision to apply.

### human_approver

Interactive human approver.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0250d6d10e06b35c1da2c7bb963b712a557b22c0/src/inspect_ai/approval/_human/approver.py#L11)

``` python
@approver(name="human")
def human_approver(
    choices: list[ApprovalDecision] = ["approve", "reject", "terminate"],
) -> Approver
```

`choices` list\[[ApprovalDecision](../reference/inspect_ai.approval.html.md#approvaldecision)\]  
Choices to present to human.

### read_approval_policies

Read approval policies from a JSON or YAML config file.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0250d6d10e06b35c1da2c7bb963b712a557b22c0/src/inspect_ai/approval/_policy.py#L135)

``` python
def read_approval_policies(file: str) -> list[ApprovalPolicy]
```

`file` str  
JSON or YAML config file with approval policies.

### approval

Context manager to temporarily replace tool approval policies.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0250d6d10e06b35c1da2c7bb963b712a557b22c0/src/inspect_ai/approval/_apply.py#L70)

``` python
@contextlib.contextmanager
def approval(
    policies: list[ApprovalPolicy],
) -> Iterator[None]
```

`policies` list\[[ApprovalPolicy](../reference/inspect_ai.approval.html.md#approvalpolicy)\]  
Approval policies to use within the context.

## Types

### Approver

Approve or reject a tool call.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0250d6d10e06b35c1da2c7bb963b712a557b22c0/src/inspect_ai/approval/_approver.py#L12)

``` python
class Approver(Protocol):
    async def __call__(
        self,
        message: str,
        call: ToolCall,
        view: ToolCallView,
        history: list[ChatMessage],
    ) -> Approval
```

`message` str  
Message genreated by the model along with the tool call.

`call` ToolCall  
The tool call to be approved.

`view` ToolCallView  
Custom rendering of tool context and call.

`history` list\[[ChatMessage](../reference/inspect_ai.model.html.md#chatmessage)\]  
The current conversation history.

### Approval

Approval details (decision, explanation, etc.)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0250d6d10e06b35c1da2c7bb963b712a557b22c0/src/inspect_ai/approval/_approval.py#L19)

``` python
class Approval(BaseModel)
```

#### Attributes

`decision` [ApprovalDecision](../reference/inspect_ai.approval.html.md#approvaldecision)  
Approval decision.

`modified` ToolCall \| None  
Modified tool call for decision ‘modify’.

`explanation` str \| None  
Explanation for decision.

`metadata` dict\[str, Any\] \| None  
Additional approval metadata.

### ApprovalDecision

Represents the possible decisions in an approval.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0250d6d10e06b35c1da2c7bb963b712a557b22c0/src/inspect_ai/approval/_approval.py#L7)

``` python
ApprovalDecision = Literal["approve", "modify", "reject", "terminate", "escalate"]
```

### ApprovalPolicy

Policy mapping approvers to tools.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0250d6d10e06b35c1da2c7bb963b712a557b22c0/src/inspect_ai/approval/_policy.py#L21)

``` python
@dataclass
class ApprovalPolicy
```

#### Attributes

`approver` [Approver](../reference/inspect_ai.approval.html.md#approver)  
Approver for policy.

`tools` str \| list\[str\]  
Tools to use this approver for (can be full tool names or globs).

## Decorator

### approver

Decorator for registering approvers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/0250d6d10e06b35c1da2c7bb963b712a557b22c0/src/inspect_ai/approval/_registry.py#L28)

``` python
def approver(*args: Any, name: str | None = None, **attribs: Any) -> Any
```

`*args` Any  
Function returning [Approver](../reference/inspect_ai.approval.html.md#approver) targeted by plain approver decorator without attributes (e.g. `@approver`)

`name` str \| None  
Optional name for approver. If the decorator has no name argument then the name of the function will be used to automatically assign a name.

`**attribs` Any  
Additional approver attributes.
