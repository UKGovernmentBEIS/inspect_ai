# import asyncio

# import pytest

# from inspect_ai.util._limit import LimitExceededError, MessageLimit, check_message_limit


# def test_can_check_message_limit_with_no_active_limits() -> None:
#     check_message_limit(0, False)


# def test_validates_limit_parameter() -> None:
#     with pytest.raises(ValueError):
#         MessageLimit(-1)


# def test_can_create_with_none_limit() -> None:
#     with MessageLimit(None):
#         check_message_limit(0, False)


# def test_can_create_with_zero_limit() -> None:
#     with MessageLimit(0):
#         pass


# def test_does_not_raise_error_when_limit_not_exceeded() -> None:
#     with MessageLimit(10):
#         check_message_limit(10, False)


# def test_raises_error_when_limit_exceeded() -> None:
#     with MessageLimit(10):
#         with pytest.raises(LimitExceededError) as exc_info:
#             check_message_limit(11, False)

#     assert exc_info.value.type == "message"
#     assert exc_info.value.value == 11
#     assert exc_info.value.limit == 10


# def test_raises_error_when_limit_repeatedly_exceeded() -> None:
#     with MessageLimit(10):
#         with pytest.raises(LimitExceededError):
#             check_message_limit(11, False)
#         with pytest.raises(LimitExceededError) as exc_info:
#             check_message_limit(12, False)

#     assert exc_info.value.type == "message"
#     assert exc_info.value.value == 12
#     assert exc_info.value.limit == 10


# def test_stack_can_trigger_outer_limit() -> None:
#     with MessageLimit(5):
#         with MessageLimit(10):
#             with pytest.raises(LimitExceededError) as exc_info:
#                 # Should trigger outer limit (5).
#                 check_message_limit(6, False)

#     assert exc_info.value.limit == 5


# def test_stack_can_trigger_inner_limit() -> None:
#     with MessageLimit(10):
#         with MessageLimit(5):
#             with pytest.raises(LimitExceededError) as exc_info:
#                 # Should trigger inner limit (5).
#                 check_message_limit(6, False)

#     assert exc_info.value.limit == 5


# def test_out_of_scope_limits_are_not_checked() -> None:
#     with MessageLimit(10):
#         check_message_limit(5, False)

#     check_message_limit(100, False)


# def test_outer_limit_is_checked_after_inner_limit_popped() -> None:
#     with MessageLimit(10):
#         check_message_limit(5, False)

#         with MessageLimit(5):
#             check_message_limit(5, False)

#         with pytest.raises(LimitExceededError) as exc_info:
#             # Should trigger outer limit (10).
#             check_message_limit(11, False)

#     assert exc_info.value.limit == 10
#     assert exc_info.value.value == 11


# def test_can_reuse_context_manager() -> None:
#     limit = MessageLimit(10)

#     with limit:
#         check_message_limit(5, False)

#     with limit:
#         check_message_limit(5, False)

#     with limit:
#         with pytest.raises(LimitExceededError):
#             check_message_limit(11, False)

#     with limit:
#         check_message_limit(5, False)


# def test_can_reuse_context_manager_in_stack() -> None:
#     limit = MessageLimit(10)

#     with limit:
#         check_message_limit(10, False)

#         with limit:
#             with pytest.raises(LimitExceededError) as exc_info:
#                 check_message_limit(11, False)

#     assert exc_info.value.value == 11


# async def test_same_context_manager_across_async_contexts():
#     async def async_task(limit: MessageLimit):
#         with limit:
#             # Incrementally use 10 tokens (should not exceed the limit).
#             for i in range(10):
#                 check_message_limit(i, False)
#                 # Yield to the event loop to allow other coroutines to run.
#                 await asyncio.sleep(0)
#             with pytest.raises(LimitExceededError) as exc_info:
#                 check_message_limit(11, False)
#                 assert exc_info.value.value == 11

#     # The same MessageLimit instance is reused across different async contexts.
#     reused_context_manager = MessageLimit(10)
#     # This will result in 3 distinct "trees" each with 1 root node.
#     await asyncio.gather(*(async_task(reused_context_manager) for _ in range(3)))


# def test_can_update_limit_value() -> None:
#     limit = MessageLimit(10)

#     with limit:
#         limit.limit = 20
#         check_message_limit(15, False)

#         with pytest.raises(LimitExceededError) as exc_info:
#             # Note: the exception is raised as soon as we decrease the limit.
#             limit.limit = 10
#         assert exc_info.value.value == 20

#         limit.limit = None
#         check_message_limit(100, False)

#     assert limit.limit is None


# def test_can_update_limit_value_on_reused_context_manager() -> None:
#     shared_limit = MessageLimit(10)

#     with shared_limit:
#         with shared_limit:
#             shared_limit.limit = 20

#             check_message_limit(15, False)

#             with pytest.raises(LimitExceededError) as exc_info:
#                 # TODO: Might change if we record initial message count.
#                 # Should trigger either limit (20).
#                 check_message_limit(30, False)

#     assert exc_info.value.value == 30
#     assert exc_info.value.limit == 20
