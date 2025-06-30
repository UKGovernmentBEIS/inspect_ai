from inspect_ai.hooks import Hooks, RunStart


class CustomHooks(Hooks):
    @property
    def name(self) -> str:
        return "custom_hook"

    @property
    def description(self) -> str:
        return "A custom hook for testing purposes"

    async def on_run_start(self, event: RunStart) -> None:
        global run_ids
        run_ids.append(event.run_id)


run_ids: list[str] = []
