import { Position, Selection, TextDocument, Uri, workspace } from "vscode";
import { readTaskData } from "./task";


// Provides a Selection for a task with a document
export const taskRangeForDocument = async (task: string, documentUri: Uri) => {
  const taskDatas = await tasksForDocument(documentUri);

  // Find the task that matches the name (or just select the first task)
  const taskData = taskDatas.find((data) => {
    return data.name === task;
  });

  // If the task is within this document, find its position
  if (taskData) {
    const position = new Position(taskData.line + 1, 0);
    return new Selection(position, position);
  }
};

export const firstTaskRangeForDocument = async (documentUri: Uri) => {

  const taskDatas = await tasksForDocument(documentUri);
  if (taskDatas.length > 0) {
    const position = new Position(taskDatas[0].line + 1, 0);
    return new Selection(position, position);
  }
};

// Provides a list of task DocumentSymbols for a document
const tasksForDocument = async (documentUri: Uri) => {
  const document = await workspace.openTextDocument(documentUri);
  const tasks = readTaskData(document);
  return tasks;
};


export const documentHasTasks = (document: TextDocument) => {
  const tasks = readTaskData(document);
  return tasks.length > 0;
};
