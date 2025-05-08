# inspect_ai.approval


## Approvers

### auto_approver

Automatically apply a decision to tool calls.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/approval/_auto.py#L9)

``` python
@approver(name="auto")
def auto_approver(decision: ApprovalDecision = "approve") -> Approver
```

`decision` [ApprovalDecision](inspect_ai.approval.qmd#approvaldecision)  
Decision to apply.

### human_approver

Interactive human approver.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/approval/_human/approver.py#L11)

``` python
@approver(name="human")
def human_approver(
    choices: list[ApprovalDecision] = ["approve", "reject", "terminate"],
) -> Approver
```

`choices` list\[[ApprovalDecision](inspect_ai.approval.qmd#approvaldecision)\]  
Choices to present to human.

## Types

### Approver

Approve or reject a tool call.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/approval/_approver.py#L12)

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

`history` list\[[ChatMessage](inspect_ai.model.qmd#chatmessage)\]  
The current conversation history.

### Approval

Approval details (decision, explanation, etc.)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/approval/_approval.py#L19)

``` python
class Approval(BaseModel)
```

#### Attributes

`decision` [ApprovalDecision](inspect_ai.approval.qmd#approvaldecision)  
Approval decision.

`modified` ToolCall \| None  
Modified tool call for decision ‘modify’.

`explanation` str \| None  
Explanation for decision.

### ApprovalDecision

Represents the possible decisions in an approval.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/approval/_approval.py#L7)

``` python
ApprovalDecision = Literal["approve", "modify", "reject", "terminate", "escalate"]
```

### ApprovalPolicy

Policy mapping approvers to tools.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/approval/_policy.py#L21)

``` python
@dataclass
class ApprovalPolicy
```

#### Attributes

`approver` [Approver](inspect_ai.approval.qmd#approver)  
Approver for policy.

`tools` str \| list\[str\]  
Tools to use this approver for (can be full tool names or globs).

## Decorator

### approver

Decorator for registering approvers.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/5044b7730b357516973690a752dfbc3d8b575b8f/src/inspect_ai/approval/_registry.py#L28)

``` python
def approver(*args: Any, name: str | None = None, **attribs: Any) -> Any
```

`*args` Any  
Function returning `Approver` targeted by plain approver decorator
without attributes (e.g. `@approver`)

`name` str \| None  
Optional name for approver. If the decorator has no name argument then
the name of the function will be used to automatically assign a name.

`**attribs` Any  
Additional approver attributes.
