import { FC } from "react";
import { DownloadButton } from "../components/DownloadButton";
import "./DownloadPanel.css";

interface DownloadPanelProps {
  message: string;
  buttonLabel: string;
  fileName: string;
  fileContents: string | Blob | ArrayBuffer | ArrayBufferView;
}

export const DownloadPanel: FC<DownloadPanelProps> = ({
  message,
  buttonLabel,
  fileName,
  fileContents,
}) => {
  return (
    <div>
      <div className={"download-panel"}>
        <div className={"download-panel-message"}>{message}</div>
        <DownloadButton
          label={buttonLabel}
          fileName={fileName}
          fileContents={fileContents}
        />
      </div>
    </div>
  );
};
