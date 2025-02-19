import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-python";

import clsx from "clsx";
import { Fragment, useEffect, useMemo, useRef } from "react";
import { ApplicationIcons } from "../../appearance/icons";
import { MetaDataGrid } from "../../metadata/MetaDataGrid";
import {
  ModelCall,
  ModelEvent,
  Request,
  Response,
  Tools1,
} from "../../types/log";
import { ModelUsagePanel } from "../../usage/ModelUsagePanel";
import {
  formatDateTime,
  formatNumber,
  formatPrettyDecimal,
} from "../../utils/format";
import { ChatView } from "../chat/ChatView";
import { EventPanel } from "./event/EventPanel";
import { EventSection } from "./event/EventSection";
import { TranscriptEventState } from "./types";

import { highlightElement } from "prismjs";
import styles from "./ModelEventView.module.css";

interface ModelEventViewProps {
  id: string;
  event: ModelEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}

/**
 * Renders the StateEventView component.
 */
export const ModelEventView: React.FC<ModelEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  className,
}) => {
  const totalUsage = event.output.usage?.total_tokens;
  const callTime = event.output.time;

  const subItems = [];
  if (totalUsage) {
    subItems.push(`${formatNumber(totalUsage)} tokens`);
  }
  if (callTime) {
    subItems.push(`${formatPrettyDecimal(callTime)} sec`);
  }
  const subtitle = subItems.length > 0 ? `(${subItems.join(", ")})` : "";

  // Note: despite the type system saying otherwise, this has appeared empircally
  // to sometimes be undefined
  const outputMessages = event.output.choices?.map((choice) => {
    return choice.message;
  });

  const entries: Record<string, unknown> = { ...event.config };
  entries["tool_choice"] = event.tool_choice;
  delete entries["max_connections"];

  // For any user messages which immediately preceded this model call, including a
  // panel and display those user messages (exclude tool_call messages as they
  // are already shown in the tool call above)
  const userMessages = [];
  for (const msg of event.input.slice().reverse()) {
    if (msg.role === "user" && !msg.tool_call_id) {
      userMessages.push(msg);
    } else {
      break;
    }
  }

  return (
    <EventPanel
      id={id}
      className={className}
      title={`Model Call: ${event.model} ${subtitle}`}
      subTitle={formatDateTime(new Date(event.timestamp))}
      icon={ApplicationIcons.model}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      <div data-name="Summary" className={styles.container}>
        <ChatView
          id={`${id}-model-output`}
          messages={[...userMessages, ...(outputMessages || [])]}
          className={clsx(styles.output)}
          numbered={false}
          toolCallStyle="compact"
        />
      </div>
      <div data-name="All" className={styles.container}>
        <div className={styles.all}>
          <EventSection title="Configuration" className={styles.tableSelection}>
            <MetaDataGrid entries={entries} plain={true} />
          </EventSection>

          <EventSection title="Usage" className={styles.tableSelection}>
            {event.output.usage !== null ? (
              <ModelUsagePanel usage={event.output.usage} />
            ) : undefined}
          </EventSection>

          <EventSection
            title="Tools"
            className={clsx(styles.tableSelection, styles.tools)}
          >
            <ToolsConfig tools={event.tools} />
          </EventSection>
        </div>

        <EventSection title="Messages">
          <ChatView
            id={`${id}-model-input-full`}
            messages={[...event.input, ...(outputMessages || [])]}
          />
        </EventSection>
      </div>

      {event.call ? (
        <APIView
          data-name="API"
          call={event.call}
          className={styles.container}
        />
      ) : (
        ""
      )}
    </EventPanel>
  );
};

interface APIViewProps {
  call: ModelCall;
  className?: string | string[];
}

export const APIView: React.FC<APIViewProps> = ({ call, className }) => {
  if (!call) {
    return null;
  }

  return (
    <div className={clsx(className)}>
      <EventSection title="Request">
        <APICodeCell contents={call.request} />
      </EventSection>
      <EventSection title="Response">
        <APICodeCell contents={call.response} />
      </EventSection>
    </div>
  );
};

interface APICodeCellProps {
  id?: string;
  contents: Request | Response;
}

export const APICodeCell: React.FC<APICodeCellProps> = ({ id, contents }) => {
  if (!contents) {
    return null;
  }

  const codeRef = useRef<HTMLElement>(null);
  const sourceCode = useMemo(() => {
    return JSON.stringify(contents, undefined, 2);
  }, [contents]);

  useEffect(() => {
    if (codeRef.current) {
      highlightElement(codeRef.current);
    }
  }, [codeRef.current, contents]);

  return (
    <div>
      <pre className={styles.codePre}>
        <code
          id={id}
          ref={codeRef}
          className={clsx("language-json", styles.code, "text-size-small")}
        >
          {sourceCode}
        </code>
      </pre>
    </div>
  );
};

interface ToolConfigProps {
  tools: Tools1;
}

const ToolsConfig: React.FC<ToolConfigProps> = ({ tools }) => {
  const toolEls = tools.map((tool, idx) => {
    return (
      <Fragment key={`${tool.name}-${idx}`}>
        <div className={clsx("text-style-label", "text-style-secondary")}>
          {tool.name}
        </div>
        <div>{tool.description}</div>
      </Fragment>
    );
  });

  return <div className={styles.toolConfig}>{toolEls}</div>;
};
