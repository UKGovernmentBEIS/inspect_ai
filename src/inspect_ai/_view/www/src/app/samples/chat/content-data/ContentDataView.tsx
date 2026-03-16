import { FC, ReactNode } from "react";
import { WebSearch } from "./WebSearch";

import clsx from "clsx";
import { ContentData } from "../../../../@types/log";
import { RecordTree } from "../../../content/RecordTree";
import styles from "./ContentDataView.module.css";
import { WebSearchContentData, WebSearchResults } from "./WebSearchResults";
import { CompactionData, kCompactionMetadata } from "./CompactionData";

export interface ContentDataProps {
  id: string;
  contentData: ContentData;
}

interface RenderableData {
  type?: string;
  name?: string;
  [key: string]: any;
}

export const ContentDataView: FC<ContentDataProps> = ({ id, contentData }) => {
  const renderableData = contentData.data as RenderableData;

  const renderer = contentDataRenderers.find((r) =>
    r.canRender(renderableData),
  );

  if (!renderer) {
    const { encrypted_content, ...record } = renderableData;
    return (
      <div className={clsx(styles.contentData)}>
        <RecordTree
          id={`${id}-tree`}
          record={record}
          className={clsx(styles.data)}
          defaultExpandLevel={0}
        />
      </div>
    );
  }

  return (
    <div className={clsx(styles.contentData)}>
      {renderer.render(id, renderableData)}
    </div>
  );
};

// The following handles rendering of the content data based on its type
// and name, allowing for different renderers to be used for different types of content data.

interface ContentDataRenderer {
  name: string;
  canRender: (data: RenderableData) => boolean;
  render: (id: string, data: RenderableData) => ReactNode;
}

const compactionDataRenderer: ContentDataRenderer = {
  name: "Compaction",
  canRender: (data: RenderableData) => {
    return Object.hasOwn(data, kCompactionMetadata);
  },
  render: (id: string, data: RenderableData): ReactNode => {
    return <CompactionData id={id} data={data} />;
  },
};

const webSearchServerToolRenderer: ContentDataRenderer = {
  name: "WebSearch",
  canRender: (data: RenderableData) => {
    return data.type === "server_tool_use" && data.name === "web_search";
  },
  render: (_id: string, data: RenderableData): ReactNode => {
    return <WebSearch query={data.input.query} />;
  },
};

const webSearchResultsServerToolRenderer: ContentDataRenderer = {
  name: "WebSearchResults",
  canRender: (data: RenderableData) => {
    return (
      data.type === "web_search_tool_result" && Array.isArray(data.content)
    );
  },
  render: (_id: string, data: RenderableData): ReactNode => {
    const results: WebSearchContentData[] =
      data.content as WebSearchContentData[];
    return <WebSearchResults results={results} />;
  },
};

const serverToolRenderer: ContentDataRenderer = {
  name: "ServerTool",
  canRender: (data: RenderableData) => data.type === "server_tool_use",
  render: (id: string, data: RenderableData): ReactNode => {
    return (
      <>
        <div
          className={clsx(
            "text-style-label",
            "text-style-secondary",
            "text-size-smaller",
          )}
        >
          Server Tool
        </div>
        <RecordTree
          id={`${id}-server-tool`}
          record={data}
          className={clsx(styles.data)}
        />
      </>
    );
  },
};

export const contentDataRenderers: ContentDataRenderer[] = [
  compactionDataRenderer,
  webSearchServerToolRenderer,
  webSearchResultsServerToolRenderer,
  serverToolRenderer,
];
