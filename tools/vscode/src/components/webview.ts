import {
  Uri,
  WebviewPanel,
  window,
  ViewColumn,
  EventEmitter,
  ExtensionContext,
} from "vscode";

import { Disposable } from "../core/dispose";
import { getNonce } from "../core/nonce";

export interface ShowOptions {
  readonly preserveFocus?: boolean;
  readonly viewColumn?: ViewColumn;
}

export class InspectWebviewManager<T extends InspectWebview<S>, S> {
  constructor(
    protected readonly context: ExtensionContext,
    private readonly viewType_: string,
    private readonly title_: string,
    private readonly localResourceRoots: Uri[],
    private webviewType_: new (
      context: ExtensionContext,
      state: S,
      webviewPanel: WebviewPanel
    ) => T
  ) {
    this.extensionUri_ = context.extensionUri;

    context.subscriptions.push(
      window.registerWebviewPanelSerializer(this.viewType_, {
        deserializeWebviewPanel: (panel, state: S) => {
          this.restoreWebview(panel, state);
          setTimeout(() => {
            panel.dispose();
          }, 200);
          return Promise.resolve();
        },
      })
    );
  }

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
      const view = this.createWebview(this.context, state, options);
      this.registerWebviewListeners(view);
      this.activeView_ = view;
    }
    this.resolveOnShow();

    if (options?.preserveFocus) {
      this.preserveEditorFocus();
    }
  }

  public revealWebview() {
    if (this.activeView_) {
      this.activeView_.reveal();
      this.resolveOnShow();
      this.preserveEditorFocus();
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

  private resolveOnShow() {
    if (this.onShow_) {
      this.onShow_();
      this.onShow_ = undefined;
    }
  }

  private preserveEditorFocus() {
    // No need to take action here - we are already setting preserveFocus 
    // and ensuring that focus ends up in the correct places
  }

  private restoreWebview(panel: WebviewPanel, state: S): void {
    const view = new this.webviewType_(this.context, state, panel);
    this.registerWebviewListeners(view);
    this.activeView_ = view;
  }


  private createWebview(
    context: ExtensionContext,
    state: S,
    showOptions?: ShowOptions
  ): T {

    const webview = window.createWebviewPanel(
      this.viewType_,
      this.title_,
      {
        viewColumn: showOptions?.viewColumn || ViewColumn.Beside,
        preserveFocus: showOptions?.preserveFocus,
      },
      {
        enableScripts: true,
        enableForms: true,
        retainContextWhenHidden: true,
        localResourceRoots: [
          ...this.localResourceRoots,
          Uri.joinPath(context.extensionUri, "assets", "www")
        ],
      }
    );

    const inspectWebView = new this.webviewType_(context, state, webview);
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
  protected readonly _webviewPanel: WebviewPanel;

  private readonly _onDidDispose = this._register(new EventEmitter<void>());
  public readonly onDispose = this._onDidDispose.event;

  public constructor(
    private readonly context: ExtensionContext,
    state: T,
    webviewPanel: WebviewPanel
  ) {
    super();

    this._webviewPanel = this._register(webviewPanel);
    this._register(
      this._webviewPanel.onDidDispose(() => {
        this.dispose();
      })
    );

    this.show(state);
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
                      script-src 'nonce-${nonce}' ${allowUnsafe ? "'unsafe-eval'" : ""};
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
      Uri.joinPath(this.context.extensionUri, ...parts)
    );
  }

  protected escapeAttribute(value: string | Uri): string {
    return value.toString().replace(/"/g, "&quot;");
  }

}