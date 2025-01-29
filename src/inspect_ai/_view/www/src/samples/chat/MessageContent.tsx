import { MarkdownDiv } from "../../components/MarkdownDiv";
import { ContentTool } from "../../types";
import {
  ContentAudio,
  ContentImage,
  ContentText,
  ContentVideo,
  Format,
  Format1,
} from "../../types/log";
import styles from "./MessageContent.module.css";
import { ToolOutput } from "./tools/ToolOutput";

type ContentType =
  | string
  | string[]
  | ContentText
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
export const MessageContent: React.FC<MessageContentProps> = ({ contents }) => {
  if (Array.isArray(contents)) {
    return contents.map((content, index) => {
      if (typeof content === "string") {
        return messageRenderers["text"].render(
          {
            type: "text",
            text: content,
          },
          index === contents.length - 1,
        );
      } else {
        if (content) {
          const renderer = messageRenderers[content.type];
          if (renderer) {
            return renderer.render(content, index === contents.length - 1);
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
    };
    return messageRenderers["text"].render(contentText, true);
  }
};

interface MessageRenderer {
  render: (content: ContentType, isLast: boolean) => React.ReactNode;
}

const messageRenderers: Record<string, MessageRenderer> = {
  text: {
    render: (content, isLast) => {
      const c = content as ContentText;
      return (
        <MarkdownDiv
          markdown={c.text}
          className={isLast ? "no-last-para-padding" : ""}
        />
      );
    },
  },
  image: {
    render: (content) => {
      const c = content as ContentImage;
      if (c.image.startsWith("data:")) {
        return <img src={c.image} className={styles.contentImage} />;
      } else {
        return <code>{c.image}</code>;
      }
    },
  },
  audio: {
    render: (content) => {
      const c = content as ContentAudio;
      return (
        <audio controls>
          <source src={c.audio} type={mimeTypeForFormat(c.format)} />
        </audio>
      );
    },
  },
  video: {
    render: (content) => {
      const c = content as ContentVideo;
      return (
        <video width="500" height="375" controls>
          <source src={c.video} type={mimeTypeForFormat(c.format)} />
        </video>
      );
    },
  },
  tool: {
    render: (content) => {
      const c = content as ContentTool;
      return <ToolOutput output={c.content} />;
    },
  },
};

/**
 * Renders message content based on its type.
 * Supports rendering strings, images, and tools using specific renderers.
 */
const mimeTypeForFormat = (format: Format | Format1): string => {
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
