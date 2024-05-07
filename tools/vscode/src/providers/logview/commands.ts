import { Command } from "../../core/command";
import { InspectLogviewManager } from "./logview-manager";
import { showError } from "../../components/error";

export interface LogviewState {
  url?: string;
}

export interface LogviewOptions {
  state?: LogviewState;
  activate?: boolean;
}

export function logviewCommands(
  manager: InspectLogviewManager,
): Command[] {
  return [new ShowLogviewCommand(manager)];
}

class ShowLogviewCommand implements Command {
  constructor(private readonly manager_: InspectLogviewManager) { }
  async execute(): Promise<void> {
    // ensure logview is visible
    try {
      this.manager_.showInspectView();
    } catch (err: unknown) {
      await showError(
        "An error occurred while attempting to start Inspect View",
        err instanceof Error ? err : Error(String(err))
      );
    }

  }

  private static readonly id = "inspect.showLogview";
  public readonly id = ShowLogviewCommand.id;
}

