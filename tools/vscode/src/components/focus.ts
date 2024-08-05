import { commands, ExtensionContext, window } from "vscode";

export function scheduleReturnFocus(command: string) {
  setTimeout(() => {
    void commands.executeCommand(command);
  }, 200);
}

export function scheduleFocusActiveEditor() {
  setTimeout(() => {
    const editor = window.activeTextEditor;
    if (editor) {
      void window.showTextDocument(editor.document, editor.viewColumn, false);
    }
  }, 200);
}

export class FocusManager {
  private lastFocused: 'editor' | 'terminal' | 'notebook' | 'none' = 'none';

  constructor(context: ExtensionContext) {
    this.initialize(context);
  }

  private initialize(context: ExtensionContext) {
    // Track editor focus changes
    context.subscriptions.push(
      window.onDidChangeActiveTextEditor((editor) => {
        if (editor) {
          this.lastFocused = 'editor';
        }
      })
    );

    // Track terminal focus changes
    context.subscriptions.push(
      window.onDidOpenTerminal(async (terminal) => {
        const pid = await terminal.processId;
        if (window.activeTerminal?.processId === pid) {
          this.lastFocused = 'terminal';
        }
      })
    );

    // Handle terminal focus changes (when terminal is in focus and user types)
    context.subscriptions.push(
      window.onDidChangeTerminalState((terminal) => {
        if (terminal.state.isInteractedWith) {
          this.lastFocused = 'terminal';
        }
      })
    );

    // Handle when terminal becomes active
    context.subscriptions.push(
      window.onDidChangeActiveTerminal((terminal) => {
        if (terminal) {
          this.lastFocused = 'terminal';
        }
      })
    );

    // Track when window focus changes to ensure robustness
    context.subscriptions.push(
      window.onDidChangeWindowState((windowState) => {
        if (windowState.focused) {
          if (window.activeTextEditor) {
            this.lastFocused = 'editor';
          } else if (window.activeTerminal) {
            this.lastFocused = 'terminal';
          }
        }
      })
    );

    // Track when editors gain or lose focus
    context.subscriptions.push(
      window.onDidChangeTextEditorSelection((e) => {
        if (e.textEditor === window.activeTextEditor) {
          this.lastFocused = 'editor';
        }
      })
    );

    // Track notebook editor focus changes
    context.subscriptions.push(
      window.onDidChangeActiveNotebookEditor((notebookEditor) => {
        if (notebookEditor) {
          this.lastFocused = 'notebook';
        }
      })
    );
  }

  public getLastFocused(): 'editor' | 'terminal' | 'notebook' | 'none' {
    return this.lastFocused;
  }
}
