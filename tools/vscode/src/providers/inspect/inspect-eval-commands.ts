import { Uri } from "vscode";
import { Command } from "../../core/command";
import { InspectEvalManager } from "./inspect-eval";
import { toAbsolutePath } from "../../core/path";
import { scheduleFocusActiveEditor } from "../../components/focus";

export function inspectEvalCommands(manager: InspectEvalManager): Command[] {
  return [new RunEvalCommand(manager), new DebugEvalCommand(manager)];
}

export class RunEvalCommand implements Command {
  constructor(private readonly manager_: InspectEvalManager) { }
  async execute(documentUri: Uri, fnName: string): Promise<void> {
    const cwd = toAbsolutePath(documentUri.fsPath);

    const evalPromise = this.manager_.startEval(cwd, fnName, false);
    scheduleFocusActiveEditor();
    await evalPromise;
  }
  private static readonly id = "inspect.runTask";
  public readonly id = RunEvalCommand.id;
}

export class DebugEvalCommand implements Command {
  constructor(private readonly manager_: InspectEvalManager) { }
  async execute(documentUri: Uri, fnName: string): Promise<void> {
    const cwd = toAbsolutePath(documentUri.fsPath);
    await this.manager_.startEval(cwd, fnName, true);
  }
  private static readonly id = "inspect.debugTask";
  public readonly id = DebugEvalCommand.id;
}

