from inspect_ai._util.registry import is_registry_dict

from .display import TaskProfile


def task_config(
    profile: TaskProfile, generate_config: bool = True, style: str = ""
) -> str:
    # merge config
    # wind params back for display
    task_args = dict(profile.task_args)
    for key in task_args.keys():
        value = task_args[key]
        if is_registry_dict(value):
            task_args[key] = value["name"]
    config = task_args | dict(profile.eval_config.model_dump(exclude_none=True))
    if generate_config:
        config = config | dict(profile.generate_config.model_dump(exclude_none=True))
    if profile.tags:
        config["tags"] = ",".join(profile.tags)
    config_print: list[str] = []
    for name, value in config.items():
        if name == "approval":
            config_print.append(
                f"{name}: {','.join([approver['name'] for approver in value['approvers']])}"
            )
        elif name == "sample_id":
            value = value if isinstance(value, list) else [value]
            value = [str(v) for v in value]
            config_print.append(f"{name}: {','.join(value)}")
        elif name not in ["limit", "model"]:
            config_print.append(f"{name}: {value}")
    values = ", ".join(config_print)
    if values:
        if style:
            return f"[{style}]{values}[/{style}]"
        else:
            return values
    else:
        return ""


def task_dict(d: dict[str, str], bold_value: bool = False) -> str:
    slot1, slot2 = ("", "[/bold]") if bold_value else ("[/bold]", "")
    return "  ".join(
        [f"[bold]{key}:{slot1} {value}{slot2}" for key, value in d.items()]
    )
