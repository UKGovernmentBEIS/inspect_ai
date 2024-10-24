import { workspace } from "vscode";

// Inspect Settings
export interface InspectSettings {
  jsonLogView: boolean;
}
export type InspectLogViewStyle = "html" | "text";

// Settings namespace and constants
const kInspectConfigSection = "inspect_ai";
const kInspectConfigJsonLogView = "jsonLogView";

// Manages the settings for the inspect extension
export class InspectSettingsManager {
  constructor(private readonly onChanged_: (() => void) | undefined) {
    workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(kInspectConfigSection)) {
        // Configuration for has changed
        this.settings_ = undefined;
        if (this.onChanged_) {
          this.onChanged_();
        }
      }
    });
  }
  private settings_: InspectSettings | undefined;

  // get the current settings values
  getSettings(): InspectSettings {
    if (!this.settings_) {
      this.settings_ = this.readSettings();
    }
    return this.settings_;
  }

  // Read settings values directly from VS.Code
  private readSettings() {
    const configuration = workspace.getConfiguration(kInspectConfigSection);
    const jsonLogView = configuration.get<boolean>(kInspectConfigJsonLogView);
    return {
      jsonLogView: jsonLogView !== undefined ? jsonLogView : true
    };
  }

}