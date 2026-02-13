# Model Proxy Lifecycle: Start to Termination

This document traces the complete flow of running and terminating the model proxy within the sandbox via `sandbox_agent_bridge`.


## Sequence Diagram

```mermaid
sequenceDiagram
    box rgb(220, 235, 255) Inspect Host Process
        participant Bridge as sandbox_agent_bridge<br/>(bridge.py)
        participant Exec2 as exec_remote<br/>(ExecRemoteProcess + SandboxJSONRPCTransport)
    end

    box rgb(255, 240, 220) Sandbox - Stateless CLI per invocation
        participant CLI as inspect-sandbox-tools exec<br/>(main.py _exec)
    end

    box rgb(255, 220, 180) Sandbox - Long-Running Server via Unix Socket
        participant Server as aiohttp server<br/>(server.py)
        participant ExecAsync as exec_remote<br/>(Controller + Job)
    end

    box rgb(220, 255, 220) Sandbox - model_proxy subprocess
        participant Proxy as model_proxy process
    end

    Note over Bridge,Proxy: STARTUP

    Bridge->>+Exec2: sandbox_env.exec_remote(<br/>cmd=[SANDBOX_CLI, "model_proxy"] ...)
    Note right of Exec2: json_rpc = { "jsonrpc": "2.0", "method": "exec_remote_start",<br/>"params": {"command": "inspect-sandbox-tools model_proxy" ... } }
    Exec2->>+CLI: sandbox.exec(["inspect-sandbox-tools", "exec"], input=json_rpc)<br/>e.g. docker exec
    CLI->>+Server: HTTP POST json_rpc to server
    Note right of Server: async_dispatch parses json_rpc,<br/>routes to handler by method name
    Server->>+ExecAsync: exec_remote_start(command, env, ...)
    ExecAsync->>+Proxy: create_subprocess_shell()
    Proxy-->>ExecAsync: PID
    ExecAsync-->>-Server: SubmitResult(pid)
    Server-->>-CLI: JSON-RPC response
    CLI-->>-Exec2: SubmitResult(pid)
    Exec2-->>-Bridge: ExecRemoteProcess (proxy handle)

    Note over Bridge,Proxy: PROXY RUNNING - Bridge yields to caller.<br/>No poll loop — fire-and-forget pattern.

    Bridge->>Bridge: yield bridge (agent does work)

    Note over Bridge,Proxy: TERMINATION

    Bridge->>Bridge: finally block entered

    Bridge->>+Exec2: await proxy.kill()

    rect rgb(255, 230, 230)
        Note over Exec2,Proxy: Kill sequence
        Note right of Exec2: json_rpc = {"jsonrpc": "2.0", "method": "exec_remote_kill",<br/>"params": {"pid": 1234} }
        Exec2->>+CLI: sandbox.exec(["inspect-sandbox-tools", "exec"], input=json_rpc)
        CLI->>+Server: HTTP POST json_rpc to server
        Server->>+ExecAsync: exec_remote_kill
        ExecAsync->>Proxy: os.killpg(pgid, SIGTERM)

        alt process exits within 5s
            Proxy-->>ExecAsync: process.wait() returns
        else timeout
            ExecAsync->>Proxy: os.killpg(pgid, SIGKILL)
            Proxy-->>ExecAsync: process.wait() returns
        end

        ExecAsync-->>-Server: KillResult(stdout, stderr)
        Server-->>-CLI: JSON-RPC response
        CLI-->>-Exec2: KillResult
    end

    Exec2->>Exec2: enqueue remaining output
    Exec2-->>-Bridge: kill() returns

    Bridge->>Bridge: tg.cancel_scope.cancel()<br/>(cancels run_model_service)
    Bridge->>Bridge: task group exits cleanly
```
