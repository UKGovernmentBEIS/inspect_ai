import { FC, ReactNode } from "react";
import { ContentDocument } from "../../../../@types/log";
import { isImage } from "../../../../utils/mime";

import clsx from "clsx";
import { iconForMimeType } from "../../../appearance/icons";

import api from "../../../../client/api";
import { useStore } from "../../../../state/store";
import styles from "./ContentDocumentView.module.css";

interface ContentDocumentProps {
  id: string;
  document: ContentDocument;
}

export const ContentDocumentView: FC<ContentDocumentProps> = ({
  id,
  document,
}) => {
  const canDownloadFiles = useStore(
    (state) => state.capabilities.downloadFiles,
  );

  if (isImage(document.mime_type)) {
    return (
      <ContentDocumentFrame document={document} downloadable={canDownloadFiles}>
        <img
          className={clsx(styles.imageDocument)}
          src={document.document}
          alt={document.filename}
          id={id}
        />
      </ContentDocumentFrame>
    );
  } else {
    return (
      <ContentDocumentFrame
        document={document}
        downloadable={canDownloadFiles}
      />
    );
  }
};

interface ContentDocumentFrameProps {
  children?: ReactNode;
  document: ContentDocument;
  downloadable: boolean;
}

const ContentDocumentFrame: FC<ContentDocumentFrameProps> = ({
  document,
  children,
  downloadable,
}) => {
  return (
    <div
      className={clsx(
        styles.documentFrame,
        "text-size-small",
        "text-style-secondary",
      )}
    >
      <div className={clsx(styles.documentFrameTitle)}>
        <i className={clsx(iconForMimeType(document.mime_type))} />
        <div>
          {downloadable ? (
            <a
              className={clsx(styles.downloadLink)}
              onClick={() => {
                api.download_file(document.filename, document.document);
              }}
            >
              {document.filename}
            </a>
          ) : (
            document.filename
          )}
        </div>
      </div>
      {children}
    </div>
  );
};
