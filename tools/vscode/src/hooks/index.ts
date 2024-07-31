import vscode, { WebviewPanelOptions, WebviewOptions } from "vscode";
import { createPreviewPanel } from "./preview";
import { hasHooks, hooksExtensionHost } from "./hooks";

export interface HostWebviewPanel extends vscode.Disposable {
  readonly webview: vscode.Webview;
  readonly active: boolean;
  readonly visible: boolean;
  readonly viewColumn: vscode.ViewColumn;
  reveal(viewColumn?: vscode.ViewColumn, preserveFocus?: boolean): void;
  readonly onDidChangeViewState: vscode.Event<unknown>;
  readonly onDidDispose: vscode.Event<void>;
}

export interface ExtensionHost {
  // preview
  createPreviewPanel(
    viewType: string,
    title: string,
    preserveFocus?: boolean,
    options?: WebviewPanelOptions & WebviewOptions
  ): HostWebviewPanel;
}

export function extensionHost(): ExtensionHost {
  if (hasHooks()) {
    return hooksExtensionHost();
  } else {
    return defaultExtensionHost();
  }
}

function defaultExtensionHost(): ExtensionHost {
  return {
    createPreviewPanel,
  };
}
