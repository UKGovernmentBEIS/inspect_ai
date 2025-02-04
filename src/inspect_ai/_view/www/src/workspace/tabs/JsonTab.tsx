import { filename } from "../../utils/path";

import { Capabilities } from "../../api/types";
import { DownloadPanel } from "../../components/DownloadPanel";
import { JSONPanel } from "../../components/JsonPanel";
import styles from "./JsonTab.module.css";

const kJsonMaxSize = 10000000;

interface JsonTabProps {
  logFile?: string;
  capabilities: Capabilities;
  selected: boolean;
  json: string;
}

/**
 * Renders JSON tab
 */
export const JsonTab: React.FC<JsonTabProps> = ({
  logFile,
  capabilities,
  json,
}) => {
  if (logFile && json.length > kJsonMaxSize && capabilities.downloadFiles) {
    // This JSON file is so large we can't really productively render it
    // we should instead just provide a DL link
    const file = `${filename(logFile)}.json`;
    return (
      <div className={styles.jsonTab}>
        <DownloadPanel
          message="The JSON for this log file is too large to render."
          buttonLabel="Download JSON File"
          fileName={file}
          fileContents={json}
        />
      </div>
    );
  } else {
    return (
      <div className={styles.jsonTab}>
        <JSONPanel id="task-json-contents" json={json} simple={true} />
      </div>
    );
  }
};
