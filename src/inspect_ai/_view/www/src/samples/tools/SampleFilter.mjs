import { html } from "htm/preact";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

import {
  kScoreTypeCategorical,
  kScoreTypeNumeric,
  kScoreTypeObject,
  kScoreTypePassFail,
} from "../../constants.mjs";

/**
 * Renders the Sample Filter Control
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("../SamplesDescriptor.mjs").SamplesDescriptor} props.descriptor - The sample descriptor
 * @param {(filter: import("../../Types.mjs").ScoreFilter) => void} props.filterChanged - Filter changed function
 * @param {import("../../Types.mjs").ScoreFilter} props.filter - Capabilities of the application host
 * @returns {import("preact").JSX.Element | string} The TranscriptView component.
 */
export const SampleFilter = ({ descriptor, filter, filterChanged }) => {
  const updateCategoryValue = (e) => {
    const val = e.currentTarget.value;
    if (val === "all") {
      filterChanged({});
    } else {
      filterChanged({
        value: val,
        type: kScoreTypeCategorical,
      });
    }
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
        onChange=${updateCategoryValue}
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
        onChange=${updateCategoryValue}
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
          onInput=${(e) => {
            filterChanged({
              value: e.currentTarget.value,
              type: kScoreTypeNumeric,
            });
          }}
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
        onChange=${updateCategoryValue}
      />`;
    }

    default: {
      return undefined;
    }
  }
};

const SelectFilter = ({ value, options, onChange }) => {
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
        onChange=${onChange}
      >
        ${options.map((option) => {
          return html`<option value="${option.value}">${option.text}</option>`;
        })}
      </select>
    </div>
  `;
};
