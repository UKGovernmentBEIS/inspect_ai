import { Uri } from "vscode";

export interface LogviewState {
  log_file?: Uri;
  log_dir: Uri;
  sample?: {
    id: string;
    epoch: string;
  }
  background_refresh?: boolean;
}
