import { extname } from "path";
import { DocumentSymbol, NotebookCellKind, NotebookDocument, NotebookRange, Position, Range, Selection, Uri, commands } from "vscode";

export interface NotebookCellSelection {
  cell: NotebookRange,
  selection: Range
}

// Tests whether a given Uri is a notebook
export const isNotebook = (uri: Uri) => {
  const ext = extname(uri.fsPath);
  return ext === ".ipynb";
};

// Find the cell selection for a task within a notebook
// Note that this provides both the cell range and the selection
// within the cell
export const taskRangeForNotebook = async (task: string, document: NotebookDocument): Promise<NotebookCellSelection | undefined> => {
  const cellSelections = await taskCellsForNotebook(document);

  // Find the cell that contains the task
  const cellSelection = cellSelections.find((selection) => {
    return selection.symbols.find((symbol) => {
      return symbol.name === task;
    });
  });

  // If there is a cell with this task, compute its range
  if (cellSelection) {
    const symbol = cellSelection.symbols.find((sym) => {
      return sym.name === task;
    });

    if (symbol) {
      const position = new Position(symbol.range.start.line + 1, 0);
      return {
        cell: new NotebookRange(cellSelection.cellIndex, cellSelection.cellIndex),
        selection: new Selection(position, position)
      };
    }
  }
};


// Describes a cell position and the symbols within a cell
interface NotebookSymbols {
  cellIndex: number;
  symbols: DocumentSymbol[];
}

// Provides a list of cell and DocumentSymbols within the cells which contain tasks
const taskCellsForNotebook = async (document: NotebookDocument): Promise<NotebookSymbols[]> => {
  const ranges: NotebookSymbols[] = [];
  for (const cell of document.getCells()) {
    if (cell.kind === NotebookCellKind.Code) {

      // Execute the document symbol provider for the cell document
      const symbols: DocumentSymbol[] = await commands.executeCommand(
        'vscode.executeDocumentSymbolProvider', cell.document.uri) || [];

      // Find the function symbol in the cell
      const taskSymbols = symbols.filter(symbol => {
        // Check for the `@task` decorator before the function
        const textRange = new Range(symbol.range.start, symbol.range.end);
        const textBeforeFunction = cell.document.getText(textRange);
        return textBeforeFunction.startsWith('@task');
      });

      if (taskSymbols.length > 0) {
        ranges.push({ cellIndex: cell.index, symbols: taskSymbols });
      }
    }
  }
  return ranges;
};