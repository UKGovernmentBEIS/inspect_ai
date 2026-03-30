# Learnings

## 2026-03-30 Initial Setup
- Inspect AI fork: METR/inspect_ai, branch: feat/remote-control
- Display protocol is in `src/inspect_ai/_display/core/display.py` — `Display`, `TaskDisplay`, `Progress` are Python Protocols
- Display factory in `src/inspect_ai/_display/core/active.py` — selects based on `display_type()`
- Valid display types defined in `src/inspect_ai/util/_display.py` as `DisplayType = Literal["full", "conversation", "rich", "plain", "log", "none"]`
- Hooks in `src/inspect_ai/hooks/_hooks.py` — `on_sample_start`, `on_sample_end`, `on_sample_scoring`, `on_model_usage`
- EarlyStopping in `src/inspect_ai/util/_early_stopping.py` — `schedule_sample()` returns `EarlyStop | None`
- New socket display files go under `src/inspect_ai/_display/socket/`
- PlainDisplay is the simplest existing display — good structural reference
