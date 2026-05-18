from typing import Any

from inspect_ai.log._log import EvalLog

# EvalConfig fields that control logging, display, and parallelism — not the
# scientific conditions of the eval. Omitted from exported run configs so that
# users can apply their own operational preferences when re-running.
_OPERATIONAL_EVAL_CONFIG_FIELDS = {
    "log_samples",
    "log_realtime",
    "log_images",
    "log_model_api",
    "log_buffer",
    "log_shared",
    "score_display",
    "sandbox_cleanup",
    "max_samples",
    "max_dataset_memory",
    "max_tasks",
    "max_subprocesses",
    "max_sandboxes",
}


def eval_log_to_run_config_dict(log: EvalLog) -> dict[str, Any]:
    """Produce a --run-config compatible dict from an eval log.

    All resolved task and solver args are included (not just args_passed) so
    the exported config is self-contained even if defaults change in future.
    """
    spec = log.eval
    plan = log.plan
    out: dict[str, Any] = {}

    # Task
    task_name = spec.task_registry_name or spec.task
    task_ref = f"{spec.task_file}@{task_name}" if spec.task_file else task_name
    task_entry: dict[str, Any] = {"task": task_ref}
    if spec.task_args:
        task_entry["args"] = spec.task_args
    out["task"] = task_entry

    # Model
    model_entry: dict[str, Any] = {"model": spec.model}
    if spec.model_base_url:
        model_entry["base_url"] = spec.model_base_url
    if spec.model_args:
        model_entry["args"] = spec.model_args
    model_gc = spec.model_generate_config.model_dump(exclude_none=True)
    if model_gc:
        model_entry["config"] = model_gc
    out["model"] = model_entry

    # Model roles (dict[str, ModelConfig])
    if spec.model_roles:
        roles: dict[str, Any] = {}
        for name, mc in spec.model_roles.items():
            role_entry: dict[str, Any] = {"model": mc.model}
            if mc.base_url:
                role_entry["base_url"] = mc.base_url
            role_gc = mc.config.model_dump(exclude_none=True)
            if role_gc:
                role_entry["config"] = role_gc
            if mc.args:
                role_entry["args"] = mc.args
            roles[name] = role_entry
        out["model_roles"] = roles

    # Generate config (plan-level)
    if plan is not None:
        gc = plan.config.model_dump(exclude_none=True)
        if gc:
            out["generate_config"] = gc

    # Solver
    if spec.solver:
        solver_entry: dict[str, Any] = {"solver": spec.solver}
        if spec.solver_args:
            solver_entry["args"] = spec.solver_args
        out["solver"] = solver_entry

    # Eval config — drop operational fields (logging, display, parallelism)
    ec = {
        k: v
        for k, v in spec.config.model_dump(exclude_none=True).items()
        if k not in _OPERATIONAL_EVAL_CONFIG_FIELDS
    }
    if ec:
        out["eval_config"] = ec

    # Sandbox
    if spec.sandbox is not None:
        from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec

        if isinstance(spec.sandbox, SandboxEnvironmentSpec):
            cfg = spec.sandbox.config
            if isinstance(cfg, str) and cfg:
                out["sandbox"] = f"{spec.sandbox.type}:{cfg}"
            elif hasattr(cfg, "model_dump"):
                import sys

                print(
                    f"Warning: sandbox config is a Python object ({type(cfg).__name__}) "
                    "and cannot be fully exported. Only the sandbox type has been included — "
                    "you will need to supply the sandbox config manually when re-running.",
                    file=sys.stderr,
                )
                out["sandbox"] = spec.sandbox.type
            else:
                out["sandbox"] = spec.sandbox.type
        elif isinstance(spec.sandbox, str):
            out["sandbox"] = spec.sandbox

    # Tags and metadata
    if spec.tags:
        out["tags"] = spec.tags
    if spec.metadata:
        out["metadata"] = spec.metadata

    return out
