import {
  DebugConfiguration,
  ExtensionContext,
  debug,
  window,
  workspace,
} from "vscode";
import { inspectEvalCommands } from "./inspect-eval-commands";
import { Command } from "../../core/command";
import {
  AbsolutePath,
  activeWorkspacePath,
  workspaceRelativePath,
} from "../../core/path";
import { WorkspaceStateManager } from "../workspace/workspace-state-provider";
import { inspectVersion } from "../../inspect";
import { inspectBinPath } from "../../inspect/props";
import { activeWorkspaceFolder } from "../../core/workspace";
import { findOpenPort } from "../../core/port";
import { log } from "../../core/log";
import { findEnvPythonPath } from "../../core/python";

export async function activateEvalManager(
  stateManager: WorkspaceStateManager,
  context: ExtensionContext
): Promise<[Command[], InspectEvalManager]> {
  // Activate the manager
  const inspectEvalMgr = new InspectEvalManager(stateManager);

  // Set up our terminal environment
  // Update the workspace id used in our terminal environments
  await stateManager.initializeWorkspaceId();

  const workspaceId = stateManager.getWorkspaceInstance();
  const env = context.environmentVariableCollection;
  log.append(`Workspace: ${workspaceId}`);
  log.append(`Resetting Terminal Workspace:`);

  env.delete("INSPECT_WORKSPACE_ID");
  env.append("INSPECT_WORKSPACE_ID", workspaceId);

  return [inspectEvalCommands(inspectEvalMgr), inspectEvalMgr];
}

export class InspectEvalManager {
  constructor(private readonly stateManager_: WorkspaceStateManager) { }

  public async startEval(file: AbsolutePath, task?: string, debug = false) {
    // if we don't have inspect bail and let the user know
    if (!inspectVersion()) {
      await window.showWarningMessage(
        `Unable to ${debug ? "Debug" : "Run"
        } Eval (Inspect Package Not Installed)`,
        {
          modal: true,
          detail: "pip install --upgrade inspect-ai",
        }
      );
      return;
    }

    const workspaceDir = activeWorkspacePath();
    const relativePath = workspaceRelativePath(file);

    // The base set of task args
    const taskArg = task ? `${relativePath}@${task}` : relativePath;
    const args = ["eval", taskArg];

    // Read the document state to determine flags
    const docState = this.stateManager_.getTaskState(file.path, task);

    // Forward the various doc state args
    const limit = docState.limit;
    if (
      debug === true &&
      workspace.getConfiguration("inspect_ai").get("debugSingleSample")
    ) {
      args.push(...["--limit", "1"]);
    } else if (limit) {
      args.push(...["--limit", limit]);
    }

    const epochs = docState.epochs;
    if (epochs) {
      args.push(...["--epochs", epochs]);
    }

    const temperature = docState.temperature;
    if (temperature) {
      args.push(...["--temperature", temperature]);
    }

    const maxTokens = docState.maxTokens;
    if (maxTokens) {
      args.push(...["--max-tokens", maxTokens]);
    }

    const topP = docState.topP;
    if (topP) {
      args.push(...["--top-p", topP]);
    }

    const topK = docState.topK;
    if (topK) {
      args.push(...["--top-k", topK]);
    }

    // Forwards task params
    const taskParams = docState.params;
    if (taskParams) {
      Object.keys(taskParams).forEach((key) => {
        const value = taskParams[key];
        args.push(...["-T", `${key}=${value}`]);
      });
    }

    // Find the python environment
    const useSubdirectoryEnvironments = workspace.getConfiguration("inspect_ai").get("useSubdirectoryEnvironments");
    const pythonPath = useSubdirectoryEnvironments ? findEnvPythonPath(file.dirname(), activeWorkspacePath()) : undefined;

    // If we're debugging, launch using the debugger
    if (debug) {
      // Handle debugging
      let debugPort = 5678;
      if (debug === true) {
        // Provision a port
        debugPort = await findOpenPort(debugPort);

        args.push("--debug-port");
        args.push(debugPort.toString());
      }

      // Pass the workspace ID to the debug environment so we'll 
      // properly target the workspace window when showing the logview
      const env = {
        INSPECT_WORKSPACE_ID: this.stateManager_.getWorkspaceInstance(),
      };

      await runDebugger(
        inspectBinPath()?.path || "inspect",
        args,
        workspaceDir.path,
        debugPort,
        env,
        pythonPath ? pythonPath : undefined
      );
    } else {
      // Run the command
      runEvalCmd(args, workspaceDir.path, pythonPath ? pythonPath : undefined);
    }
  }
}

const runEvalCmd = (args: string[], cwd: string, python?: AbsolutePath) => {
  // See if there a non-busy terminal that we can re-use
  const name = "Inspect Eval";
  let terminal = window.terminals.find((t) => {
    return t.name === name;
  });
  if (!terminal) {
    terminal = window.createTerminal({ name, cwd });
  }
  terminal.show();
  terminal.sendText(`cd ${cwd}`);

  const cmd = [];
  if (python) {
    cmd.push(`${python.path}`);
    cmd.push("-m");
    cmd.push("inspect_ai");
  } else {
    cmd.push("inspect");
  }
  cmd.push(...args);

  terminal.sendText(cmd.join(" "));
};

const runDebugger = async (
  program: string,
  args: string[],
  cwd: string,
  port: number,
  env?: Record<string, string>,
  pythonPath?: AbsolutePath
) => {
  const name = "Inspect Eval";
  const debugConfiguration: DebugConfiguration = {
    name,
    type: "python",
    request: "launch",
    program,
    args,
    console: "internalConsole",
    cwd,
    port,
    env,
    justMyCode: false,
    pythonPath: pythonPath?.path
  };
  await debug.startDebugging(activeWorkspaceFolder(), debugConfiguration);
};
