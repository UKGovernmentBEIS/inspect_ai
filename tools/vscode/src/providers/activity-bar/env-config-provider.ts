import {
  Disposable,
  Uri,
  Webview,
  WebviewView,
  WebviewViewProvider,
  env,
} from "vscode";
import { getNonce } from "../../core/nonce";
import { WorkspaceStateManager } from "../workspace/workspace-state-provider";
import { WorkspaceEnvManager } from "../workspace/workspace-env-provider";
import { kInspectEnvValues } from "../inspect/inspect-constants";
import { inspectVersion } from "../../inspect";
import { InspectChangedEvent, InspectManager } from "../inspect/inspect-manager";
import { inspectVersionDescriptor } from "../../inspect/props";

export const kActiveTaskChanged = "activeTaskChanged";
export const kInitialize = "initialize";
export const kEnvChanged = "envChanged";

export type SetEnvCommand = {
  command: "setEnvValue";
  default: string;
  value: string;
} & Record<string, string>;

export type InitCommand = {
  command: "initialize";
};

export type OpenUrlCommand = {
  command: "openUrl";
  url: string;
};

export interface EnvConfiguration {
  provider?: string;
  model?: string;
  maxConnections?: string;
  maxRetries?: string;
  timeout?: string;
  logDir?: string;
  logLevel?: string;
  modelBaseUrl?: string;
}

// A list of the auto-complete models and the minimum
// version required in order to support the model
const kInspectModels: Record<string, string> = {
  "openai": "0.3.8",
  "anthropic": "0.3.8",
  "google": "0.3.8",
  "mistral": "0.3.8",
  "hf": "0.3.8",
  "together": "0.3.8",
  "bedrock": "0.3.8",
  "ollama": "0.3.9",
  "azureai": "0.3.8",
  "cf": "0.3.8",
  "llama-cpp-python": "0.3.39"
};

const inspectModels = () => {
  const descriptor = inspectVersionDescriptor();
  return Object.keys(kInspectModels).filter((key) => {
    const ver = kInspectModels[key];
    if (descriptor !== null) {
      return descriptor.version.compare(ver) > -1;
    } else {
      return false;
    }
  });
};


export class EnvConfigurationProvider implements WebviewViewProvider {
  public static readonly viewType = "inspect_ai.env-configuration-view";

  constructor(
    private readonly extensionUri_: Uri,
    private readonly envManager_: WorkspaceEnvManager,
    private readonly stateManager_: WorkspaceStateManager,
    private readonly inspectManager_: InspectManager
  ) { }
  private env: EnvConfiguration = {};

  public resolveWebviewView(webviewView: WebviewView) {
    webviewView.webview.options = {
      // Allow scripts in the webview
      enableScripts: true,
      localResourceRoots: [this.extensionUri_],
    };

    webviewView.webview.html = this.htmlForWebview(webviewView.webview);

    // Process UI messages
    webviewView.webview.onDidReceiveMessage(
      async (data: SetEnvCommand | InitCommand | OpenUrlCommand) => {

        const command = data.command;
        switch (command) {
          case "initialize": {
            if (inspectVersion() === null) {
              await noInspectMsg();
            } else {
              await initMsg();
            }
            break;
          }
          case "setEnvValue":
            {
              // Set the value
              setConfiguration(data.default, data.value, this.env);

              // Special case for provider, potentially restoring the 
              // previously used model
              let updateWebview = false;
              if (data.default === "provider") {
                const modelState = this.stateManager_.getModelState(data.value);
                setConfiguration("model", modelState.lastModel || "", this.env);
                updateWebview = true;
              }

              // Save the most recently used model for this provider
              if (this.env.provider && data.default === "model") {
                const modelState = this.stateManager_.getModelState(this.env.provider);
                modelState.lastModel = data.value;
                await this.stateManager_.setModelState(this.env.provider, modelState);
              }

              // Save the env
              this.envManager_.setValues(configToEnv(this.env));


              if (updateWebview) {
                await webviewView.webview.postMessage({
                  type: kEnvChanged,
                  message: {
                    env: this.env,
                  },
                });
              }

              break;
            }
          case "openUrl":
            await env.openExternal(Uri.parse(data.url));
            break;
        }
      }
    );

    const initMsg = async () => {

      // Merge current state
      this.env = envToConfig(this.envManager_);

      // Send the state over
      await webviewView.webview.postMessage({
        type: kInitialize,
        message: {
          env: this.env
        },
      });
    };

    const noInspectMsg = async () => {
      await webviewView.webview.postMessage({
        type: "noInspect",
      });
    };

    // Update the panel if the environment changes
    this.disposables_.push(this.envManager_.onEnvironmentChanged(async () => {
      this.env = envToConfig(this.envManager_);
      await webviewView.webview.postMessage({
        type: kEnvChanged,
        message: {
          env: this.env,
        },
      });
    }));

    // If the interpreter changes, refresh the tasks
    this.disposables_.push(this.inspectManager_.onInspectChanged(async (e: InspectChangedEvent) => {
      if (e.available) {
        await initMsg();
      } else {
        await noInspectMsg();
      }
    }));

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
      Uri.joinPath(this.extensionUri_, "out", "env-config-webview.js")
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

    const modelOptions = inspectModels().map((model) => {
      return `<fast-option value="${model}">${model}</fast-option>`;
    });

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
                  <vscode-panel-tab id="tab-1">Model</vscode-panel-tab>
                  <vscode-panel-tab id="tab-2">Logging</vscode-panel-tab>
                  <vscode-panel-view id="view-1">

                    <div class="group rows full-width" >
                      <div class="dropdown-container full-width">
                        <div id="provider-label-container"><label id="provider-label" for="provider">Model</label></div>
                        <div class="cols full-width no-wrap">
                          <fast-combobox autocomplete="both" id="provider" placeholder="Provider">
                            <fast-option value="">None</fast-option>
                            ${modelOptions.join("\n")}
                          </fast>
                        </div>
                      </div>
                      <div id="model-container">  
                        <vscode-text-field placeholder="Model Name" id="model"></vscode-text-field>
                      </div>
                      <div id="show-base-url-container">
                        <vscode-link id="show-base-url"><i class="codicon codicon-ellipsis"></i></vscode-link>
                      </div>
                      <div id="model-base-url-container" class="hidden full-width">
                        <vscode-text-field placeholder="Model Base Url" id="model-base-url" class="full-width"></vscode-text-field>
                      </div>
                      <div class="cols control-column full-width">
                        <vscode-text-field id="max-connections" size="3" placeholder="default" min="1">Connections</vscode-text-field>
                        <vscode-text-field id="max-retries" size="3" placeholder="default" min="1">Retries</vscode-text-field>
                        <vscode-text-field id="timeout" size="3" placeholder="default" min="1">Timeout</vscode-text-field>
                      </div>                      
                    </div>
                  </vscode-panel-view>
                  <vscode-panel-view id="view-2">
                    <div class="rows full-width">
                      <div class="cols full-width">
                        <vscode-text-field placeholder="default" id="log-dir" size="16" class="full-width"
                          >Log Directory</vscode-text-field
                        >
                        
                        <div class="dropdown-container full-width">
                          <label for="provider">Log Level</label>  
                          <vscode-dropdown id="log-level" position="below" class="full-width">
                            <vscode-option value="">default</vscode-option>
                            <vscode-option value="debug">debug</vscode-option>
                            <vscode-option value="http">http</vscode-option>
                            <vscode-option value="info">info</vscode-option>
                            <vscode-option value="warning" selected="true">warning</vscode-option>
                            <vscode-option value="error">error</vscode-option>
                            <vscode-option value="critical">critical</vscode-option>
                          </vscode-dropdown>
                        </div>
                      </div>
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

const envToConfig = (envManager: WorkspaceEnvManager) => {
  const config: EnvConfiguration = {};
  const env = envManager.getValues();
  const providerModelStr = env[kInspectEnvValues.providerModel];
  if (providerModelStr) {
    const providerModelParts = providerModelStr.split("/");
    if (providerModelParts.length > 1) {
      config.provider = providerModelParts[0];
      config.model = providerModelParts.slice(1).join("/");
    } else {
      config.provider = providerModelStr;
    }
  } else {
    config.provider = "";
    config.model = "";
  }

  const logLevel = env[kInspectEnvValues.logLevel];
  if (logLevel) {
    config.logLevel = logLevel;
  }

  const logDir = env[kInspectEnvValues.logDir];
  if (logDir) {
    config.logDir = logDir;
  }

  const maxConnections = env[kInspectEnvValues.connections];
  if (maxConnections) {
    config.maxConnections = maxConnections;
  }

  const maxRetries = env[kInspectEnvValues.retries];
  if (maxRetries) {
    config.maxRetries = maxRetries;
  }

  const timeout = env[kInspectEnvValues.timeout];
  if (timeout) {
    config.timeout = timeout;
  }

  const modelBaseUrl = env[kInspectEnvValues.modelBaseUrl];
  if (modelBaseUrl) {
    config.modelBaseUrl = modelBaseUrl;
  }

  return config;
};

const configToEnv = (config: EnvConfiguration): Record<string, string> => {
  const env: Record<string, string> = {};
  if (config.provider && config.model) {
    env[kInspectEnvValues.providerModel] = `${config.provider}/${config.model}`;
  } else {
    env[kInspectEnvValues.providerModel] = "";
  }

  env[kInspectEnvValues.logLevel] = config.logLevel || "";
  env[kInspectEnvValues.logDir] = config.logDir || "";
  env[kInspectEnvValues.connections] = config.maxConnections || "";
  env[kInspectEnvValues.retries] = config.maxRetries || "";
  env[kInspectEnvValues.timeout] = config.timeout || "";
  env[kInspectEnvValues.modelBaseUrl] = config.modelBaseUrl || "";

  return env;
};

const setConfiguration = (
  key: string,
  value: string,
  state: EnvConfiguration
) => {
  switch (key) {
    case "provider":
      state.provider = value;
      break;
    case "model":
      state.model = value;
      break;
    case "logDir":
      state.logDir = value;
      break;
    case "logLevel":
      state.logLevel = value;
      break;
    case "maxConnections":
      state.maxConnections = value;
      break;
    case "maxRetries":
      state.maxRetries = value;
      break;
    case "timeout":
      state.timeout = value;
      break;
    case "modelBaseUrl":
      state.modelBaseUrl = value;
      break;
  }
};
