import { createColumnHelper } from "@tanstack/react-table";
import { EvalLogHeader } from "../../../../client/api/types";
import { FileLogItem, FolderLogItem } from "../../LogItem";
import { completedDateColumn } from "./CompletedDate";
import { iconColumn } from "./Icon";
import { modelColumn } from "./Model";
import { scoreColumn } from "./Score";
import { statusColumn } from "./Status";
import { taskColumn } from "./Task";

export const columnHelper = createColumnHelper<FileLogItem | FolderLogItem>();

export const getColumns = (logHeaders: Record<string, EvalLogHeader>) => {
  return [
    iconColumn(),
    taskColumn(logHeaders),
    completedDateColumn(logHeaders),
    modelColumn(logHeaders),
    scoreColumn(logHeaders),
    statusColumn(logHeaders),
  ];
};
