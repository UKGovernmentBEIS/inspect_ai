import clsx from "clsx";
import { FC, ReactNode } from "react";
import styles from "./CompactionData.module.css";
import ExpandablePanel from "../../../../components/ExpandablePanel";
import { RenderedText } from "../../../content/RenderedText";
import { MetaDataGrid } from "../../../content/MetaDataGrid";

export const kCompactionMetadata = "compaction_metadata"

export const CompactionData: FC<{ id: string, data: Record<string,unknown> }> = ({ id, data }) => {
  
  // get the compaction metadata
  const compactionMetadata = data[kCompactionMetadata] as Record<string,unknown>;

  let compactionContent: ReactNode | undefined = undefined;
  if (compactionMetadata.type === "anthropic_compact") {
     compactionContent = <ExpandablePanel id={`${id}-compacted-content`} collapse={true}>
        <RenderedText markdown={String(compactionMetadata.content)} />
    </ExpandablePanel>;
  } else {
    compactionContent = <MetaDataGrid id={`${id}-compacted-content-metadata`} className={styles.grid} entries={compactionMetadata} />;
  }
  
  return (
    <div className={clsx(styles.content, "text-size-small")}>
        <div
        className={clsx(
            "text-style-label",
            "text-style-secondary",
            styles.title
            )}
        >
        Compacted Content
        </div>
        {compactionContent}
       
    </div>
    );
};

