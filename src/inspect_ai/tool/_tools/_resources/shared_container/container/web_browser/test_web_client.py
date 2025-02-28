import sys

from web_browser_rpc_types import GoArgs
from web_client import _parse_args


def test_parse_args_session_name_handling() -> None:
    test_cases: list[tuple[list[str], str, object]] = [
        (
            ["cli", "--session_name=my_session", "web_go", "boston.com"],
            "web_go",
            GoArgs(session_name="my_session", url="boston.com"),
        ),
        (
            ["cli", "web_go", "boston.com", "--session_name=my_session"],
            "web_go",
            GoArgs(session_name="my_session", url="boston.com"),
        ),
        (
            ["cli", "web_go", "--session_name=my_session", "boston.com"],
            "web_go",
            GoArgs(session_name="my_session", url="boston.com"),
        ),
        (
            ["cli", "--session_name", "my_session", "web_go", "boston.com"],
            "web_go",
            GoArgs(session_name="my_session", url="boston.com"),
        ),
        (
            ["cli", "web_go", "boston.com", "--session_name", "my_session"],
            "web_go",
            GoArgs(session_name="my_session", url="boston.com"),
        ),
        (
            ["cli", "web_go", "--session_name", "my_session", "boston.com"],
            "web_go",
            GoArgs(session_name="my_session", url="boston.com"),
        ),
    ]
    for argv, expected_cmd, expected_params in test_cases:
        sys.argv = argv
        cmd, params = _parse_args()
        assert cmd == expected_cmd
        assert params == expected_params
