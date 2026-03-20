import clsx from "clsx";
import { FC, useMemo } from "react";
import { Events } from "../../../@types/log";
import { RenderedEventNode } from "../transcript/TranscriptVirtualList";
import { flatTree } from "../transcript/transform/flatten";
import { useEventNodes } from "../transcript/transform/hooks";
import transcriptStyles from "../transcript/TranscriptVirtualListComponent.module.css";

interface PrintTranscriptProps {
  events: Events;
}

/**
 * Non-virtualized transcript renderer for the print route.
 * Processes events through the same pipeline as the normal view
 * (fixupEventStream -> treeifyEvents -> flatTree) but always
 * renders all events expanded, with no virtualization.
 */
export const PrintTranscript: FC<PrintTranscriptProps> = ({ events }) => {
  const { eventNodes } = useEventNodes(events, false);

  // Flatten with null collapsed IDs = everything expanded
  const flattenedNodes = useMemo(() => {
    return flatTree(eventNodes, null);
  }, [eventNodes]);

  return (
    <div>
      {flattenedNodes.map((item, index) => {
        const paddingClass = index === 0 ? transcriptStyles.first : undefined;

        const previousIndex = index - 1;
        const nextIndex = index + 1;
        const previous =
          previousIndex > 0 && previousIndex <= flattenedNodes.length
            ? flattenedNodes[previousIndex]
            : undefined;
        const next =
          nextIndex < flattenedNodes.length
            ? flattenedNodes[nextIndex]
            : undefined;
        const attached =
          item.event.event === "tool" &&
          (previous?.event.event === "tool" ||
            previous?.event.event === "model");

        const attachedParent =
          item.event.event === "model" && next?.event.event === "tool";
        const attachedClass = attached ? transcriptStyles.attached : undefined;
        const attachedChildClass = attached
          ? transcriptStyles.attachedChild
          : undefined;
        const attachedParentClass = attachedParent
          ? transcriptStyles.attachedParent
          : undefined;

        return (
          <div
            id={item.id}
            key={item.id}
            className={clsx(transcriptStyles.node, paddingClass, attachedClass)}
            style={{
              paddingLeft: `${item.depth <= 1 ? item.depth * 0.7 : (0.7 + item.depth - 1) * 1}em`,
              paddingRight: `${item.depth === 0 ? undefined : ".7em"} `,
            }}
          >
            <RenderedEventNode
              node={item}
              next={next}
              className={clsx(attachedParentClass, attachedChildClass)}
            />
          </div>
        );
      })}
    </div>
  );
};
