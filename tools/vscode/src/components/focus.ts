import { commands, window } from "vscode";

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
