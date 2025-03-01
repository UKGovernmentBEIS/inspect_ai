from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import Success, async_dispatch, method
from pydantic import ValidationError

from bash.bash import BashSubprocess
from bash.bash_types import BashParams, CommandParams, RestartParams
from bash.constants import SERVER_PORT
from either import Left, Right
from validation import return_validation_error, validate_params

# NOTE: we're using the `Either` type from `oslash`. That's not a particularly
# widely used package, but it's already indirectly used by `jsonrpcserver`. If
# we get rid of `jsonrpcserver`, we should switch over to 'returns.result'.


bash_subprocess = BashSubprocess()


# curl -X POST http://localhost:5556/ -H "Content-Type: application/json" -d '{"jsonrpc": "2.0", "method": "bash", "params": { {"command": "echo foo"}, "id": 1}'


@method
async def bash(params):
    print(f"XXXX is bash method with {params=}")
    match validate_params(params, BashParams):
        case Left(e):
            return return_validation_error(e)
        case Right(BashParams(root=CommandParams(command=command))):
            return Success(bash_subprocess.execute_cmd(command))
        case Right(BashParams(root=RestartParams())):
            return Success(bash_subprocess.restart())
        case _:
            return return_validation_error(ValidationError("unhandled command", params))


@method
async def do_it():
    output = await bash_subprocess.execute_cmd("echo Hello, World!")
    return Success({"output": output.decode().strip()})


def main():
    async def handle_ping(_request: Request) -> Response:
        return Response(
            text="Yo\n",
            content_type="text/plain",
        )

    async def handle_request(request: Request) -> Response:
        return Response(
            text=await async_dispatch(await request.text()),
            content_type="application/json",
        )

    app = Application()
    app.router.add_post("/", handle_request)
    app.router.add_get("/", handle_ping)

    run_app(app, port=SERVER_PORT)


if __name__ == "__main__":
    main()
