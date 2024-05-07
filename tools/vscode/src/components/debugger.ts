import { DebugSession, debug } from "vscode";
import { activeWorkspaceFolder } from "../core/workspace";
import { sleep } from "../core/wait";
import { isServerListening } from "../core/port";

export class DebuggerManager {
  constructor(private readonly sessionName_: string) {
    debug.onDidStartDebugSession((debugSession: DebugSession) => {
      if (this.activeSession_) {
        throw new Error(
          "Unxpectedly tried to start a debug session when one is already running!"
        );
      }
      if (debugSession.configuration.name === sessionName_) {
        this.activeSession_ = debugSession;
      }
    });
    debug.onDidTerminateDebugSession((debugSession: DebugSession) => {
      if (
        this.activeSession_ &&
        debugSession.configuration.name === this.activeSession_?.name
      ) {
        this.activeSession_ = undefined;
      }
    });
  }

  public async attach(port: number) {
    // Stop any active sessions
    if (this.activeSession_) {
      await debug.stopDebugging(this.activeSession_);
      this.activeSession_ = undefined;
    }

    // Start a new session
    const debugConfiguration = {
      name: this.sessionName_,
      type: "python",
      request: "attach",
      connect: {
        host: "localhost",
        port,
      },
    };

    // Retry attaching a few times
    const maxRetries = 15;
    const waitMs = 250;
    let retries = 0;

    let launched = false;
    do {
      await sleep(waitMs);
      const listening = await isServerListening(
        debugConfiguration.connect.port,
        debugConfiguration.connect.host
      );
      if (listening) {
        launched = await debug.startDebugging(
          activeWorkspaceFolder(),
          debugConfiguration
        );
      }
      retries++;
    } while (!launched && retries < maxRetries);

    if (!launched) {
      throw new Error("Timed out while waiting for debugger to attach");
    }
  }
  private activeSession_: DebugSession | undefined;
}
