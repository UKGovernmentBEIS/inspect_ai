import { DocumentSymbol, Position, Range, Selection, SymbolKind, TextDocument, Uri, commands, workspace } from "vscode";


// Provides a Selection for a task with a document
export const taskRangeForDocument = async (task: string, documentUri: Uri) => {
  const taskSymbols = await tasksForDocument(documentUri);

  // Find the task that matches the name (or just select the first task)
  const taskSymbol = taskSymbols.find((symbol) => {
    return symbol.name === task;
  });

  // If the task is within this document, find its position
  if (taskSymbol) {
    const position = new Position(taskSymbol.range.start.line + 1, 0);
    return new Selection(position, position);
  }
};

// Provides a list of task DocumentSymbols for a document
const tasksForDocument = async (documentUri: Uri) => {
  const symbols = await commands.executeCommand<DocumentSymbol[]>(
    "vscode.executeDocumentSymbolProvider",
    documentUri
  );

  const document = await workspace.openTextDocument(documentUri);
  return symbols.filter((pred) => {
    return symbolIsTask(document, pred);
  });
};


export const documentHasTasks = async (document: TextDocument) => {
  const symbols = await commands.executeCommand<DocumentSymbol[]>(
    "vscode.executeDocumentSymbolProvider",
    document.uri
  );

  return symbols.some((pred) => {
    return symbolIsTask(document, pred);
  });
};

const symbolIsTask = (document: TextDocument, pred: DocumentSymbol) => {
  if (pred.kind === SymbolKind.Function) {
    const textRange = new Range(pred.range.start, pred.range.end);
    const textBeforeFunction = document.getText(textRange);

    // Check if the text contains the `@task` decorator
    if (textBeforeFunction && textBeforeFunction.startsWith('@task')) {
      return true;
    }
  }
};