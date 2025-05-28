import { LogFile } from "../../client/api/types";

export interface LogItem {
  id: string;
  name: string;
  type: "folder" | "file";
  url?: string;
  logFile?: LogFile;
}
