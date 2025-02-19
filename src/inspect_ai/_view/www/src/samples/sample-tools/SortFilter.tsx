import clsx from "clsx";
import { SampleSummary } from "../../api/types";
import {
  kEpochAscVal,
  kEpochDescVal,
  kSampleAscVal,
  kSampleDescVal,
  kScoreAscVal,
  kScoreDescVal,
} from "../../constants";
import { isNumeric } from "../../utils/type";
import { SamplesDescriptor } from "../descriptor/samplesDescriptor";
import styles from "./SortFilter.module.css";

interface SortFilterProps {
  sort: string;
  setSort: (sort: string) => void;
  epochs: number;
}

export const SortFilter: React.FC<SortFilterProps> = ({
  sort,
  setSort,
  epochs,
}) => {
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
        onChange={(e) => {
          const sel = e.target as HTMLSelectElement;
          setSort(sel.value);
        }}
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
): { sorted: SampleSummary[]; order: "asc" | "desc" } => {
  const sortedSamples = samples.sort((a: SampleSummary, b: SampleSummary) => {
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
          return sortId(a, b);
        }
      }

      case kScoreAscVal: {
        const aScore = samplesDescriptor.selectedScore(a);
        const bScore = samplesDescriptor.selectedScore(b);
        if (
          aScore === undefined ||
          bScore === undefined ||
          samplesDescriptor.selectedScoreDescriptor == undefined
        ) {
          return 0;
        }
        return samplesDescriptor.selectedScoreDescriptor.compare(
          aScore,
          bScore,
        );
      }
      case kScoreDescVal: {
        const aScore = samplesDescriptor.selectedScore(a);
        const bScore = samplesDescriptor.selectedScore(b);
        if (
          aScore === undefined ||
          bScore === undefined ||
          samplesDescriptor.selectedScoreDescriptor == undefined
        ) {
          return 0;
        }

        return samplesDescriptor.selectedScoreDescriptor.compare(
          aScore,
          bScore,
        );
      }
      default:
        return 0;
    }
  });
  return {
    sorted: sortedSamples,
    order:
      sort === kSampleAscVal || sort === kEpochAscVal || sort === kScoreAscVal
        ? "asc"
        : "desc",
  };
};
