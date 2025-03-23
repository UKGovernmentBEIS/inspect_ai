import clsx from "clsx";
import { Card, CardBody, CardHeader } from "../../components/Card";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { EvalSample } from "../../types/log";
import { inputString } from "../../utils/format";

import { FC } from "react";
import ExpandablePanel from "../../components/ExpandablePanel";
import { useEvalDescriptor } from "../../state/hooks";
import { SampleScoresGrid } from "./SampleScoresGrid";
import styles from "./SampleScoresView.module.css";

interface SampleScoresViewProps {
  sample?: EvalSample;
  className?: string | string[];
}

export const SampleScoresView: FC<SampleScoresViewProps> = ({
  sample,
  className,
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
      <Card>
        <CardHeader label="Input" />
        <CardBody>
          <ExpandablePanel
            lines={10}
            id={`sample-score-${sample.id}-${sample.epoch}`}
            collapse={true}
          >
            <MarkdownDiv
              markdown={scoreInput.join("\n")}
              className={clsx(styles.wordBreak, "text-size-base")}
            />
          </ExpandablePanel>
        </CardBody>
      </Card>
      <Card className={clsx(styles.scoreCard)}>
        <CardBody>
          <SampleScoresGrid evalSample={sample} />
        </CardBody>
      </Card>
    </div>
  );
};
