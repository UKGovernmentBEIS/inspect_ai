import { html } from "htm/preact";
import { isNumeric } from "../../utils/Type.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

import {
  kScoreTypeCategorical,
  kScoreTypeNumeric,
  kScoreTypeObject,
  kScoreTypePassFail,
} from "../SamplesDescriptor.mjs";

export const SampleFilter = ({ descriptor, filter, filterChanged }) => {
  const filterCategory = (e) => {
    const val = e.currentTarget.value;
    if (val === "all") {
      filterChanged({
        value: undefined,
        filterFn: undefined,
      });
    } else {
      filterChanged({
        value: val,
        filterFn: (sample, value) => {
          const score = descriptor.selectedScore(sample);
          if (typeof score.value === "string") {
            return score.value.toLowerCase() === value?.toLowerCase();
          } else if (typeof score.value === "object") {
            return JSON.stringify(score.value) == value;
          } else {
            return score.value === value;
          }
        },
      });
    }
  };

  const filterInput = (e) => {
    filterChanged({
      value: e.currentTarget.value,
      filterFn: filterText(descriptor),
    });
  };

  switch (descriptor?.scoreDescriptor?.scoreType) {
    case kScoreTypePassFail: {
      const options = [{ text: "All", value: "all" }];
      options.push(
        ...descriptor.scoreDescriptor.categories.map((cat) => {
          return { text: cat.text, value: cat.val };
        }),
      );
      return html`<${SelectFilter}
        value=${filter.value || "all"}
        options=${options}
        filterFn=${filterCategory}
      />`;
    }

    case kScoreTypeCategorical: {
      const options = [{ text: "All", value: "all" }];
      options.push(
        ...descriptor.scoreDescriptor.categories.map((cat) => {
          return { text: cat, value: cat };
        }),
      );
      return html`<${SelectFilter}
        value=${filter.value || "all"}
        options=${options}
        filterFn=${filterCategory}
      />`;
    }

    case kScoreTypeNumeric: {
      // TODO: Create a real numeric slider control of some kind
      return html`
        <input
          type="text"
          class="form-control"
          value=${filter.value}
          placeholder="Filter Samples (score)"
          style=${{ width: "150px" }}
          onInput=${filterInput}
        />
      `;
    }

    case kScoreTypeObject: {
      if (!descriptor.scoreDescriptor.categories) {
        return "";
      }
      const options = [{ text: "All", value: "all" }];
      options.push(
        ...descriptor.scoreDescriptor.categories.map((cat) => {
          return { text: cat.text, value: cat.value };
        }),
      );

      return html`<${SelectFilter}
        value=${filter.value || "all"}
        options=${options}
        filterFn=${filterCategory}
      />`;
    }

    default: {
      return undefined;
    }
  }
};

const SelectFilter = ({ value, options, filterFn }) => {
  return html`
    <div style=${{ display: "flex" }}>
      <span
        class="sample-label"
        style=${{
          alignSelf: "center",
          fontSize: FontSize.smaller,
          ...TextStyle.label,
          ...TextStyle.secondary,
          marginRight: "0.3em",
          marginLeft: "0.2em",
        }}
        >Scores:</span
      >
      <select
        class="form-select form-select-sm"
        aria-label=".sample-label"
        style=${{ fontSize: FontSize.smaller }}
        value=${value}
        onChange=${filterFn}
      >
        ${options.map((option) => {
          return html`<option value="${option.value}">${option.text}</option>`;
        })}
      </select>
    </div>
  `;
};

const filterText = (descriptor) => {
  return (sample, value) => {
    const score = descriptor.selectedScore(sample);
    if (!value) {
      return true;
    } else {
      if (isNumeric(value)) {
        if (typeof score.value === "number") {
          return score.value === Number(value);
        } else {
          return Number(score.value) === Number(value);
        }
      } else {
        const filters = [
          {
            prefix: ">=",
            fn: (score, val) => {
              return score >= val;
            },
          },
          {
            prefix: "<=",
            fn: (score, val) => {
              return score <= val;
            },
          },
          {
            prefix: ">",
            fn: (score, val) => {
              return score > val;
            },
          },
          {
            prefix: "<",
            fn: (score, val) => {
              return score < val;
            },
          },
          {
            prefix: "=",
            fn: (score, val) => {
              return score === val;
            },
          },
          {
            prefix: "!=",
            fn: (score, val) => {
              return score !== val;
            },
          },
        ];

        for (const filter of filters) {
          if (value?.startsWith(filter.prefix)) {
            const val = value.slice(filter.prefix.length).trim();
            if (!val) {
              return true;
            }

            const num = Number(val);
            return filter.fn(score.value, num);
          }
        }
        if (typeof score.value === "string") {
          return score.value.toLowerCase() === value?.toLowerCase();
        } else {
          return score.value === value;
        }
      }
    }
  };
};
