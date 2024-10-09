``` bash
$ inspect eval theory.py --trace
```

In trace mode, all messages exchanged with the model are printed to the terminal (tool output is truncated at 100 lines).

Note that enabling trace mode automatically sets `max_tasks` and `max_samples` to 1, as otherwise messages from concurrently running samples would be interleaved together in an incoherent jumble.

If you want to add your own trace content, use the `trace_enabled()` function to check whether trace mode is currently enabled and the `trace_panel()` function to output a panel that is visually consistent with other trace mode output. For example:

``` python
from inspect_ai.util import trace_enabled, trace_panel

if trace_enabled():
    trace_panel("My Panel", content="Panel content")
```