import { html } from "htm/preact";
import { isNumeric } from "../../utils/Type.mjs";

const kSampleAscVal = "sample-asc";
const kSampleDescVal = "sample-desc";
const kEpochAscVal = "epoch-asc";
const kEpochDescVal = "epoch-desc";
const kScoreAscVal = "score-asc";
const kScoreDescVal = "score-desc";

export const kDefaultSort = kSampleAscVal;

export const SortFilter = ({ sort, setSort, epochs }) => {
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
  options.push({
    label: "score asc",
    val: kScoreAscVal,
  });
  options.push({
    label: "score desc",
    val: kScoreDescVal,
  });
  return html`
    <div style=${{ display: "flex" }}>
      <span
        class="epoch-filter-label"
        style=${{ alignSelf: "center", marginRight: "0.5em" }}
        >Sort:</span
      >
      <select
        class="form-select form-select-sm"
        aria-label=".epoch-filter-label"
        style=${{ fontSize: "0.7rem" }}
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
          return a.id.localeCompare(b.id);
        }
      case kSampleDescVal:
        if (isNumeric(a.id) && isNumeric(b.id)) {
          return b.id - a.id;
        } else {
          return b.id.localeCompare(a.id);
        }
      case kEpochAscVal:
        return a.epoch - b.epoch;
      case kEpochDescVal:
        return b.epoch - a.epoch;
      case kScoreAscVal:
        return sampleDescriptor.scoreDescriptor.compare(
          a.score.value,
          b.score.value,
        );
      case kScoreDescVal:
        return sampleDescriptor.scoreDescriptor.compare(
          b.score.value,
          a.score.value,
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
