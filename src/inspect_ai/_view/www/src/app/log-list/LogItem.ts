export interface LogItem {
  id: string;
  name: string;
  type: "folder" | "file";
  url?: string;
}
