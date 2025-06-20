from inspect_ai.util._lifecycle import EvalStartEvent, LifecycleHooks


class CustomLifecycleHook(LifecycleHooks):
    async def on_run_start(self, event: EvalStartEvent) -> None:
        global run_ids
        run_ids.append(event.run_id)


run_ids: list[str] = []
