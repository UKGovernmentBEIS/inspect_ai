import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field, computed_field


def trim_long_string(string, threshold=5100, k=2500):
    # Check if the length of the string is longer than the threshold
    if len(string) > threshold:
        # Output the first k and last k characters
        first_k_chars = string[:k]
        last_k_chars = string[-k:]

        truncated_len = len(string) - 2 * k

        return f"{first_k_chars}\n ... [{truncated_len} characters truncated] ... \n{last_k_chars}"
    else:
        return string


class ExecutionInfo(BaseModel):
    stdout: str | None
    stderr: str | None
    return_code: int | None
    exec_time: float
    exc_type: str | None = None
    exc_info: dict | None = None
    exc_stack: list[tuple] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def term_out(self) -> str:
        # return trim_long_string(f"STDOUT:\n\n{self.stdout}\n\nSTDERR:\\nn{self.stderr}")
        return f"STDOUT:\n\n{trim_long_string(self.stdout)}\n\nSTDERR:\n{trim_long_string(self.stderr)}"


class MetricValue(BaseModel):
    value: float | int | None
    maximize: bool | None

    def is_better(self, other: "MetricValue") -> bool:
        if self.value is None:
            return False
        if other.value is None:
            return True
        assert type(self) is type(other) and (self.maximize == other.maximize)
        if self.value == other.value:
            return False
        comp = self.value > other.value
        return comp if self.maximize else not comp


class Node(BaseModel):
    code: str
    plan: str
    step: int
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    ctime: float = Field(default_factory=lambda: time.time())
    parent: "Node | None" = None
    execution_info: ExecutionInfo | None = None
    analysis: str | None = None
    metric: MetricValue | None = None
    is_buggy: bool | None = None

    def model_post_init(self, __context):
        self._children = set()
        if self.parent is not None:
            self.parent.children.add(self)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stage_name(self) -> Literal["draft", "debug", "improve"]:
        if self.parent is None:
            return "draft"
        return "debug" if self.parent.is_buggy else "improve"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_leaf(self) -> bool:
        return not self.children

    @computed_field  # type: ignore[prop-decorator]
    @property
    def debug_depth(self) -> int:
        if self.stage_name != "debug":
            return 0
        return self.parent.debug_depth + 1 if self.parent else 1

    @property
    def children(self) -> set["Node"]:
        return self._children

    def __hash__(self):
        return hash(self.id)


class Journal(BaseModel):
    nodes: list[Node] = Field(default_factory=list)

    def __getitem__(self, idx: int) -> Node:
        return self.nodes[idx]

    def __len__(self) -> int:
        return len(self.nodes)

    def append(self, node: Node):
        node.step = len(self)
        self.nodes.append(node)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def draft_nodes(self) -> list[Node]:
        return [node for node in self.nodes if node.stage_name == "draft"]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def buggy_nodes(self) -> list[Node]:
        return [node for node in self.nodes if node.is_buggy]

    @computed_field
    @property
    def good_nodes(self) -> list[Node]:
        return [node for node in self.nodes if not node.is_buggy]

    def get_best_node(self, only_good: bool = True) -> None | Node:
        nodes = self.good_nodes if only_good else self.nodes
        if not nodes:
            return None

        def key(node: Node):
            if node.metric is None:
                return -float("inf")
            if node.metric.value is None:
                return -float("inf")
            return node.metric.value if node.metric.maximize else -node.metric.value

        return max(
            nodes,
            key=key,
        )

    def generate_summary(self, include_code: bool = False) -> str:
        summary = []
        for node in self.good_nodes:
            summary_part = f"Design: {node.plan}\n"
            if include_code:
                summary_part += f"Code: {node.code}\n"
            summary_part += f"Results: {node.analysis}\n"
            summary_part += f"Validation Metric: {node.metric}\n"
            summary.append(summary_part)
        return "\n-------------------------------\n".join(summary)
