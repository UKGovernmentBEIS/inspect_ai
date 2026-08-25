class TerminateSampleError(RuntimeError):
    """Signal that the current sample should terminate without an error."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class TerminateTaskError(RuntimeError):
    """Signal that the current task evaluation should terminate."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
