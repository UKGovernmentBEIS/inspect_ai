import clsx from "clsx";
import { ChangeEvent, FC, useCallback } from "react";
import { ScoreLabel } from "../../../app/types";
import { SampleSummary } from "../../../client/api/types";
import {
  kEpochAscVal,
  kEpochDescVal,
  kSampleAscVal,
  kSampleDescVal,
  kScoreAscVal,
  kScoreDescVal,
} from "../../../constants";
import { isNumeric } from "../../../utils/type";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";
import styles from "./SortFilter.module.css";

interface SortFilterProps {
  sort: string;
  setSort: (sort: string) => void;
  epochs: number;
}

export const SortFilter: FC<SortFilterProps> = ({ sort, setSort, epochs }) => {
  const options = [
    { label: "sample asc", val: kSampleAscVal },
    { label: "sample desc", val: kSampleDescVal },
  ];
  if (epochs > 1) {
    options.push({
      label: "epoch asc",
      val: kEpochAscVal,
    });
    options.push({
      label: "epoch desc",
      val: kEpochDescVal,
    });
  }
  options.push({
    label: "score asc",
    val: kScoreAscVal,
  });
  options.push({
    label: "score desc",
    val: kScoreDescVal,
  });

  const handleChange = useCallback(
    (e: ChangeEvent<HTMLSelectElement>) => {
      const sel = e.target as HTMLSelectElement;
      setSort(sel.value);
    },
    [setSort],
  );

  return (
    <div className={styles.flex}>
      <span
        className={clsx(
          "sort-filter-label",
          "text-size-smaller",
          "text-style-label",
          "text-style-secondary",
          styles.label,
        )}
      >
        Sort:
      </span>
      <select
        className={clsx("form-select", "form-select-sm", "text-size-smaller")}
        aria-label=".sort-filter-label"
        value={sort}
        onChange={handleChange}
      >
        {options.map((option) => {
          return (
            <option key={option.val} value={option.val}>
              {option.label}
            </option>
          );
        })}
      </select>
    </div>
  );
};

export const byEpoch = (sort: string) => {
  return sort === kEpochAscVal || sort === kEpochDescVal;
};

export const bySample = (sort: string) => {
  return sort === kSampleAscVal || sort === kSampleDescVal;
};

const sortId = (a: SampleSummary, b: SampleSummary) => {
  if (isNumeric(a.id) && isNumeric(b.id)) {
    return Number(a.id) - Number(b.id);
  } else {
    // Note that if there are mixed types of ids (e.g. a string
    // and a number), we need to be sure we're working with strings
    // to performan the comparison
    return String(a.id).localeCompare(String(b.id));
  }
};

/**
 * Sorts a list of samples
 */
export const sortSamples = (
  sort: string,
  samples: SampleSummary[],
  samplesDescriptor: SamplesDescriptor,
  score?: ScoreLabel,
): SampleSummary[] => {
  const sortedSamples = samples.sort((a: SampleSummary, b: SampleSummary) => {
    const scoreDescriptor = score
      ? samplesDescriptor.evalDescriptor.scoreDescriptor(score)
      : undefined;

    switch (sort) {
      case kSampleAscVal: {
        const result = sortId(a, b);
        if (result !== 0) {
          return result;
        } else {
          return a.epoch - b.epoch;
        }
      }
      case kSampleDescVal: {
        const result = sortId(b, a);
        if (result !== 0) {
          return result;
        } else {
          return a.epoch - b.epoch;
        }
      }
      case kEpochAscVal: {
        const result = a.epoch - b.epoch;
        if (result !== 0) {
          return result;
        } else {
          return sortId(a, b);
        }
      }
      case kEpochDescVal: {
        const result = b.epoch - a.epoch;
        if (result !== 0) {
          return result;
        } else {
          return sortId(b, a);
        }
      }

      case kScoreAscVal: {
        const aScore = samplesDescriptor.evalDescriptor.score(a, score);
        const bScore = samplesDescriptor.evalDescriptor.score(b, score);
        if (
          aScore === undefined ||
          bScore === undefined ||
          scoreDescriptor === undefined
        ) {
          return 0;
        }
        return scoreDescriptor?.compare(aScore, bScore);
      }
      case kScoreDescVal: {
        const aScore = samplesDescriptor.evalDescriptor.score(a, score);
        const bScore = samplesDescriptor.evalDescriptor.score(b, score);
        if (
          aScore === undefined ||
          bScore === undefined ||
          scoreDescriptor == undefined
        ) {
          return 0;
        }

        return scoreDescriptor?.compare(bScore, aScore);
      }
      default:
        return 0;
    }
  });
  return sortedSamples;
};
