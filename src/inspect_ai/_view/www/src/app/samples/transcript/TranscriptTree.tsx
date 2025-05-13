import { FC, useMemo } from "react";
import { NodeRendererProps, Tree } from "react-arborist";
import { ApplicationIcons } from "../../appearance/icons";
import { EventNode } from "./types";

import styles from "./TranscriptTree.module.css";
import { EventPanel } from "./event/EventPanel";
interface TranscriptTreeProps {
  eventNodes: EventNode[];
  height?: number;
}

export const TranscriptTree: FC<TranscriptTreeProps> = ({ eventNodes }) => {
  // Calculate a tree height based on nodes - using the actual count of visible nodes
  const treeHeight = useMemo(() => {
    // Count visible nodes (including children)
    function countNodes(nodes: EventNode[]): number {
      let count = nodes.length;
      for (const node of nodes) {
        if (node.children && node.children.length > 0) {
          count += countNodes(node.children);
        }
      }
      return count;
    }

    // Each node is approximately 24px tall
    const totalNodes = countNodes(eventNodes);
    return totalNodes * 24; // rowHeight is typically 24px
  }, [eventNodes]);

  return (
    <EventPanel id={"transcript-tree"} className={styles.panel}>
      <Tree<EventNode>
        initialData={eventNodes}
        idAccessor="id"
        childrenAccessor={(d) => d.children}
        height={treeHeight}
        disableDrag={true}
        disableDrop={true}
        disableEdit={true}
        disableMultiSelection={true}
      >
        {renderNode}
      </Tree>
    </EventPanel>
  );
};

const renderNode = ({
  node,
  style,
  dragHandle,
}: NodeRendererProps<EventNode>) => {
  const iconClz = iconForNode(node.data);
  return (
    <div style={style} className={styles.node} ref={dragHandle}>
      <i className={iconClz} />
      {node.data.event.event}
    </div>
  );
};

const iconForNode = (node: EventNode): string => {
  if (node.event.event === "span_begin") {
    switch (node.event.type) {
      case "solver":
        return ApplicationIcons.solvers.default;
      case "tool":
        return ApplicationIcons.solvers.use_tools;
      default:
        return ApplicationIcons.subtask;
    }
  } else {
    switch (node.event.event) {
      case "subtask":
        return ApplicationIcons.subtask;
      case "approval":
        switch (node.event.decision) {
          case "approve":
            return ApplicationIcons.approvals.approve;
          case "reject":
            return ApplicationIcons.approvals.reject;
          case "escalate":
            return ApplicationIcons.approvals.escalate;
          case "modify":
            return ApplicationIcons.approvals.modify;
          case "terminate":
            return ApplicationIcons.approvals.terminate;
          default:
            return ApplicationIcons.approvals.approve;
        }
      case "model":
        return ApplicationIcons.model;
      case "score":
        return ApplicationIcons.scorer;

      default:
        return ApplicationIcons["toggle-right"];
    }
  }
};
