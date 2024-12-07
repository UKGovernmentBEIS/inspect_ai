import { html } from "htm/preact";
import { isNumeric } from "../../utils/Type.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";
import {
  kEpochAscVal,
  kEpochDescVal,
  kSampleAscVal,
  kSampleDescVal,
  kScoreAscVal,
  kScoreDescVal,
} from "../../constants.mjs";

export const SortFilter = ({ sampleDescriptor, sort, setSort, epochs }) => {
  const options = [
    { label: "sample asc", val: kSampleAscVal },
    { label: "sample desc", val: kSampleDescVal },
  ];
  if (epochs) {
    options.push({
      label: "epoch asc",
      val: kEpochAscVal,
    });
    options.push({
      label: "epoch desc",
      val: kEpochDescVal,
    });
  }
  if (sampleDescriptor?.scoreDescriptor?.compare) {
    options.push({
      label: "score asc",
      val: kScoreAscVal,
    });
    options.push({
      label: "score desc",
      val: kScoreDescVal,
    });
  }
  return html`
    <div style=${{ display: "flex" }}>
      <span
        class="sort-filter-label"
        style=${{
          alignSelf: "center",
          fontSize: FontSize.smaller,
          ...TextStyle.label,
          ...TextStyle.secondary,
          marginRight: "0.3em",
          marginLeft: "0.2em",
        }}
        >Sort:</span
      >
      <select
        class="form-select form-select-sm"
        aria-label=".sort-filter-label"
        style=${{ fontSize: FontSize.smaller }}
        value=${sort}
        onChange=${(e) => {
          setSort(e.target.value);
        }}
      >
        ${options.map((option) => {
          return html`<option value="${option.val}">${option.label}</option>`;
        })}
      </select>
    </div>
  `;
};

export const byEpoch = (sort) => {
  return sort === kEpochAscVal || sort === kEpochDescVal;
};

export const bySample = (sort) => {
  return sort === kSampleAscVal || sort === kSampleDescVal;
};

const sortId = (a, b) => {
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
 *
 * @param {string} sort - The sort direction
 * @param {import("../../api/Types.mjs").SampleSummary[]} samples - The samples
 * @param {import("../SamplesDescriptor.mjs").SamplesDescriptor} samplesDescriptor - The samples descriptor
 * @returns {{ sorted: import("../../api/Types.mjs").SampleSummary[], order: 'asc' | 'desc' }} An object with sorted samples and the sort order.
 */
export const sortSamples = (sort, samples, samplesDescriptor) => {
  const sortedSamples = samples.sort((a, b) => {
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

      case kScoreAscVal:
        return samplesDescriptor.scoreDescriptor.compare(
          samplesDescriptor.selectedScore(a).value,
          samplesDescriptor.selectedScore(b).value,
        );
      case kScoreDescVal:
        return samplesDescriptor.scoreDescriptor.compare(
          samplesDescriptor.selectedScore(b).value,
          samplesDescriptor.selectedScore(a).value,
        );
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
