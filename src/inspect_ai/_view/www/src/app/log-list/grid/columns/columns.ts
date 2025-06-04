import { createColumnHelper } from "@tanstack/react-table";
import { EvalLogHeader } from "../../../../client/api/types";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { completedDateColumn } from "./CompletedDate";
import { fileNameColumn } from "./FileName";
import { iconColumn } from "./Icon";
import { modelColumn } from "./Model";
import { scoreColumn } from "./Score";
import { statusColumn } from "./Status";
import { taskColumn } from "./Task";

export const columnHelper = createColumnHelper<FileLogItem | FolderLogItem>();

export const getColumns = (
  logHeaders: Record<string, EvalLogHeader>,
  columnIds?: string[],
) => {
  const allColumns = [
    iconColumn(),
    taskColumn(logHeaders),
    fileNameColumn(),
    completedDateColumn(logHeaders),
    modelColumn(logHeaders),
    scoreColumn(logHeaders),
    statusColumn(logHeaders),
  ];
  if (columnIds) {
    return allColumns.filter((col) => columnIds.includes(col.id || ""));
  }
  return allColumns;
};
