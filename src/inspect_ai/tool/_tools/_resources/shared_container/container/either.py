from oslash.either import Either, Left, Right  # type: ignore

# NOTE: we're using the `Either` type from `oslash`. That's not a particularly
# widely used package, but it's already indirectly used by `jsonrpcserver`. If
# we get rid of `jsonrpcserver`, we should switch over to 'returns.result'.

__all__ = ["Either", "Left", "Right"]
