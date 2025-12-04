import { ReactNode } from "react";
import { Value2 } from "../../../@types/log";
import { ScoreLabel } from "../../../app/types";
import { BasicSampleData, SampleSummary } from "../../../client/api/types";
import { arrayToString, inputString } from "../../../utils/format";
import { errorType } from "../error/error";
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
  selectedScore: (sample: BasicSampleData) => SelectedScore | undefined;
  selectedScorerDescriptor: (
    sample: BasicSampleData,
  ) => ScorerDescriptor | undefined;
}

export const createEvalDescriptor = (
  scores: ScoreLabel[],
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
      if (typeof sample.scores[scoreLabel.scorer].value === "object") {
        return (
          sample.scores[scoreLabel.scorer].value as Record<string, Value2>
        )[scoreLabel.name];
      } else {
        return sample.scores[scoreLabel.scorer].value;
      }
    } else if (sample.scores[scoreLabel.name]) {
      return sample.scores[scoreLabel.name].value;
    } else {
      return undefined;
    }
  };

  const scoreAnswer = (
    sample: BasicSampleData,
    scorer: ScoreLabel,
  ): string | undefined => {
    if (sample && sample.scores) {
      const sampleScore = sample.scores[scorer.name];
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
    } else if (descriptor && descriptor.render) {
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
        return scoreAnswer(sample, scoreLabel) || "";
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
    scoreLabel?: ScoreLabel,
  ): SelectedScore | undefined => {
    if (!scoreLabel) {
      return undefined;
    }
    return {
      value: scoreValue(sample, scoreLabel),
      render: () => {
        return scoreRendered(sample, scoreLabel);
      },
    };
  };

  return {
    scores,
    scorerDescriptor,
    scoreDescriptor,
    score,
    scoreAnswer,
  };
};

export const createSamplesDescriptor = (
  samples: SampleSummary[],
  evalDescriptor: EvalDescriptor,
  selectedScores: ScoreLabel[],
): SamplesDescriptor | undefined => {
  const sizes = samples.reduce(
    (previous, current) => {
      const text = inputString(current.input).join(" ");

      let answerLength = 0;

      if (selectedScores.length > 0) {
        selectedScores.forEach((scoreLabel, index) => {
          const score = evalDescriptor.score(current, scoreLabel);
          const scoreValue = score?.value;
          const scoreText = scoreValue
            ? String(scoreValue)
            : current.error
              ? errorType(current.error)
              : "";

          const currentSize = Math.max(
            scoreText.length,
            scoreLabel.name.length,
          );
          previous.scores[index] = Math.max(
            previous.scores[index] || 0,
            currentSize,
          );
        });

        answerLength =
          evalDescriptor.scoreAnswer(current, selectedScores[0])?.length || 0;
      } else {
        previous.scores = [];
        previous.scores[0] = 3;
      }

      previous.input = Math.min(Math.max(previous.input, text.length), 200);
      previous.target = Math.min(
        Math.max(previous.target, arrayToString(current.target).length),
        300,
      );
      previous.answer = Math.min(Math.max(previous.answer, answerLength), 300);
      previous.limit = Math.min(
        Math.max(previous.limit, current.limit ? current.limit.length : 0),
        50,
      );
      previous.retries = Math.min(
        Math.max(
          previous.retries,
          current.retries ? String(current.retries).length : 0,
        ),
        50,
      );
      previous.id = Math.min(
        Math.max(previous.id, String(current.id).length),
        10,
      );

      return previous;
    },
    {
      input: 0,
      target: 0,
      answer: 0,
      limit: 0,
      retries: 0,
      id: 0,
      scores: [] as number[],
    },
  );
  // normalize to base 1

  const totalScoreSizes = sizes.scores.reduce((sum, size) => sum + size, 0);
  const normalizedScoreSizes =
    totalScoreSizes > 0
      ? sizes.scores.map((size) => Math.round((size / totalScoreSizes) * 30))
      : [];
  const maxSizes = {
    input: Math.min(sizes.input, 300),
    target: Math.min(sizes.target, 300),
    answer: Math.min(sizes.answer, 300),
    limit: Math.min(sizes.limit, 50),
    retries: Math.min(sizes.retries, 50),
    id: Math.min(sizes.id, 10),
    score: normalizedScoreSizes,
  };
  const base =
    maxSizes.input +
      maxSizes.target +
      maxSizes.answer +
      maxSizes.limit +
      maxSizes.retries +
      maxSizes.id +
      maxSizes.score.reduce((sum, size) => {
        return sum + size;
      }, 0) || 1;

  const inputNormalized = maxSizes.input / base;
  const targetNormalized =
    maxSizes.target / base > 0
      ? Math.max(maxSizes.target / base, inputNormalized / 10)
      : 0;
  const answerNormalized =
    maxSizes.answer / base > 0
      ? Math.max(maxSizes.answer / base, inputNormalized / 10)
      : 0;

  const messageShape = {
    raw: sizes,
    normalized: {
      input: inputNormalized,
      target: targetNormalized,
      answer: answerNormalized,
      limit: maxSizes.limit / base,
      retries: maxSizes.retries / base,
      id: maxSizes.id / base,
      scores: maxSizes.score.map((val) => {
        return val / base;
      }),
    },
  };

  const firstSelectedScore = selectedScores?.[0];

  return {
    evalDescriptor,
    messageShape,
    selectedScore: (sample) =>
      firstSelectedScore
        ? evalDescriptor.score(sample, firstSelectedScore)
        : undefined,
    selectedScorerDescriptor: (sample) =>
      firstSelectedScore
        ? evalDescriptor.scorerDescriptor(sample, firstSelectedScore)
        : undefined,
  };
};

const scoreLabelKey = (scoreLabel: ScoreLabel) => {
  return `${scoreLabel?.scorer}.${scoreLabel.name}`;
};
