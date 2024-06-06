from typing import Sequence, Union, overload


class Target(Sequence[str]):
    """Target for scoring against the current TaskState.

    Target is a sequence of one or more strings. Use the
    `text` property to access the value as a single string.
    """

    def __init__(self, target: str | list[str]) -> None:
        self.target = target if isinstance(target, list) else [target]

    @overload
    def __getitem__(self, index: int) -> str: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[str]: ...

    def __getitem__(self, index: Union[int, slice]) -> Union[str, Sequence[str]]:
        return self.target[index]

    def __len__(self) -> int:
        return len(self.target)

    @property
    def text(self) -> str:
        return "".join(self.target)
