import { LogHandle } from "../../../../client/api/types";

export interface LogListRow {
  id: string;
  name: string;
  type: "file" | "folder" | "pending-task";
  displayIndex?: number;
  url?: string;
  task?: string;
  model?: string;
  score?: number;
  status?: string;
  completedAt?: string;
  itemCount?: number;
  log?: LogHandle;
  [key: string]: any; // For dynamic score columns
}
