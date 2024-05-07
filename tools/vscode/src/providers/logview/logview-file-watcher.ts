import { FileSystemWatcher, OutputChannel, Uri, workspace, Disposable } from "vscode";
import { InspectLogviewManager } from "./logview-manager";
import { workspacePath, workspaceRelativePath } from "../../core/path";
import { showError } from "../../components/error";

const kLogFilePattern = "**/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]-[0-9][0-9]-[0-9][0-9]_*_??????????????????????.json";
export class LogViewFileWatcher implements Disposable {
  constructor(
    private readonly logviewManager_: InspectLogviewManager,
    private readonly outputChannel_: OutputChannel,
  ) {
    this.outputChannel_.appendLine("Watching workspace...");
    this.watcher = workspace.createFileSystemWatcher(kLogFilePattern, false, true, true);
    const onChange = (e: Uri) => {
      const absPath = workspacePath(e.fsPath);

      const displayPath = workspaceRelativePath(absPath);
      this.outputChannel_.appendLine(`${displayPath} changed`);

      // Ensure we have an absolute path
      this.logviewManager_.showLogFile(Uri.file(absPath.path)).catch(async (err: Error) => {
        await showError("Unable to preview log file - failed to start Inspect View", err);
      });


    };
    this.watcher.onDidCreate(onChange);
  }

  dispose() {
    this.outputChannel_.appendLine("Stopping watching workspace...");
    this.watcher.dispose();
  }
  private watcher: FileSystemWatcher;
}