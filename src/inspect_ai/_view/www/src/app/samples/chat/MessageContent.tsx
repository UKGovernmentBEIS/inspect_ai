import clsx from "clsx";

import { FC, ReactNode } from "react";
import {
  ContentAudio,
  ContentImage,
  ContentReasoning,
  ContentText,
  ContentVideo,
  Format1,
  Format2,
} from "../../../@types/log";
import { ContentTool } from "../../../app/types";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import styles from "./MessageContent.module.css";
import { ToolOutput } from "./tools/ToolOutput";

type ContentType =
  | string
  | string[]
  | ContentText
  | ContentReasoning
  | ContentImage
  | ContentAudio
  | ContentVideo
  | ContentTool;

interface MessageContentProps {
  contents:
    | string
    | string[]
    | (
        | ContentText
        | ContentReasoning
        | ContentImage
        | ContentAudio
        | ContentVideo
        | ContentTool
      )[];
}

/**
 * Renders message content based on its type.
 * Supports rendering strings, images, and tools using specific renderers.
 */
export const MessageContent: FC<MessageContentProps> = ({ contents }) => {
  if (Array.isArray(contents)) {
    return contents.map((content, index) => {
      if (typeof content === "string") {
        return messageRenderers["text"].render(
          `text-content-${index}`,
          {
            type: "text",
            text: content,
            refusal: null,
          },
          index === contents.length - 1,
        );
      } else {
        if (content) {
          const renderer = messageRenderers[content.type];
          if (renderer) {
            return renderer.render(
              `text-${content.type}-${index}`,
              content,
              index === contents.length - 1,
            );
          } else {
            console.error(`Unknown message content type '${content.type}'`);
          }
        }
      }
    });
  } else {
    // This is a simple string
    const contentText: ContentText = {
      type: "text",
      text: contents,
      refusal: null,
    };
    return messageRenderers["text"].render(
      "text-message-content",
      contentText,
      true,
    );
  }
};

interface MessageRenderer {
  render: (key: string, content: ContentType, isLast: boolean) => ReactNode;
}

const messageRenderers: Record<string, MessageRenderer> = {
  text: {
    render: (key, content, isLast) => {
      const c = content as ContentText;
      return (
        <MarkdownDiv
          key={key}
          markdown={c.text || ""}
          className={isLast ? "no-last-para-padding" : ""}
        />
      );
    },
  },
  reasoning: {
    render: (key, content, isLast) => {
      const r = content as ContentReasoning;
      if (!r.reasoning && !r.redacted) {
        return undefined;
      }
      return (
        <div key={key} className={clsx(styles.reasoning, "text-size-small")}>
          <div
            className={clsx(
              "text-style-label",
              "text-style-secondary",
              isLast ? "no-last-para-padding" : "",
            )}
          >
            Reasoning
          </div>
          <ExpandablePanel id={`${key}-reasoning`} collapse={true}>
            <MarkdownDiv
              markdown={
                r.redacted
                  ? "Reasoning encrypted by model provider."
                  : r.reasoning
              }
            />
          </ExpandablePanel>
        </div>
      );
    },
  },
  image: {
    render: (key, content) => {
      const c = content as ContentImage;
      if (c.image.startsWith("data:")) {
        return <img src={c.image} className={styles.contentImage} key={key} />;
      } else {
        return <code key={key}>{c.image}</code>;
      }
    },
  },
  audio: {
    render: (key, content) => {
      const c = content as ContentAudio;
      return (
        <audio controls key={key}>
          <source src={c.audio} type={mimeTypeForFormat(c.format)} />
        </audio>
      );
    },
  },
  video: {
    render: (key, content) => {
      const c = content as ContentVideo;
      return (
        <video width="500" height="375" controls key={key}>
          <source src={c.video} type={mimeTypeForFormat(c.format)} />
        </video>
      );
    },
  },
  tool: {
    render: (key, content) => {
      const c = content as ContentTool;
      return <ToolOutput output={c.content} key={key} />;
    },
  },
};

/**
 * Renders message content based on its type.
 * Supports rendering strings, images, and tools using specific renderers.
 */
const mimeTypeForFormat = (format: Format1 | Format2): string => {
  switch (format) {
    case "mov":
      return "video/quicktime";
    case "wav":
      return "audio/wav";
    case "mp3":
      return "audio/mpeg";
    case "mp4":
      return "video/mp4";
    case "mpeg":
      return "video/mpeg";
  }
};
