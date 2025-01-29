import { EvalSummary } from "./api/types";
import { ContentImage, ContentText } from "./types/log";

export interface Capabilities {
  downloadFiles: boolean;
  webWorkers: boolean;
}

export interface CurrentLog {
  name: string;
  contents: EvalSummary;
}

export interface Logs {
  log_dir: string;
  files: string[];
}

export interface ScoreLabel {
  name: string;
  scorer: string;
}

export interface ScoreFilter {
  value?: string;
}

export type SampleMode = "none" | "single" | "many";

export interface ContentTool {
  type: "tool";
  content: (ContentImage | ContentText)[];
}
