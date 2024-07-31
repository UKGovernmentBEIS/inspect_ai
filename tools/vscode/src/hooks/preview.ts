import {
  window,
  WebviewOptions,
  WebviewPanelOptions,
  ViewColumn,
} from "vscode";
import { HostWebviewPanel } from ".";

export function createPreviewPanel(
  viewType: string,
  title: string,
  preserveFocus?: boolean,
  options?: WebviewPanelOptions & WebviewOptions
): HostWebviewPanel {
  return window.createWebviewPanel(
    viewType,
    title,
    {
      viewColumn: ViewColumn.Beside,
      preserveFocus,
    },
    options
  ) as HostWebviewPanel;
}
