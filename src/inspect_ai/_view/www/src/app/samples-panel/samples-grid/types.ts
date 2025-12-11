import { Status } from "../../../@types/log";

// Flattened row data for the grid
export interface SampleRow {
  type?: "sample" | "folder";
  displayIndex?: number;
  logFile: string;
  task: string;
  model: string;
  status?: Status;
  sampleId: string | number;
  epoch: number;
  input: string;
  target: string;
  error?: string;
  limit?: string;
  retries?: number;
  completed?: boolean;
  url?: string;
  name?: string;
  [key: string]: any; // For dynamic score columns
}
