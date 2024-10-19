import {
  Uri,
  ViewColumn,
  EventEmitter,
  ExtensionContext,
  window,
  commands,
  WebviewPanel,
} from "vscode";

import { Disposable } from "../core/dispose";
import { getNonce } from "../core/nonce";
import { ExtensionHost, HostWebviewPanel } from "../hooks";
import { isNotebook } from "./notebook";
import { FocusManager } from "./focus";
import { log } from "../core/log";
import { InspectViewServer } from "../providers/inspect/inspect-view-server";

export interface ShowOptions {
  readonly preserveFocus?: boolean;
  readonly viewColumn?: ViewColumn;
}

export class InspectWebviewManager<T extends InspectWebview<S>, S> {
  constructor(
    protected readonly context_: ExtensionContext,
    private readonly server_: InspectViewServer,
    private readonly viewType_: string,
    private readonly title_: string,
    private readonly localResourceRoots: Uri[],
    private webviewType_: new (
      context: ExtensionContext,
      server: InspectViewServer,
      state: S,
      webviewPanel: HostWebviewPanel
    ) => T,
    private host_: ExtensionHost
  ) {
    this.extensionUri_ = context_.extensionUri;

    context_.subscriptions.push(
      window.registerWebviewPanelSerializer(this.viewType_, {
        deserializeWebviewPanel: (panel: WebviewPanel, state?: S) => {
          state = state || this.getWorkspaceState();
          if (state) {
            this.restoreWebview(panel as HostWebviewPanel, state);
          } else {
            setTimeout(() => {
              panel.dispose();
            }, 200);
          }
          return Promise.resolve();
        },
      })
    );

    this.focusManager_ = new FocusManager(context_);
  }
  private focusManager_: FocusManager;

  public setOnShow(f: () => void) {
    this.onShow_ = f;
  }

  public setOnClose(f: () => void) {
    this.onClose_ = f;
  }

  public showWebview(state: S, options?: ShowOptions): void {
    if (this.activeView_) {
      this.activeView_.show(state, options);
    } else {
      const view = this.createWebview(this.context_, state, options);
      this.registerWebviewListeners(view);
      this.activeView_ = view;
    }
    this.resolveOnShow();

    if (options?.preserveFocus) {
      this.preserveEditorFocus();
    }
  }

  public revealWebview(preserveEditorFocus: boolean) {
    if (this.activeView_) {
      this.activeView_.reveal();
      this.resolveOnShow();
      if (preserveEditorFocus) {
        this.preserveEditorFocus();
      }
    }
  }

  public hasWebview() {
    return !!this.activeView_;
  }

  public isVisible() {
    return !!this.activeView_ && this.activeView_.webviewPanel().visible;
  }

  public isActive() {
    return !!this.activeView_ && this.activeView_.webviewPanel().active;
  }

  protected onViewStateChanged() { }

  protected getWorkspaceState(): S | undefined {
    return undefined;
  }


  private resolveOnShow() {
    if (this.onShow_) {
      this.onShow_();
      this.onShow_ = undefined;
    }
  }

  private preserveEditorFocus() {
    // Replace focus to the correct spot
    const lastFocused = this.focusManager_.getLastFocused();
    if (lastFocused === "terminal") {
      // The terminal
      setTimeout(() => {
        commands.executeCommand('workbench.action.terminal.focus').then(
          () => {
            // Command executed successfully
          },
          (error) => {
            log.append("Couldn't focus terminal.\n" + error);
          }
        );
      }, 50);
    } else if (lastFocused === "editor") {
      // The editor
      const editor = window.activeTextEditor;
      if (editor) {
        if (!isNotebook(editor.document.uri)) {
          setTimeout(() => {
            // Refocus the active document by calling showTextDocument with the active editor
            window.showTextDocument(editor.document, editor.viewColumn).then(() => {

            }, (error) => {
              log.append("Couldn't focus editor.\n" + error);
            });
          }, 50);
        }

      }
    } else if (lastFocused === "notebook") {
      // A notebook
      setTimeout(() => {
        if (window.activeNotebookEditor) {
          window.activeNotebookEditor.revealRange(window.activeNotebookEditor.selection);
        }
      }, 50);
    }
  }


  private restoreWebview(panel: HostWebviewPanel, state: S): void {
    const view = new this.webviewType_(this.context_, this.server_, state, panel);
    this.registerWebviewListeners(view);
    this.activeView_ = view;
  }

  private createWebview(
    context: ExtensionContext,
    state: S,
    showOptions?: ShowOptions
  ): T {
    const previewPanel = this.host_.createPreviewPanel(
      this.viewType_,
      this.title_,
      showOptions?.preserveFocus,
      {
        enableScripts: true,
        enableForms: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          ...this.localResourceRoots,
          Uri.joinPath(context.extensionUri, "assets", "www"),
        ],
      }
    );

    const inspectWebView = new this.webviewType_(context, this.server_, state, previewPanel);
    return inspectWebView;
  }

  private registerWebviewListeners(view: T) {
    view.onDispose(() => {
      if (this.activeView_ === view) {
        this.activeView_ = undefined;
        this.onViewStateChanged();
        if (this.onClose_) {
          this.onClose_();
          this.onClose_ = undefined;
        }
      }
    });
    view.webviewPanel().onDidChangeViewState(() => {
      this.onViewStateChanged();
    });
  }

  public dispose() {
    if (this.activeView_) {
      this.activeView_.dispose();
      this.activeView_ = undefined;
    }
    let item: Disposable | undefined;
    while ((item = this.disposables_.pop())) {
      item.dispose();
    }
  }
  protected activeView_?: T;
  protected readonly disposables_: Disposable[] = [];

  private onShow_?: () => void;
  private onClose_?: () => void;
  private readonly extensionUri_: Uri;
}

export abstract class InspectWebview<T> extends Disposable {
  protected readonly _webviewPanel: HostWebviewPanel;

  private readonly _onDidDispose = this._register(new EventEmitter<void>());
  public readonly onDispose = this._onDidDispose.event;

  public constructor(
    private readonly _context: ExtensionContext,
    private readonly _server: InspectViewServer,
    state: T,
    webviewPanel: HostWebviewPanel
  ) {
    super();

    this._webviewPanel = this._register(webviewPanel);
    this._register(
      this._webviewPanel.onDidDispose(() => {
        this.dispose();
      })
    );
  }

  public override dispose() {
    this._onDidDispose.fire();
    super.dispose();
  }

  public show(state: T, options?: ShowOptions) {
    this._webviewPanel.webview.html = this.getHtml(state);
    this._webviewPanel.reveal(options?.viewColumn, options?.preserveFocus);
  }

  public reveal() {
    this._webviewPanel.reveal(undefined, true);
  }

  public webviewPanel() {
    return this._webviewPanel;
  }

  protected abstract getHtml(state: T): string;

  protected getExtensionVersion(): string {
    return (this._context.extension.packageJSON as Record<string, unknown>)
      .version as string;
  }

  protected webviewHTML(
    js: Array<string[]>,
    css: string[],
    headerHtml: string,
    bodyHtml: string,
    allowUnsafe = false
  ) {
    const nonce = getNonce();

    if (!Array.isArray(js)) {
      js = [js];
    }

    const jsHtml = js.reduce((html, script) => {
      return (
        html +
        `<script src="${this.extensionResourceUrl(
          script
        ).toString()}" nonce="${nonce}"></script>\n`
      );
    }, "");

    const mainCss = this.extensionResourceUrl(css);
    const codiconsUri = this.extensionResourceUrl([
      "assets",
      "www",
      "codicon",
      "codicon.css",
    ]);
    const codiconsFontUri = this.extensionResourceUrl([
      "assets",
      "www",
      "codicon",
      "codicon.ttf",
    ]);

    return /* html */ `<!DOCTYPE html>
              <html>
              <head>
                  <meta http-equiv="Content-type" content="text/html;charset=UTF-8">
  
                  <meta http-equiv="Content-Security-Policy" content="
                      default-src 'none';
                      font-src ${this._webviewPanel.webview.cspSource};
                      style-src ${this._webviewPanel.webview.cspSource} ${allowUnsafe ? "'unsafe-inline'" : ""
      };
                      script-src 'nonce-${nonce}' ${allowUnsafe ? "'unsafe-eval'" : ""
      };
            connect-src ${this._webviewPanel.webview.cspSource} ;
                      frame-src *;
                      ">
  
                  ${headerHtml}
  
                  <link rel="stylesheet" type="text/css" href="${mainCss.toString()}">
          <style type="text/css">
          @font-face {
            font-family: "codicon";
            font-display: block;
            src: url("${codiconsFontUri.toString()}?939d3cf562f2f1379a18b5c3113b59cd") format("truetype");
          }
          </style>
                  <link rel="stylesheet" type="text/css" href="${codiconsUri.toString()}">
              </head>
              <body>
                  ${bodyHtml}
                  ${jsHtml}
              </body>
              </html>`;
  }

  protected extensionResourceUrl(parts: string[]): Uri {
    return this._webviewPanel.webview.asWebviewUri(
      Uri.joinPath(this._context.extensionUri, ...parts)
    );
  }

  protected escapeAttribute(value: string | Uri): string {
    return value.toString().replace(/"/g, "&quot;");
  }
}
