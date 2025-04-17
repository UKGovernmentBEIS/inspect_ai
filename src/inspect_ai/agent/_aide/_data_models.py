from pathlib import Path

import yaml
from pydantic import BaseModel, Field, computed_field
from shortuuid import uuid

import inspect_ai.agent._aide._prompts as prompts
from inspect_ai.agent import AgentState
from inspect_ai.agent._aide._journal import (
    Journal,
    Node,
)
from inspect_ai.agent._aide._utils import (
    compile_prompt_to_md,
)
from inspect_ai.util import StoreModel


class PromptConfig(BaseModel):
    response_format_prompt: str = prompts.DEFAULT_RESPONSE_FORMAT_PROMPT
    implementation_guideline_prompt: str = (
        prompts.DEFAULT_IMPLEMENTATION_GUIDELINE_PROMPT
    )
    draft_introduction_prompt: str = prompts.DEFAULT_DRAFT_INTRODUCTION_PROMPT
    solution_sketch_guideline_prompt: str = (
        prompts.DEFAULT_SOLUTION_SKETCH_GUIDELINE_PROMPT
    )
    available_packages: list[str] = prompts.DEFAULT_AVAILABLE_PACKAGES
    available_packages_prompt: str = prompts.DEFAULT_AVAILABLE_PACKAGES_PROMPT
    improvement_introduction_prompt: str = prompts.DEFAULT_IMPROVE_INTRODUCTION_PROMPT
    solution_improvement_sketch_guideline_prompt: str = (
        prompts.DEFAULT_SOLUTION_IMPROVEMENT_SKETCH_GUIDELINE_PROMPT
    )
    debug_introduction_prompt: str = prompts.DEFAULT_DEBUG_INTRODUCTION_PROMPT
    bugfix_improvement_sketch_guideline_prompt: str = (
        prompts.DEFAULT_BUGFIX_IMPROVEMENT_SKETCH_GUIDELINE_PROMPT
    )
    execution_result_introduction_prompt: str = (
        prompts.DEFAULT_EXECUTION_RESULT_INTRODUCTION_PROMPT
    )
    submit_review_tool_description: str = prompts.DEFAULT_SUBMIT_REVIEW_TOOL_DESCRIPTION
    final_answer_introduction_prompt: str = (
        prompts.DEFAULT_FINAL_ANSWER_INTRODUCTION_PROMPT
    )

    def model_post_init(self, __context):
        # implementation_guideline_prompt should contain `timeout` argument
        try:
            self.implementation_guideline_prompt.format(timeout=10)
        except KeyError:
            raise ValueError(
                "implementation_guideline_prompt must contain a `timeout` argument"
            )

        # available_packages_prompt should contain `packages` argument
        try:
            self.available_packages_prompt.format(packages="test")
        except KeyError:
            raise ValueError(
                "available_packages_prompt must contain a `packages` argument"
            )

    @classmethod
    def from_yaml(self, path: Path) -> "PromptConfig":
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return PromptConfig(**data)

    def save_to_yaml(self, path: Path):
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f)


class AideConfig(BaseModel):
    goal: str | None = Field(
        default=None,
        description="The goal of the agent. Can be provided along with `evaluation_metric` to evaluate the agent's performance. Both of these values will be used to build the task description. If running via an inspect solver, this value will be overridden by `sample.input`.",
    )

    evaluation_metric: str | None = Field(
        default=None,
        description="The evaluation metric for the agent. Can be provided along with `goal` to evaluate the agent's performance. Both of these values will be used to build the task description. If running via an inspect solver, this value will be overridden by `sample.input`.",
    )

    task_description: str | None = Field(
        default=None,
        description="The task description for the agent. Can be provided directly, or if left empty, will be generated from `goal` and `evaluation_metric`. If running via an inspect solver, this value will be overridden by `sample.input`.",
    )

    data_dir: Path | None = Field(
        default=None,
        description="A local data directory to copy files from to the agent workspace. This will be copied to the workspace directory.",
    )

    num_drafts: int = Field(
        default=1,
        description="The number of drafts to generate before improving nodes.",
    )

    debug_prob: float = Field(
        default=0.5,
        description="The probability of debugging a node instead of drafting a new one at each step.",
    )

    agent_steps: int = Field(
        default=10,
        description="The number of steps the agent should run for.",
        ge=1,
    )

    exec_timeout: int = Field(
        default=600,
        description="The maximum time in seconds that the agent should allow for code execution.",
        ge=1,
    )

    # prompt_config: PromptConfig = PromptConfig()
    prompt_config: PromptConfig = Field(
        default_factory=PromptConfig,
        description="The configuration for the prompts used by the agent.",
    )

    exp_name: str | None = Field(
        default_factory=lambda: uuid(),
        description="The name of the experiment. If not provided, a random name will be generated.",
    )

    workspace_dir: Path = Field(
        default=Path("/app/workspaces/workspace"),
        description="The directory where the agent will execute code. Defaults to /app/workspaces/workspace.",
    )

    preproc_data: bool = Field(
        default=True,
        description="Whether to preprocess the data in the data_dir before copying it to the workspace.",
    )

    @computed_field
    @property
    def log_dir(self) -> Path:
        top_log_dir = Path("aide_logs")
        exp_name = self.exp_name or uuid()
        return (top_log_dir / exp_name).resolve()

    @computed_field
    @property
    def log_cmd(self) -> str:
        return f"python3 -m http.server 8000 --directory {self.log_dir}"

    def model_post_init(self, __context):
        if self.task_description is None and self.goal is not None:
            td = {"Task goal": self.goal}
            if self.evaluation_metric:
                td["Task evaluation metric"] = self.evaluation_metric
            self.task_description = compile_prompt_to_md(td)


class AideState(StoreModel):
    journal: Journal = Field(default_factory=Journal)
    config: AideConfig = Field(default_factory=AideConfig)
    data_preview: str = Field(default_factory=str)
    task_description: str = Field(default_factory=str)
    inspect_agent_state: AgentState | None = Field(default=None)
    instance: str | None = Field(default=None)
    best_node: Node | None = Field(default=None)

    class Config:
        arbitrary_types_allowed = True
