import { Status } from "../../../@types/log";

// Flattened row data for the grid
export interface SampleRow {
  displayIndex?: number;
  logFile: string;
  created: string; // representing datetime
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
  [key: string]: any; // For dynamic score columns
}
