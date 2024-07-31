import * as vscode from "vscode";
import * as hooks from "positron";

import { ExtensionHost, HostWebviewPanel } from ".";
import { PreviewPanelOnDidChangeViewStateEvent } from "positron";

declare global {
  function acquirePositronApi(): hooks.PositronApi;
}

let api: hooks.PositronApi | null | undefined;

export function hooksApi(): hooks.PositronApi | undefined | null {
  if (api === undefined) {
    try {
      api = acquirePositronApi();
    } catch {
      api = null;
    }
  }
  return api;
}

export function hasHooks() {
  return !!hooksApi();
}

export function hooksExtensionHost(): ExtensionHost {
  return {
    createPreviewPanel: (
      viewType: string,
      title: string,
      preserveFocus?: boolean,
      options?: vscode.WebviewPanelOptions & vscode.WebviewOptions
    ): HostWebviewPanel => {
      // create preview panel
      // eslint-disable-next-line @typescript-eslint/no-non-null-asserted-optional-chain
      const panel = hooksApi()?.window.createPreviewPanel(
        viewType,
        title,
        preserveFocus,
        {
          enableScripts: options?.enableScripts,
          enableForms: options?.enableForms,
          localResourceRoots: options?.localResourceRoots,
          portMapping: options?.portMapping,
        }
      )!;

      // adapt to host interface
      return new HookWebviewPanel(panel);
    },
  };
}

// This panel provides the base interface than any host can provide in order for 
// our log viewer to work properly. It can be provided by vscode using the defaulthost 
// or the hooksExtensionHost if the positron api is detected
class HookWebviewPanel implements HostWebviewPanel {
  onDidChangeViewState: vscode.Event<PreviewPanelOnDidChangeViewStateEvent>;
  onDidDispose: vscode.Event<void>;

  constructor(private readonly panel_: hooks.PreviewPanel) {
    this.onDidChangeViewState = this.panel_.onDidChangeViewState;
    this.onDidDispose = this.panel_.onDidDispose;
  }

  get webview() {
    return this.panel_.webview;
  }

  get visible() {
    return this.panel_.visible;
  }

  get active() {
    return this.panel_.active;
  }

  get viewColumn() {
    return vscode.ViewColumn.Two;
  }


  reveal(_viewColumn?: vscode.ViewColumn, preserveFocus?: boolean) {
    this.panel_.reveal(preserveFocus);
  }

  dispose() {
    this.panel_.dispose();
  }
}
