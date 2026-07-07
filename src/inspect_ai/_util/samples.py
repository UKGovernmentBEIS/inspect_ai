def parse_samples_limit(limit: str | None) -> int | tuple[int, int] | None:
    if limit is not None:
        if "-" not in limit:
            return int(limit)
        else:
            limit_split = [int(r) for r in limit.split("-")]
            if len(limit_split) != 2:
                raise ValueError(
                    f"Invalid sample limit '{limit}': expected a single number "
                    "or a range like '10-20'."
                )
            return (limit_split[0] - 1, limit_split[1])
    else:
        return None


def parse_sample_id(sample_id: str | None) -> list[str] | None:
    if sample_id is not None:
        return [id.strip() for id in sample_id.split(",")]
    else:
        return None
