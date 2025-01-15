import threading


def is_main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()
