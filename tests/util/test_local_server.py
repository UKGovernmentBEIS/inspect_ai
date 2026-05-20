from inspect_ai._util.local_server import _server_arg_to_cli_key


def test_server_arg_to_cli_key_converts_top_level_underscores() -> None:
    assert _server_arg_to_cli_key("tensor_parallel_size") == "tensor-parallel-size"


def test_server_arg_to_cli_key_preserves_dotted_nested_underscores() -> None:
    assert (
        _server_arg_to_cli_key("speculative_config.num_speculative_tokens")
        == "speculative-config.num_speculative_tokens"
    )


def test_server_arg_to_cli_key_preserves_multiple_nested_segments() -> None:
    assert (
        _server_arg_to_cli_key("speculative_config.draft_model.num_speculative_tokens")
        == "speculative-config.draft_model.num_speculative_tokens"
    )
