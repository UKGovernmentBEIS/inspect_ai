import { extname } from "path";
import { NotebookCellKind, NotebookDocument, NotebookRange, Position, Range, Selection, Uri } from "vscode";
import { TaskData, readTaskData } from "./task";

export interface NotebookCellSelection {
  cell: NotebookRange,
  selection: Range
}

// Tests whether a given Uri is a notebook
export const isNotebook = (uri: Uri) => {
  return isNotebookPath(uri.path);
};

export const isNotebookPath = (path: string) => {
  const ext = extname(path);
  return ext === ".ipynb";
};

// Find the cell selection for a task within a notebook
// Note that this provides both the cell range and the selection
// within the cell
export const taskRangeForNotebook = (task: string, document: NotebookDocument): NotebookCellSelection | undefined => {
  const cells = cellTasks(document);

  // Find the cell that contains the task
  const cellTask = cells.find((cell) => {
    return cell.tasks.find((child) => {
      return child.name === task;
    });
  });

  if (cellTask) {
    const taskDetail = cellTask.tasks.find((child) => {
      return child.name === task;
    });
    if (taskDetail) {
      const index = cellTask.cellIndex;
      const position = new Position(taskDetail.line + 1, 0);
      return {
        cell: new NotebookRange(index, index),
        selection: new Selection(position, position)
      };
    }
  }
};

export const firstTaskRangeForNotebook = (document: NotebookDocument) => {
  const cells = cellTasks(document);

  // Find a cell that contains a task
  const cellTask = cells.find((cell) => {
    return cell.tasks.length > 0;
  });

  // If there is a cell with a task, compute its range
  if (cellTask) {

    // Just take the first task in the cell
    const task = cellTask.tasks[0];
    const index = cellTask.cellIndex;
    const position = new Position(task.line + 1, 0);
    return {
      cell: new NotebookRange(index, index),
      selection: new Selection(position, position)
    };
  }
};

// Describes a cell position and the symbols within a cell
interface CellTasks {
  cellIndex: number;
  tasks: TaskData[];
}

// Provides a list of cell and DocumentSymbols within the cells which contain tasks
export const cellTasks = (document: NotebookDocument): CellTasks[] => {
  const ranges: CellTasks[] = [];
  for (const cell of document.getCells()) {
    if (cell.kind === NotebookCellKind.Code) {
      const tasks = readTaskData(cell.document);
      if (tasks.length > 0) {
        ranges.push({ cellIndex: cell.index, tasks });
      }
    }
  }
  return ranges;
};