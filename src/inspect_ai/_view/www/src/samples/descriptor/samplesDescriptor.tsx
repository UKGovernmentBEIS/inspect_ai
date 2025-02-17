import { ReactNode } from "react";
import { BasicSampleData, SampleSummary } from "../../api/types";
import { ScoreLabel } from "../../types";
import { Value2 } from "../../types/log";
import { arrayToString, inputString } from "../../utils/format";
import { getScoreDescriptorForValues } from "./score/ScoreDescriptor";
import {
  EvalDescriptor,
  MessageShape,
  ScoreDescriptor,
  ScorerDescriptor,
  SelectedScore,
} from "./types";

export interface SamplesDescriptor {
  evalDescriptor: EvalDescriptor;
  messageShape: MessageShape;
  selectedScoreDescriptor?: ScoreDescriptor;
  selectedScore: (sample: BasicSampleData) => SelectedScore | undefined;
  selectedScorerDescriptor: (sample: BasicSampleData) => ScorerDescriptor;
}

export const createEvalDescriptor = (
  scores: ScoreLabel[],
  epochs: number,
  samples?: SampleSummary[],
): EvalDescriptor | undefined => {
  if (!samples) {
    return undefined;
  }

  const scoreValue = (
    sample: BasicSampleData,
    scoreLabel?: ScoreLabel,
  ): Value2 | undefined => {
    // no scores, no value
    if (
      sample.scores === null ||
      Object.keys(sample.scores).length === 0 ||
      !scoreLabel
    ) {
      return undefined;
    }

    if (
      scoreLabel.scorer !== scoreLabel.name &&
      sample.scores[scoreLabel.scorer] &&
      sample.scores[scoreLabel.scorer].value
    ) {
      return sample.scores[scoreLabel.scorer].value;
    } else if (sample.scores[scoreLabel.name]) {
      return sample.scores[scoreLabel.name].value;
    } else {
      return undefined;
    }
  };

  const scoreAnswer = (
    sample: BasicSampleData,
    scorer: string,
  ): string | undefined => {
    if (sample && sample.scores) {
      const sampleScore = sample.scores[scorer];
      if (sampleScore && sampleScore.answer) {
        return sampleScore.answer;
      }
    } else {
      return undefined;
    }
  };

  const scoreExplanation = (
    sample: BasicSampleData,
    scorer: string,
  ): string | undefined => {
    if (sample && sample.scores) {
      const sampleScore = sample.scores[scorer];
      if (sampleScore && sampleScore.explanation) {
        return sampleScore.explanation;
      }
    }
    return undefined;
  };

  // Retrieve the metadata for a sample
  const scoreMetadata = (
    sample: BasicSampleData,
    scorer: string,
  ): Record<string, unknown> | undefined => {
    if (sample && sample.scores) {
      const sampleScore = sample.scores[scorer];
      if (sampleScore && sampleScore.metadata) {
        return sampleScore.metadata;
      }
    }
    return undefined;
  };

  const scoreDescriptorMap: Record<string, ScoreDescriptor> = {};
  for (const scoreLabel of scores) {
    const uniqScoreValues = [
      ...new Set(
        samples
          .filter((sample) => !!sample.scores)
          .filter((sample) => {
            // There is no selected scorer, so include this value
            if (!scoreLabel) {
              return true;
            }

            // There are no scores, so exclude this
            if (!sample.scores) {
              return false;
            }

            if (scoreLabel.scorer !== scoreLabel.name) {
              return (
                Object.keys(sample.scores).includes(scoreLabel.scorer) &&
                Object.keys(sample.scores[scoreLabel.scorer].value).includes(
                  scoreLabel.name,
                )
              );
            } else {
              return Object.keys(sample.scores).includes(scoreLabel.name);
            }
          })
          .map((sample) => {
            return scoreValue(sample, scoreLabel);
          })
          .filter((value) => {
            return value !== null;
          })
          .filter((value) => {
            return value !== undefined;
          }),
      ),
    ];
    const uniqScoreTypes = [
      ...new Set(uniqScoreValues.map((scoreValue) => typeof scoreValue)),
    ];

    const scoreDescriptor = getScoreDescriptorForValues(
      uniqScoreValues,
      uniqScoreTypes,
    );
    if (scoreDescriptor) {
      scoreDescriptorMap[scoreLabelKey(scoreLabel)] = scoreDescriptor;
    }
  }

  const scoreDescriptor = (scoreLabel: ScoreLabel): ScoreDescriptor => {
    return scoreDescriptorMap[scoreLabelKey(scoreLabel)];
  };

  const scoreRendered = (
    sample: BasicSampleData,
    scoreLabel: ScoreLabel,
  ): ReactNode => {
    const descriptor = scoreDescriptor(scoreLabel);
    const score = scoreValue(sample, scoreLabel);
    if (score === null) {
      return "null";
    } else if (score === undefined) {
      return "";
    } else if (score && descriptor && descriptor.render) {
      return descriptor.render(score);
    } else {
      return <span>{String(score)}</span>;
    }
  };

  const scorerDescriptor = (
    sample: BasicSampleData,
    scoreLabel: ScoreLabel,
  ): ScorerDescriptor => {
    return {
      metadata: () => {
        return scoreMetadata(sample, scoreLabel.scorer) || {};
      },
      explanation: () => {
        return scoreExplanation(sample, scoreLabel.scorer) || "";
      },
      answer: () => {
        return scoreAnswer(sample, scoreLabel.scorer) || "";
      },
      scores: () => {
        if (!sample || !sample.scores) {
          return [];
        }
        const myScoreDescriptor = scoreDescriptor(scoreLabel);
        if (!myScoreDescriptor) {
          return [];
        }

        // Make a list of all the valid score names (this is
        // used to distinguish between dictionaries that contain
        // scores that should be treated as standlone scores and
        // dictionaries that just contain random values, which is allowed)
        const scoreNames = scores.map((score) => {
          return score.name;
        });
        const sampleScorer = sample.scores[scoreLabel.scorer];
        const scoreVal = sampleScorer.value as Value2;

        if (typeof scoreVal === "object") {
          const names = Object.keys(scoreVal);

          // See if this is a dictionary of score names
          // if any of the score names match, treat it
          // as a scorer dictionary
          if (
            names.find((name) => {
              return scoreNames.includes(name);
            })
          ) {
            // Since this dictionary contains keys which are  scores
            // we actually render the individual scores
            const scores = names.map((name) => {
              return {
                name,
                rendered: () => {
                  return myScoreDescriptor.render(scoreVal);
                },
              };
            });
            return scores;
          } else {
            // Since this dictionary contains keys which are not scores
            // we just treat it like an opaque dictionary
            return [
              {
                name: scoreLabel.scorer,
                rendered: () => {
                  return myScoreDescriptor.render(scoreVal);
                },
              },
            ];
          }
        } else {
          return [
            {
              name: scoreLabel.scorer,
              rendered: () => {
                return myScoreDescriptor.render(scoreVal);
              },
            },
          ];
        }
      },
    };
  };

  const score = (
    sample: BasicSampleData,
    scoreLabel: ScoreLabel,
  ): SelectedScore => {
    return {
      value: scoreValue(sample, scoreLabel),
      render: () => {
        return scoreRendered(sample, scoreLabel);
      },
    };
  };

  return {
    epochs,
    samples,
    scores,
    scorerDescriptor,
    scoreDescriptor,
    score,
    scoreAnswer,
  };
};

export const createSamplesDescriptor = (
  evalDescriptor: EvalDescriptor,
  selectedScore: ScoreLabel,
): SamplesDescriptor | undefined => {
  // Find the total length of the value so we can compute an average
  const sizes = evalDescriptor.samples.reduce(
    (previous, current) => {
      const text = inputString(current.input).join(" ");
      const score = evalDescriptor.score(current, selectedScore);
      const scoreValue = score?.value;
      const scoreText = scoreValue
        ? String(scoreValue)
        : current.error
          ? String(current.error)
          : "";
      previous[0] = Math.min(Math.max(previous[0], text.length), 300);
      previous[1] = Math.min(
        Math.max(previous[1], arrayToString(current.target).length),
        300,
      );
      previous[2] = Math.min(
        Math.max(
          previous[2],
          evalDescriptor.scoreAnswer(current, selectedScore?.name)?.length || 0,
        ),
        300,
      );
      previous[3] = Math.min(
        Math.max(previous[3], current.limit ? current.limit.length : 0),
        50,
      );
      previous[4] = Math.min(
        Math.max(previous[4], String(current.id).length),
        10,
      );
      previous[5] = Math.min(Math.max(previous[5], scoreText.length), 30);

      return previous;
    },
    [0, 0, 0, 0, 0, 0],
  );

  // normalize to base 1
  const maxSizes = {
    input: Math.min(sizes[0], 300),
    target: Math.min(sizes[1], 300),
    answer: Math.min(sizes[2], 300),
    limit: Math.min(sizes[3], 50),
    id: Math.min(sizes[4], 10),
    score: Math.min(sizes[4], 30),
  };
  const base =
    maxSizes.input +
      maxSizes.target +
      maxSizes.answer +
      maxSizes.limit +
      maxSizes.id +
      maxSizes.score || 1;
  const messageShape = {
    raw: {
      input: sizes[0],
      target: sizes[1],
      answer: sizes[2],
      limit: sizes[3],
      id: sizes[4],
      score: sizes[5],
    },
    normalized: {
      input: maxSizes.input / base,
      target: maxSizes.target / base,
      answer: maxSizes.answer / base,
      limit: maxSizes.limit / base,
      id: maxSizes.id / base,
      score: maxSizes.score / base,
    },
  };

  return {
    evalDescriptor,
    messageShape,
    selectedScoreDescriptor: evalDescriptor.scoreDescriptor(selectedScore),
    selectedScore: (sample) => evalDescriptor.score(sample, selectedScore),
    selectedScorerDescriptor: (sample) =>
      evalDescriptor.scorerDescriptor(sample, selectedScore),
  };
};

const scoreLabelKey = (scoreLabel: ScoreLabel) => {
  return `${scoreLabel?.scorer}.${scoreLabel.name}`;
};
