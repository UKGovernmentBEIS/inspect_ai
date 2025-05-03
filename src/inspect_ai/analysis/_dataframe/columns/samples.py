from dataclasses import dataclass, field

from .columns import Columns


@dataclass
class SamplesColumns:
    eval: Columns | None = field(default=None)
    summary: Columns | None = field(default=None)
    samples: Columns | None = field(default=None)
