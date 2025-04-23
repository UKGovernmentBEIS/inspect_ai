import clsx from "clsx";
import { FC, Fragment, JSX, ReactNode } from "react";
import { JsonChange, Messages } from "../../../../@types/log";
import {
  HumanBaselineView,
  SessionLog,
} from "../../../../components/HumanBaselineView";
import { ChatView } from "../../chat/ChatView";

import styles from "./StateEventRenders.module.css";

interface Signature {
  remove: string[];
  replace: string[];
  add: string[];
}

interface ChangeType {
  type: string;
  signature?: Signature;
  match?: (changes: JsonChange[]) => boolean;
  render: (
    changes: JsonChange[],
    state: Record<string, unknown>,
  ) => JSX.Element;
}

const system_msg_added_sig: ChangeType = {
  type: "system_message",
  signature: {
    remove: ["/messages/0/source"],
    replace: ["/messages/0/role", "/messages/0/content"],
    add: ["/messages/1"],
  },
  render: (_changes, resolvedState) => {
    const messages = resolvedState["messages"] as Array<unknown>;
    const message = messages[0];
    return (
      <ChatView
        key="system_msg_event_preview"
        id="system_msg_event_preview"
        messages={[message] as Messages}
      />
    );
  },
};

const kToolPattern = "/tools/(\\d+)";

const use_tools: ChangeType = {
  type: "use_tools",
  signature: {
    add: ["/tools/0"],
    replace: ["/tool_choice"],
    remove: [],
  },
  render: (changes, resolvedState) => {
    return renderTools(changes, resolvedState);
  },
};

const add_tools: ChangeType = {
  type: "add_tools",
  signature: {
    add: [kToolPattern],
    replace: [],
    remove: [],
  },
  render: (changes, resolvedState) => {
    return renderTools(changes, resolvedState);
  },
};

const humanAgentKey = (key: string) => {
  return `HumanAgentState:${key}`;
};
const human_baseline_session: ChangeType = {
  type: "human_baseline_session",
  signature: {
    add: ["HumanAgentState:logs"],
    replace: [],
    remove: [],
  },
  render: (_changes, state: Record<string, unknown>) => {
    // Read the session values
    const started = state[humanAgentKey("started_running")] as number;
    const runtime = state[humanAgentKey("accumulated_time")] as number;
    const answer = state[humanAgentKey("answer")] as string;
    const completed = !!answer;
    const running = state[humanAgentKey("running_state")] as boolean;
    const rawSessions = state[humanAgentKey("logs")] as Record<string, unknown>;

    // Tweak the date value
    const startedDate = started ? new Date(started * 1000) : undefined;

    // Convert raw sessions into session logs
    const sessions: Record<string, SessionLog> = {};
    if (rawSessions) {
      for (const key of Object.keys(rawSessions)) {
        const value = rawSessions[key] as string;
        // this pulls the key apart into
        // <user>_<timestamp>.<type>
        const match = key.match(/(.*)_(\d+_\d+)\.(.*)/);
        if (match) {
          const user = match[1];
          const timestamp = match[2];
          const type = match[3];
          sessions[timestamp] = sessions[timestamp] || {};
          switch (type) {
            case "input":
              (sessions[timestamp] as SessionLog).input = value;
              break;
            case "output":
              (sessions[timestamp] as SessionLog).output = value;
              break;
            case "timing":
              (sessions[timestamp] as SessionLog).timing = value;
              break;
            case "name":
              (sessions[timestamp] as SessionLog).name = value;
              break;
          }

          (sessions[timestamp] as SessionLog).user = user;
        }
      }
    }

    return (
      <HumanBaselineView
        key="human_baseline_view"
        started={startedDate}
        running={running}
        completed={completed}
        answer={answer}
        runtime={runtime}
        sessionLogs={Object.values(sessions)}
      />
    );
  },
};

const renderTools = (
  changes: JsonChange[],
  resolvedState: Record<string, unknown>,
) => {
  // Find which tools were added in this change
  const toolIndexes: string[] = [];
  for (const change of changes) {
    const match = change.path.match(kToolPattern);
    if (match) {
      toolIndexes.push(match[1]);
    }
  }

  const toolName = (toolChoice: unknown): string => {
    if (
      typeof toolChoice === "object" &&
      toolChoice &&
      !Array.isArray(toolChoice)
    ) {
      return (toolChoice as Record<string, string>)["name"];
    } else {
      return String(toolChoice);
    }
  };

  const toolsInfo: Record<string, ReactNode> = {};

  // Show tool choice if it was changed
  const hasToolChoice = changes.find((change) => {
    return change.path.startsWith("/tool_choice");
  });
  if (resolvedState.tool_choice && hasToolChoice) {
    toolsInfo["Tool Choice"] = toolName(resolvedState.tool_choice);
  }

  // Show either all tools or just the specific tools
  const tools = resolvedState.tools as [];
  if (tools.length > 0) {
    if (toolIndexes.length === 0) {
      toolsInfo["Tools"] = (
        <Tools toolDefinitions={resolvedState.tools as ToolDefinition[]} />
      );
    } else {
      const filtered = tools.filter((_, index) => {
        return toolIndexes.includes(index.toString());
      });
      toolsInfo["Tools"] = <Tools toolDefinitions={filtered} />;
    }
  }

  return (
    <div key={"state-diff-tools"} className={clsx(styles.tools)}>
      {Object.keys(toolsInfo).map((key) => {
        return (
          <Fragment key={key}>
            <div
              className={clsx(
                "text-size-smaller",
                "text-style-label",
                "text-style-secondary",
              )}
            >
              {key}
            </div>
            {toolsInfo[key]}
          </Fragment>
        );
      })}
    </div>
  );
};

const createMessageRenderer = (name: string, role: string): ChangeType => {
  return {
    type: name,
    match: (changes: JsonChange[]) => {
      if (changes.length === 1) {
        const change = changes[0];
        if (change.op === "add" && change.path.match(/\/messages\/\d+/)) {
          return change.value["role"] === role;
        }
      }
      return false;
    },
    render: (changes) => {
      const message = changes[0].value as unknown;
      return (
        <ChatView
          key="system_msg_event_preview"
          id="system_msg_event_preview"
          messages={[message] as Messages}
        />
      );
    },
  };
};

export const RenderableChangeTypes: ChangeType[] = [
  system_msg_added_sig,
  createMessageRenderer("assistant_msg", "assistant"),
  createMessageRenderer("user_msg", "user"),
  use_tools,
  add_tools,
];

export const StoreSpecificRenderableTypes: ChangeType[] = [
  human_baseline_session,
];

interface ToolParameters {
  type: string;
  properties: {
    code: ToolProperty;
  };
  required: string[];
}

interface ToolProperty {
  type: string;
  description: string;
}

interface ToolDefinition {
  name: string;
  description: string;
  parameters?: ToolParameters;
}

interface ToolsProps {
  toolDefinitions: ToolDefinition[];
}
/**
 * Renders a list of tool components based on the provided tool definitions.
 */
export const Tools: FC<ToolsProps> = ({ toolDefinitions }) => {
  return (
    <div className={styles.toolsGrid}>
      {toolDefinitions.map((toolDefinition, idx) => {
        const toolName = toolDefinition.name;
        const toolArgs = toolDefinition.parameters?.properties
          ? Object.keys(toolDefinition.parameters.properties)
          : [];
        return (
          <Tool
            key={`${toolName}-${idx}`}
            toolName={toolName}
            toolArgs={toolArgs}
          />
        );
      })}
    </div>
  );
};

interface ToolProps {
  toolName: string;
  toolArgs?: string[];
  toolDesc?: string;
}
/**
 * Renders a single tool component.
 */
export const Tool: FC<ToolProps> = ({ toolName, toolArgs }) => {
  const functionCall =
    toolArgs && toolArgs.length > 0
      ? `${toolName}(${toolArgs.join(", ")})`
      : toolName;
  return (
    <code className={clsx("text-size-smallest", styles.tool)}>
      {functionCall}
    </code>
  );
};
