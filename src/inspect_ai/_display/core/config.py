from rich.console import RenderableType
from rich.text import Text

from inspect_ai._util.registry import is_model_dict, is_registry_dict
from inspect_ai._util.text import truncate_text
from inspect_ai.log._log import eval_config_defaults

from .display import TaskProfile


def task_config_str(profile: TaskProfile, generate_config: bool = True) -> str:
    # merge config
    # wind params back for display
    task_args = dict(profile.task_args)
    for key in task_args.keys():
        value = task_args[key]
        if is_registry_dict(value):
            task_args[key] = value["name"]
        if is_model_dict(value):
            task_args[key] = value["model"]
    # get eval_config overrides
    eval_config = dict(profile.eval_config.model_dump(exclude_none=True))
    for name, default_value in eval_config_defaults().items():
        if eval_config.get(name, None) == default_value:
            del eval_config[name]
    config = eval_config | task_args
    if generate_config:
        config = dict(profile.generate_config.model_dump(exclude_none=True)) | config
    if profile.tags:
        config["tags"] = ",".join(profile.tags)
    config["dataset"] = profile.dataset
    config_print: list[str] = []
    for name, value in config.items():
        if name == "approval" and isinstance(value, dict):
            config_print.append(
                f"{name}: {','.join([approver['name'] for approver in value['approvers']])}"
            )
        elif name == "sample_id":
            value = value if isinstance(value, list) else [value]
            value = [str(v) for v in value]
            config_print.append(f"{name}: {','.join(value)}")
        elif name not in ["limit", "model", "response_schema", "log_shared"]:
            if isinstance(value, list):
                value = ",".join([str(v) for v in value])
            elif isinstance(value, dict):
                value = "{...}"
            if isinstance(value, str):
                value = truncate_text(value, 50)
                value = value.replace("[", "\\[")
            config_print.append(f"{name}: {value}")
    values = ", ".join(config_print)
    return values


def task_config(
    profile: TaskProfile, generate_config: bool = True, style: str = ""
) -> RenderableType:
    values = task_config_str(profile, generate_config)
    if values:
        values_text = Text(values, style=style)
        values_text.truncate(500, overflow="ellipsis")
        return values_text
    else:
        return ""


def task_dict(d: dict[str, str], bold_value: bool = False) -> str:
    slot1, slot2 = ("", "[/bold]") if bold_value else ("[/bold]", "")
    return "  ".join(
        [f"[bold]{key}:{slot1} {value}{slot2}" for key, value in d.items()]
    )
