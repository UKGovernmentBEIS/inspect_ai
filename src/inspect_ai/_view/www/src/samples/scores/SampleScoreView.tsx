import clsx from "clsx";
import { Card, CardBody, CardHeader } from "../../components/Card";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { MetaDataGrid } from "../../metadata/MetaDataGrid";
import { EvalSample } from "../../types/log";
import { arrayToString, inputString } from "../../utils/format";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";
import { SampleScores } from "./SampleScores";

import { SampleSummary } from "../../api/types";
import styles from "./SampleScoreView.module.css";

interface SampleScoreViewProps {
  sample: EvalSample;
  sampleDescriptor: SamplesDescriptor;
  scorer: string;
  className?: string | string[];
}

export const SampleScoreView: React.FC<SampleScoreViewProps> = ({
  sample,
  sampleDescriptor,
  className,
  scorer,
}) => {
  if (!sampleDescriptor) {
    return null;
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

  const scorerDescriptor = sampleDescriptor.evalDescriptor.scorerDescriptor(
    sample,
    { scorer, name: scorer },
  );
  const explanation = scorerDescriptor.explanation() || "(No Explanation)";
  const answer = scorerDescriptor.answer();
  const metadata = scorerDescriptor.metadata();

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
        <CardHeader label="Score" />
        <CardBody>
          <div>
            <div
              className={clsx(
                styles.label,
                "text-style-label",
                "text-style-secondary",
              )}
            >
              Input
            </div>
            <div>
              <MarkdownDiv
                markdown={scoreInput.join("\n")}
                className={styles.wordBreak}
              />
            </div>
          </div>

          <table className={clsx("table", styles.scoreTable)}>
            <thead className={styles.bottomBorder}>
              <tr>
                <th
                  className={clsx(
                    styles.label,
                    "text-style-label",
                    "text-style-secondary",
                  )}
                >
                  Target
                </th>
                <th
                  className={clsx(
                    styles.label,
                    "text-style-label",
                    "text-style-secondary",
                  )}
                >
                  Answer
                </th>
                <th
                  className={clsx(
                    styles.label,
                    "text-style-label",
                    "text-style-secondary",
                    styles.headerScore,
                  )}
                >
                  Score
                </th>
              </tr>
            </thead>
            <tbody className={styles.bottomBorder}>
              <tr>
                <td className={styles.targetValue}>
                  <MarkdownDiv
                    markdown={arrayToString(
                      arrayToString(sample?.target || "none"),
                    )}
                    className={clsx("no-last-para-padding", styles.noLeft)}
                  />
                </td>
                <td className={clsx(styles.answerValue)}>
                  <MarkdownDiv
                    className={clsx("no-last-para-padding", styles.noLeft)}
                    markdown={answer}
                  />
                </td>
                <td className={clsx(styles.scoreValue)}>
                  <SampleScores
                    sample={sample as any as SampleSummary}
                    sampleDescriptor={sampleDescriptor}
                    scorer={scorer}
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </CardBody>
      </Card>
      {explanation && explanation !== answer ? (
        <Card>
          <CardHeader label="Explanation" />
          <CardBody>
            <MarkdownDiv
              markdown={arrayToString(explanation)}
              className={clsx("no-last-para-padding", styles.noLeft)}
            />
          </CardBody>
        </Card>
      ) : (
        ""
      )}
      {metadata && Object.keys(metadata).length > 0 ? (
        <Card>
          <CardHeader label="Metadata" />
          <CardBody>
            <MetaDataGrid
              id="task-sample-score-metadata"
              className={clsx("tab-pane", styles.noTop)}
              entries={metadata}
            />
          </CardBody>
        </Card>
      ) : (
        ""
      )}
    </div>
  );
};
