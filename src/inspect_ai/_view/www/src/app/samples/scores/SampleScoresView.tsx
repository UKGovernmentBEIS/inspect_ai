import clsx from "clsx";
import { EvalSample } from "../../../@types/log";
import { Card, CardBody } from "../../../components/Card";
import { inputString } from "../../../utils/format";

import { FC, RefObject } from "react";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { useEvalDescriptor } from "../../../state/hooks";
import { RenderedText } from "../../content/RenderedText";
import { SampleScoresGrid } from "./SampleScoresGrid";
import styles from "./SampleScoresView.module.css";

interface SampleScoresViewProps {
  sample?: EvalSample;
  className?: string | string[];
  scrollRef: RefObject<HTMLDivElement | null>;
}

export const SampleScoresView: FC<SampleScoresViewProps> = ({
  sample,
  className,
  scrollRef,
}) => {
  const evalDescriptor = useEvalDescriptor();
  if (!evalDescriptor) {
    return undefined;
  }
  if (!sample) {
    return undefined;
  }

  const scoreInput = inputString(sample.input);
  if (sample.choices && sample.choices.length > 0) {
    scoreInput.push("");
    scoreInput.push(
      ...sample.choices.map((choice, index) => {
        return `${String.fromCharCode(65 + index)}) ${choice}`;
      }),
    );
  }

  return (
    <div
      className={clsx(
        "container-fluid",
        className,
        "font-size-base",
        styles.container,
      )}
    >
      <Card className={clsx(styles.scoreCard)}>
        <CardBody>
          <div
            className={clsx(
              "text-size-small",
              "text-style-label",
              "text-style-secondary",
            )}
          >
            Input
          </div>
          <ExpandablePanel
            lines={10}
            id={`sample-score-${sample.id}-${sample.epoch}`}
            collapse={true}
          >
            <RenderedText
              markdown={scoreInput.join("\n")}
              className={clsx(styles.wordBreak, "text-size-base")}
            />
          </ExpandablePanel>
          <SampleScoresGrid
            evalSample={sample}
            className={clsx(styles.scores)}
            scrollRef={scrollRef}
          />
        </CardBody>
      </Card>
    </div>
  );
};
