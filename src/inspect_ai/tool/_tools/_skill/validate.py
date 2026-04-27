"""Validation helpers for skills."""

from typing import Sequence

from .types import Skill


def check_unique_skill_names(skills: Sequence[Skill]) -> None:
    """Raise if any skill names are duplicated.

    Args:
        skills: Skill specifications to validate.

    Raises:
        ValueError: If two or more skills share the same name.
    """
    seen: set[str] = set()
    for sk in skills:
        if sk.name in seen:
            raise ValueError(
                f"Duplicate skill name '{sk.name}'. Each skill must have a unique name."
            )
        seen.add(sk.name)
