import { DocumentSymbol, Range, SymbolKind, TextDocument } from "vscode";

export const symbolIsTask = (document: TextDocument, pred: DocumentSymbol) => {
  if (pred.kind === SymbolKind.Function) {
    const textRange = new Range(pred.range.start, pred.range.end);
    const textBeforeFunction = document.getText(textRange);

    // Check if the text contains the `@task` decorator
    if (textBeforeFunction && textBeforeFunction.startsWith('@task')) {
      return true;
    }
  }
};