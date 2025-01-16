import api from "../api/index";
import "./DownloadButton.css";

interface DownloadButtonProps {
  label: string;
  fileName: string;
  fileContents: string | Blob | ArrayBuffer | ArrayBufferView;
}

export const DownloadButton: React.FC<DownloadButtonProps> = ({
  label,
  fileName,
  fileContents,
}) => {
  return (
    <button
      className={"btn btn-outline-primary download-button"}
      onClick={async () => {
        await api.download_file(fileName, fileContents);
      }}
    >
      {label}
    </button>
  );
};
