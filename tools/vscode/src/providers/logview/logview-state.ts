import { Uri } from "vscode";


export interface LogviewState {
  log_file?: Uri;
  log_dir: Uri;
  background_refresh?: boolean;
}
