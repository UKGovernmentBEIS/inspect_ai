"""Events the tamper-evident logs tests use to order samples and hooks.

eval_retry loads the task from its file, which runs the test module again;
this module is imported once, so both copies share the gates.
"""

import threading

cancel_gates: dict[str, threading.Event] = {}
"""Set by the tests that stop an eval while a sample waits."""
