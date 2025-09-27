import { EventNode } from "../types";

export interface TreeNodeVisitor {
  visit: (node: EventNode, parent?: EventNode) => EventNode[];
  flush?: () => EventNode[];
}

/**
 * Flatten the tree structure into a flat array of EventNode objects
 * Each node in the result will have its children set properly
 * @param eventNodes - The event nodes to flatten
 * @param collapsed - Record indicating which nodes are collapsed
 * @param visitors - Array of visitors to apply to each node
 * @param parentNode - The parent node of the current nodes being processed
 * @returns An array of EventNode objects
 */
export const flatTree = (
  eventNodes: EventNode[],
  collapsed: Record<string, boolean> | null,
  visitors?: TreeNodeVisitor[],
  parentNode?: EventNode,
): EventNode[] => {
  const result: EventNode[] = [];
  for (const node of eventNodes) {
    if (visitors && visitors.length > 0) {
      let pendingNodes: EventNode[] = [{ ...node }];

      for (const visitor of visitors) {
        const allResults: EventNode[] = [];
        for (const pendingNode of pendingNodes) {
          const visitorResult = visitor.visit(pendingNode);
          if (parentNode) {
            parentNode.children = visitorResult;
          }
          allResults.push(...visitorResult);
        }
        pendingNodes = allResults;
      }

      for (const pendingNode of pendingNodes) {
        const children = flatTree(
          pendingNode.children,
          collapsed,
          visitors,
          pendingNode,
        );
        pendingNode.children = children;
        result.push(pendingNode);
        if (collapsed === null || collapsed[pendingNode.id] !== true) {
          result.push(...children);
        }
      }

      for (const visitor of visitors) {
        if (visitor.flush) {
          const finalNodes = visitor.flush();
          result.push(...finalNodes);
        }
      }
    } else {
      result.push(node);
      const children = flatTree(node.children, collapsed, visitors, node);
      if (collapsed === null || collapsed[node.id] !== true) {
        result.push(...children);
      }
    }
  }

  return result;
};
