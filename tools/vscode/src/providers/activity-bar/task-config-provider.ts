import {
  Disposable,
  Uri,
  Webview,
  WebviewView,
  WebviewViewProvider,
  commands,
} from "vscode";
import { getNonce } from "../../core/nonce";
import {
  DocumentState,
  WorkspaceStateManager,
} from "../workspace/workspace-state-provider";
import {
  ActiveTaskChangedEvent,
  ActiveTaskManager,
} from "../active-task/active-task-provider";
import { basename } from "path";
import { inspectVersion } from "../../inspect";
import { InspectManager } from "../inspect/inspect-manager";
import { DocumentTaskInfo } from "../../components/task";

export type SetActiveTaskCommand = {
  type: "setActiveTask";
  task: DocumentTaskInfo;
  state: DocumentState;
} & Record<string, unknown>;

export type SetStateCmd = {
  command: "setStateValue";
  key: string;
  value: string;
};

export type SetStateParamCmd = {
  command: "setStateParam";
  key: string;
  value: string;
};

export type NoInspectCmd = {
  command: "noInspect";
};

export class TaskConfigurationProvider implements WebviewViewProvider {
  public static readonly viewType = "inspect_ai.task-configuration";

  constructor(
    private readonly extensionUri_: Uri,
    private readonly stateManager_: WorkspaceStateManager,
    private readonly taskManager_: ActiveTaskManager,
    private readonly inspectManager_: InspectManager
  ) {
  }

  public async resolveWebviewView(webviewView: WebviewView) {
    webviewView.webview.options = {
      // Allow scripts in the webview
      enableScripts: true,
      localResourceRoots: [this.extensionUri_],
    };


    const noInspectMsg = async () => {
      webviewView.description = "";
      await webviewView.webview.postMessage({
        type: "noInspect",
      });
    };

    const initMsg = async () => {
      await webviewView.webview.postMessage({
        type: "initialize",
      });
    };

    const updateTaskInfo = async (activeTaskInfo?: DocumentTaskInfo) => {
      if (activeTaskInfo) {
        // Remove any task parameters that may have been removed by this update
        await removeStaleTaskParams(activeTaskInfo);

        // Notify the UI
        await postActiveTaskMsg(activeTaskInfo);
      } else {
        webviewView.description = "";
      }
    };

    const removeStaleTaskParams = async (activeTaskInfo: DocumentTaskInfo) => {
      const currentState = this.stateManager_.getTaskState(
        activeTaskInfo.document.fsPath,
        activeTaskInfo.activeTask?.name
      );
      const keysToRemove = Object.keys(currentState.params || {}).filter(
        (key) => {
          return !activeTaskInfo.activeTask?.params.includes(key);
        }
      );
      if (keysToRemove.length > 0) {
        keysToRemove.forEach((key) => {
          if (currentState.params) {
            delete currentState.params[key];
          }
        });
        await this.stateManager_.setTaskState(
          activeTaskInfo.document.fsPath,
          currentState,
          activeTaskInfo.activeTask?.name
        );
      }
    };

    this.disposables_.push(
      this.taskManager_.onActiveTaskChanged(
        async (e: ActiveTaskChangedEvent) => {
          await updateSidebarState(e.activeTaskInfo);
        }
      )
    );

    // If the interpreter changes, refresh the tasks
    this.disposables_.push(this.inspectManager_.onInspectChanged(async () => {
      if (inspectVersion() !== null) {
        await initMsg();
        await this.taskManager_.refresh();
      } else {
        await noInspectMsg();
      }
    }));

    this.disposables_.push(webviewView.onDidChangeVisibility(async () => {
      const activeTask = this.taskManager_.getActiveTaskInfo();
      await updateTaskInfo(activeTask);
    }));

    webviewView.webview.html = this.htmlForWebview(webviewView.webview);
    webviewView.title = "Task";

    await initMsg();


    const postActiveTaskMsg = async (activeTaskInfo: DocumentTaskInfo) => {
      // Ignore active task changes that don't include a task (e.g. they are files)
      if (
        !activeTaskInfo.activeTask ||
        inspectVersion() === null
      ) {
        return;
      }

      const currentState = this.stateManager_.getTaskState(
        activeTaskInfo.document.fsPath,
        activeTaskInfo.activeTask?.name
      );
      await webviewView.webview.postMessage({
        type: "setActiveTask",
        task: activeTaskInfo,
        state: currentState,
      });
      webviewView.description =
        activeTaskInfo.activeTask?.name ||
        basename(activeTaskInfo.document.fsPath);
    };

    this.disposables_.push(
      this.taskManager_.onActiveTaskChanged(async (e) => {
        await updateSidebarState(e.activeTaskInfo);
        await updateTaskInfo(e.activeTaskInfo);
      })
    );

    if (inspectVersion() === null) {
      await noInspectMsg();
    }

    const activeTask = this.taskManager_.getActiveTaskInfo();
    await updateTaskInfo(activeTask);

    // Process UI messages
    webviewView.webview.onDidReceiveMessage(
      async (data: SetStateCmd | SetStateParamCmd) => {
        const activeTask = this.taskManager_.getActiveTaskInfo();
        if (activeTask) {
          const path = activeTask.document.fsPath;
          const currentState = this.stateManager_.getTaskState(
            path,
            activeTask.activeTask?.name
          );
          switch (data.command) {
            case "setStateValue":
              {
                switch (data.key) {
                  case "epochs":
                    currentState["epochs"] = data.value;
                    break;
                  case "limit":
                    currentState["limit"] = data.value;
                    break;
                  case "temperature":
                    currentState["temperature"] = data.value;
                    break;
                  case "maxTokens":
                    currentState["maxTokens"] = data.value;
                    break;
                  case "topP":
                    currentState["topP"] = data.value;
                    break;
                  case "topK":
                    currentState["topK"] = data.value;
                    break;
                }
              }
              break;
            case "setStateParam":
              currentState.params = currentState.params || {};
              currentState.params[data.key] = data.value;
              break;
          }
          await this.stateManager_.setTaskState(
            path,
            currentState,
            activeTask.activeTask?.name
          );
        }
      }
    );

    // Attach a listener to clean up resources when the webview is disposed
    webviewView.onDidDispose(() => {
      this.dispose();
    });
  }
  private disposables_: Disposable[] = [];
  private dispose() {
    this.disposables_.forEach((disposable) => {
      disposable.dispose();
    });
  }

  private htmlForWebview(webview: Webview) {
    // Get the local path to main script run in the webview, then convert it to a uri we can use in the webview.
    const scriptUri = webview.asWebviewUri(
      Uri.joinPath(this.extensionUri_, "out", "task-config-webview.js")
    );
    const codiconsUri = webview.asWebviewUri(
      Uri.joinPath(
        this.extensionUri_,
        "assets",
        "www",
        "codicon",
        "codicon.css"
      )
    );

    const codiconsFontUri = webview.asWebviewUri(
      Uri.joinPath(
        this.extensionUri_,
        "assets",
        "www",
        "codicon",
        "codicon.ttf"
      )
    );

    // Use a nonce to only allow a specific script to be run.
    const nonce = getNonce();

    return `<!DOCTYPE html>
              <html lang="en">
              <head>
                  <meta charset="UTF-8">
  
                  <!--
                      Use a content security policy to only allow loading styles from our extension directory,
                      and only allow scripts that have a specific nonce.
                      (See the 'webview-sample' extension sample for img-src content security policy examples)
                  -->
                  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; font-src ${webview.cspSource
      }; style-src ${webview.cspSource
      } 'unsafe-inline'; script-src 'nonce-${nonce}';">
                  <meta name="viewport" content="width=device-width, initial-scale=1.0">
                  <style type="text/css">
                  @font-face {
                    font-family: "codicon";
                    font-display: block;
                    src: url("${codiconsFontUri.toString()}?939d3cf562f2f1379a18b5c3113b59cd") format("truetype");
                  }
                  </style>
                  <link rel="stylesheet" type="text/css" href="${codiconsUri.toString()}">                  
                  <title>Task Options</title>
              </head>
              <body>
              <section class="component-container">
                <form id="configuration-controls" class="hidden">
                  <vscode-panels>
                  <vscode-panel-tab id="tab-1">Options</vscode-panel-tab>
                  <vscode-panel-tab id="tab-2">Task Args</vscode-panel-tab>
                  <vscode-panel-view id="view-1">
                    <div class="cols full-width two-cols">
                      <vscode-text-field id="limit" size="3" placeholder="default">Limit</vscode-text-field>
                      <vscode-text-field id="epochs" size="3" placeholder="default">Epochs</vscode-text-field>
                      <vscode-text-field id="max_tokens" size="3" placeholder="default">Max Tokens</vscode-text-field>
                      <vscode-text-field id="temperature" size="3" placeholder="default">Temperature</vscode-text-field>
                      <vscode-text-field id="top_p" size="3" placeholder="default">Top P</vscode-text-field>
                      <vscode-text-field id="top_k" size="3" placeholder="default">Top K</vscode-text-field>
                    </div>
                  </vscode-panel-view>
                  <vscode-panel-view id="view-2">
                    <div id="task-args" class="full-width cols">
                    </div>
                  </vscode-panel-view>
                </vscode-panels>      
                </form>
              </section>
            
              <script type="module" nonce="${nonce}" src="${scriptUri.toString()}"></script>
              </body>
              </html>`;
  }
}

const updateSidebarState = async (taskInfo?: DocumentTaskInfo) => {
  await commands.executeCommand(
    "setContext",
    "inspect_ai.task-configuration.task-active",
    taskInfo !== undefined
  );
};
