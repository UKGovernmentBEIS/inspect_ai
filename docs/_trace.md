

```bash
$ inspect eval theory.py --trace
```

In trace mode, all messages exchanged with the model are printed to the terminal (tool output is truncated at 100 lines).

Note that trace mode can only be enabled when an evaluation has a single sample (otherwise messages from different chat conversations would be interleaved together in an incoherent jumble).

