import { Command } from "../../core/command";
import { InspectLogviewManager } from "./logview-manager";
import { showError } from "../../components/error";
import { MessageItem, Uri, commands, window } from "vscode";
import { withMinimumInspectVersion } from "../../inspect/version";
import { kInspectOpenInspectViewVersion } from "../inspect/inspect-constants";
import { inspectLogInfo } from "../../inspect/logs";

export interface LogviewState {
  log_file?: Uri;
  log_dir: Uri;
  background_refresh?: boolean;
}

export interface LogviewOptions {
  state?: LogviewState;
  activate?: boolean;
}

export async function logviewCommands(
  manager: InspectLogviewManager,
): Promise<Command[]> {

  // Check whether the open in inspect view command should be enabled
  const enableOpenInView = withMinimumInspectVersion(kInspectOpenInspectViewVersion, () => {
    return true;
  }, () => { return false; });
  await commands.executeCommand(
    "setContext",
    "inspect_ai.enableOpenInView",
    enableOpenInView
  );

  return [new ShowLogviewCommand(manager), new OpenInInspectViewCommand(manager)];
}

class ShowLogviewCommand implements Command {
  constructor(private readonly manager_: InspectLogviewManager) { }
  async execute(): Promise<void> {
    // ensure logview is visible
    try {
      await this.manager_.showInspectView();
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


class OpenInInspectViewCommand implements Command {
  constructor(private readonly manager_: InspectLogviewManager) { }
  async execute(fileUri: Uri): Promise<void> {
    // ensure logview is visible
    try {
      // Validate that this is a non-running eval log
      const logState = await inspectLogInfo(fileUri);
      if (logState.hasEvalKey && logState.hasStatusKey) {
        if (logState.status !== "started") {
          await this.manager_.showLogFile(fileUri, "activate");
        } else {
          // This is a running log, we don't yet support viewing these
          const close: MessageItem = { title: "Close" };
          await window.showInformationMessage<MessageItem>(
            "The evalutation you have selected is currently running. Please wait until the evaluation is completed.",
            close
          );
        }
      } else {
        // This isn't a valid inspect file afaict
        const close: MessageItem = { title: "Close" };
        await window.showInformationMessage<MessageItem>(
          "The selected file doesn't appear to be a valid Inspect log file.",
          close
        );
      }
    } catch (err: unknown) {
      await showError(
        "An error occurred while attempting to start Inspect View",
        err instanceof Error ? err : Error(String(err))
      );
    }
  }

  private static readonly id = "inspect.openInInspectView";
  public readonly id = OpenInInspectViewCommand.id;
}
