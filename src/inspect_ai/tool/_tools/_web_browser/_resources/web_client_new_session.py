import argparse
import sys

from constants import SERVER_PORT
from rpc_client_helpers import RPCError, rpc_call
from web_browser_rpc_types import NewSessionArgs, NewSessionResponse


def main() -> None:
    parser = argparse.ArgumentParser(prog="web_client_new_session")
    parser.add_argument(
        "--headful", action="store_true", help="Run in headful mode for testing"
    )
    args_class = parser.parse_args()
    args_dict = vars(args_class)
    # TODO: Frick. this does no validation
    params_typed_dict = NewSessionArgs(headful=args_dict["headful"])
    params = dict(params_typed_dict)

    try:
        print(
            rpc_call(
                f"http://localhost:{SERVER_PORT}/",
                "new_session",
                params,
                NewSessionResponse,
            ).session_name
        )
    except RPCError as rpc_error:
        print(rpc_error, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
