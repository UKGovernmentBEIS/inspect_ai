import inspect
from logging import getLogger
from typing import Any, Awaitable, Callable, TypeVar, cast

from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_add,
    registry_create,
    registry_info,
    registry_name,
    registry_tag,
)

from ._solver import Generate, Solver
from ._task_state import TaskState

logger = getLogger(__name__)


class Plan(Solver):
    """Task plan: List of solvers with an optional finishing solver.

    The optional `finish` solver is called after executing the steps (including in the case
    where the steps were exited early due to `TaskState.completed = True`, `message_limit`,
    or `token_limit`).

    The optional `cleanup` function is called when the plan is complete (even if the plan
    is terminated due to an exception).
    """

    def __init__(
        self,
        steps: Solver | list[Solver],
        finish: Solver | None = None,
        cleanup: Callable[[TaskState], Awaitable[None]] | None = None,
        name: str | None = None,
        internal: bool = False,
    ) -> None:
        """Create a task plan.

        Args:
          steps (list[Solver]): Solvers to run for this plan.
          finish (Solver | None): Finishing solver that is always run even for early exit.
            Note that this solver is NOT run when exception are thrown (use `cleanup` for this)
          cleanup (Callable[[TaskState], Awaitable[None]] | None): Optional cleanup handler that
            is called at the end (even if an exception occurs). Note that this function takes
            a `TaskState` but does not return one (it is only for cleanup not for transforming
            the state).
          name (str | None): Optional name for plan (for log files).
          internal (bool): Internal use of Plan (prevent deprecation warning)
        """
        if isinstance(steps, Solver):
            self.steps = [steps]
        else:
            self.steps = steps

        self.finish = finish
        self.cleanup = cleanup
        self.progress: Callable[[], None] = lambda: None
        self._name = name

        if not internal:
            from inspect_ai._util.logger import warn_once

            warn_once(
                logger,
                "Plan is deprecated: use chain() to compose a list of solvers.",
            )

    @property
    def name(self) -> str:
        if self._name is not None:
            return self._name
        elif is_registry_object(self):
            return registry_info(self).name
        else:
            return "plan"

    steps: list[Solver]
    """Solvers to run for this plan."""

    finish: Solver | None = None
    """Finishing solver that is always run even for early exit."""

    cleanup: Callable[[TaskState], Awaitable[None]] | None = None
    """Function  called at the end of the plan (even if an exception occurs).

    Note that this function takes a `TaskState` but does not return one
    (it is only for cleanup not for transforming the state). Note also that
    this function should be declared `async`.
    """

    async def __call__(
        self,
        state: TaskState,
        generate: Generate,
    ) -> TaskState:
        from ._transcript import solver_transcript

        try:
            # execute steps
            for index, solver in enumerate(self.steps):
                # run solver
                with solver_transcript(solver, state) as st:
                    state = await solver(state, generate)
                    st.complete(state)

                # tick progress
                self.progress()

                # check for completed
                if state.completed:
                    # tick rest of progress
                    for _ in range(index + 1, len(self.steps)):
                        self.progress()
                    # exit loop
                    break

            # execute finish
            if self.finish:
                with solver_transcript(self.finish, state) as st:
                    state = await self.finish(state, generate)
                    st.complete(state)
                self.progress()

            # mark completed
            state.completed = True

        finally:
            # always do cleanup if we have one
            if self.cleanup:
                try:
                    await self.cleanup(state)
                except Exception as ex:
                    logger.warning(f"Exception occurred during plan cleanup: {ex}")

        return state


PlanType = TypeVar("PlanType", bound=Callable[..., Plan])


def plan(*plan: PlanType | None, name: str | None = None, **attribs: Any) -> Any:
    r"""Decorator for registering plans.

    Args:
      *plan (PlanType): Function returning `Plan` targeted by
        plain plan decorator without attributes (e.g. `@plan`)
      name (str | None):
        Optional name for plan. If the decorator has no name
        argument then the name of the function
        will be used to automatically assign a name.
      **attribs: (dict[str,Any]): Additional plan attributes.

    Returns:
        Plan with registry attributes.
    """

    def create_plan_wrapper(plan_type: PlanType) -> PlanType:
        # get the name and params
        plan_name = registry_name(plan_type, name or getattr(plan_type, "__name__"))
        params = list(inspect.signature(plan_type).parameters.keys())

        # create and return the wrapper
        def wrapper(*w_args: Any, **w_kwargs: Any) -> Plan:
            # create the plan
            plan = plan_type(*w_args, **w_kwargs)

            # tag it
            registry_tag(
                plan_type,
                plan,
                RegistryInfo(
                    type="plan",
                    name=plan_name,
                    metadata=dict(attribs=attribs, params=params),
                ),
                *w_args,
                **w_kwargs,
            )

            # return it
            return plan

        return plan_register(
            plan=cast(PlanType, wrapper),
            name=plan_name,
            attribs=attribs,
            params=params,
        )

    from inspect_ai._util.logger import warn_once

    warn_once(
        logger,
        "@plan is deprecated: use @solver and chain() to compose a list of solvers.",
    )

    if plan:
        return create_plan_wrapper(cast(PlanType, plan[0]))
    else:
        return create_plan_wrapper


def plan_register(
    plan: PlanType, name: str, attribs: dict[str, Any], params: list[str]
) -> PlanType:
    r"""Register a plan.

    Args:
        plan (PlanType): function that returns a Plan
        name (str): Name of plan
        attribs (dict[str,Any]): Attributes of plan decorator
        params (list[str]): Plan parameter names

    Returns:
        Plan with registry attributes.
    """
    registry_add(
        plan,
        RegistryInfo(
            type="plan", name=name, metadata=dict(attribs=attribs, params=params)
        ),
    )
    return plan


def plan_create(name: str, **kwargs: Any) -> Plan:
    r"""Create a Plan based on its registered name.

    Args:
        name (str): Name of plan
        **kwargs (dict): Optional creation arguments for the plan

    Returns:
        Plan with registry info attribute
    """
    return cast(Plan, registry_create("plan", name, **kwargs))
