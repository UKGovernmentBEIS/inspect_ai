import { LogFile, LogSummary } from "../../client/api/types";

export interface LogItem {
  id: string;
  name: string;
  url?: string;
}

export interface FolderLogItem extends LogItem {
  type: "folder";
  itemCount: number;
}

export interface FileLogItem extends LogItem {
  type: "file";
  logFile: LogFile;
  logOverview?: LogSummary;
}

export interface PendingTaskItem extends LogItem {
  type: "pending-task";
  model: string;
}
