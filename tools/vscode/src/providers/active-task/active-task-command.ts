import { Command } from "../../core/command";
import { toAbsolutePath } from "../../core/path";
import { InspectEvalManager } from "../inspect/inspect-eval";
import { ActiveTaskManager } from "./active-task-provider";



export class RunActiveTaskCommand implements Command {
  constructor(private readonly manager_: ActiveTaskManager,
    private readonly inspectMgr_: InspectEvalManager
  ) { }
  async execute(): Promise<void> {
    const taskInfo = this.manager_.getActiveTaskInfo();
    if (taskInfo) {
      const docPath = toAbsolutePath(taskInfo.document.fsPath);
      await this.inspectMgr_.startEval(docPath, taskInfo.activeTask?.name, false);
    }
  }

  private static readonly id = "inspect.runActiveTask";
  public readonly id = RunActiveTaskCommand.id;
}

export class DebugActiveTaskCommand implements Command {
  constructor(private readonly manager_: ActiveTaskManager,
    private readonly inspectMgr_: InspectEvalManager
  ) { }
  async execute(): Promise<void> {
    const taskInfo = this.manager_.getActiveTaskInfo();
    if (taskInfo) {
      const docPath = toAbsolutePath(taskInfo.document.fsPath);
      await this.inspectMgr_.startEval(docPath, taskInfo.activeTask?.name, true);
    }
  }

  private static readonly id = "inspect.debugActiveTask";
  public readonly id = DebugActiveTaskCommand.id;
}

