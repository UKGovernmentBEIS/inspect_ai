import { html } from "htm/preact";
import { isNumeric } from "../../utils/Type.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

const kSampleAscVal = "sample-asc";
const kSampleDescVal = "sample-desc";
const kEpochAscVal = "epoch-asc";
const kEpochDescVal = "epoch-desc";
const kScoreAscVal = "score-asc";
const kScoreDescVal = "score-desc";

export const kDefaultSort = kSampleAscVal;

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

export const sort = (sort, samples, sampleDescriptor) => {
  const sorted = samples.sort((a, b) => {
    switch (sort) {
      case kSampleAscVal:
        if (isNumeric(a.id) && isNumeric(b.id)) {
          return a.id - b.id;
        } else {
          // Note that if there are mixed types of ids (e.g. a string
          // and a number), we need to be sure we're working with strings
          // to performan the comparison
          return String(a.id).localeCompare(String(b.id));
        }
      case kSampleDescVal:
        if (isNumeric(a.id) && isNumeric(b.id)) {
          return b.id - a.id;
        } else {
          // Note that if there are mixed types of ids (e.g. a string
          // and a number), we need to be sure we're working with strings
          // to performan the comparison
          return String(b.id).localeCompare(String(a.id));
        }
      case kEpochAscVal:
        return a.epoch - b.epoch;
      case kEpochDescVal:
        return b.epoch - a.epoch;
      case kScoreAscVal:
        return sampleDescriptor.scoreDescriptor.compare(
          sampleDescriptor.selectedScore(a).value,
          sampleDescriptor.selectedScore(b).value,
        );
      case kScoreDescVal:
        return sampleDescriptor.scoreDescriptor.compare(
          sampleDescriptor.selectedScore(b).value,
          sampleDescriptor.selectedScore(a).value,
        );
    }
  });
  return {
    sorted,
    order:
      sort === kSampleAscVal || sort === kEpochAscVal || sort === kScoreAscVal
        ? "asc"
        : "desc",
  };
};
