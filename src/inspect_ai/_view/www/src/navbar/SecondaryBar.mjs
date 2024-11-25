import { html } from "htm/preact";
import { useState } from "preact/hooks";

import { LabeledValue } from "../components/LabeledValue.mjs";
import { formatDataset, formatDuration } from "../utils/Format.mjs";
import { ExpandablePanel } from "../components/ExpandablePanel.mjs";
import { scoreFilterItems } from "../samples/tools/filters.mjs";

/**
 * Renders the Navbar
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("../types/log").EvalSpec} [props.evalSpec] - The EvalSpec
 * @param {import("../types/log").EvalPlan} [props.evalPlan] - The EvalSpec
 * @param {import("../types/log").EvalResults} [props.evalResults] - The EvalResults
 * @param {import("../types/log").EvalStats} [props.evalStats] - The EvalStats
 * @param {import("../api/Types.mjs").SampleSummary[]} [props.samples] - the samples
 * @param {import("../samples/SamplesDescriptor.mjs").EvalDescriptor} [props.evalDescriptor] - The EvalDescriptor
 * @param {(fragment: string) => void} props.addToFilterExpression - add to the current filter expression
 * @param {string} [props.status] - the status
 * @param {Map<string, string>} [props.style] - is this off canvas
 *
 * @returns {import("preact").JSX.Element | string} The TranscriptView component.
 */
export const SecondaryBar = ({
  evalSpec,
  evalPlan,
  evalResults,
  evalStats,
  samples,
  evalDescriptor,
  addToFilterExpression,
  status,
  style,
}) => {
  if (!evalSpec || status !== "success") {
    return "";
  }

  const staticColStyle = {
    flexShrink: "0",
  };

  const epochs = evalSpec.config.epochs || 1;
  const hyperparameters = {
    ...evalPlan?.config,
    ...evalSpec.task_args,
  };

  const hasConfig = Object.keys(hyperparameters).length > 0;

  const values = [];

  values.push({
    size: "minmax(12%, auto)",
    value: html`<${LabeledValue} label="Dataset" style=${staticColStyle}>
    <${DatasetSummary}
      dataset=${evalSpec.dataset}
      samples=${samples}
      epochs=${epochs} />
  </${LabeledValue}>
`,
  });

  if (hasConfig) {
    values.push({
      size: "minmax(12%, auto)",
      value: html`<${LabeledValue} label="Config" style=${{ justifySelf: "center" }}>
      <${ParamSummary} params=${hyperparameters}/>
    </${LabeledValue}>`,
    });
  }

  const totalDuration = formatDuration(
    new Date(evalStats.started_at),
    new Date(evalStats.completed_at),
  );
  values.push({
    size: "minmax(12%, auto)",
    value: html`
      <${LabeledValue} label="Duration" style=${{ justifySelf: "center" }}>
        ${totalDuration}
      </${LabeledValue}>`,
  });

  const label = evalResults?.scores.length > 1 ? "Scorers" : "Scorer";
  values.push({
    size: "minmax(12%, auto)",
    value: html`<${LabeledValue} label="${label}" style=${staticColStyle} style=${{ justifySelf: "right" }}>
    <${ScorerSummary}
      evalDescriptor=${evalDescriptor}
      addToFilterExpression=${addToFilterExpression} />
  </${LabeledValue}>`,
  });

  return html`
    <${ExpandablePanel} style=${{ margin: "0", ...style }} collapse=${true} lines=${4}>
    <div
      style=${{
        margin: "0",
        padding: "0.2em 1em 0.2em 1em",
        display: "grid",
        gridColumnGap: "1em",
        borderTop: "1px solid var(--bs-border-color)",
        gridTemplateColumns: `${values
          .map((val) => {
            return val.size;
          })
          .join(" ")}`,
      }}
    >
      ${values.map((val) => {
        return val.value;
      })}
    </div>
    </${ExpandablePanel}>
  `;
};

const DatasetSummary = ({ dataset, samples, epochs, style }) => {
  if (!dataset) {
    return "";
  }

  return html`
    <div style=${style}>
      ${dataset.name}${samples?.length
        ? html`${formatDataset(dataset.name, samples.length, epochs)}`
        : ""}
    </div>
  `;
};

const FilterableItem = ({
  item,
  index,
  openSuggestionIndex,
  setOpenSuggestionIndex,
  addToFilterExpression,
}) => {
  const handleClick = () => {
    if (item.suggestions.length === 0) {
      addToFilterExpression(item.canonicalName);
    } else {
      setOpenSuggestionIndex(openSuggestionIndex === index ? null : index);
    }
  };

  const handleSuggestionClick = (suggestion) => {
    addToFilterExpression(suggestion);
    setOpenSuggestionIndex(null);
  };

  /** @param {HTMLElement} el */
  const popupRef = (el) => {
    if (el && openSuggestionIndex === index) {
      const rect = el.previousElementSibling.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const popupWidth = el.offsetWidth;
      const finalLeft =
        rect.left + popupWidth > viewportWidth
          ? rect.right - popupWidth
          : rect.left;
      el.style.setProperty("--popup-left", `${finalLeft}px`);
      el.style.setProperty("--popup-top", `${rect.bottom + 4}px`);
    }
  };

  return html`
    <div
      class="filterable-item"
      style=${{ display: "inline-block", position: "static" }}
    >
      <a
        class="filter-link"
        style=${{
          color: "var(--bs-body-color)",
          textDecoration: "underline",
          cursor: "pointer",
        }}
        title=${item.tooltip}
        onclick=${handleClick}
      >
        ${item.canonicalName}
      </a>
      ${item.suggestions.length > 0 &&
      // Use fixed position to avoid being clipped by `ExpandablePanel`.
      html`
        <div
          class="suggestions-popup"
          style=${{
            position: "fixed",
            left: "var(--popup-left, 0)",
            top: "var(--popup-top, 0)",
            backgroundColor: "var(--bs-body-bg)",
            border: "1px solid var(--bs-border-color)",
            borderRadius: "4px",
            padding: "0.25rem 0",
            zIndex: 1000,
            display: openSuggestionIndex === index ? "block" : "none",
            boxShadow: "0 4px 8px rgba(0, 0, 0, 0.1)",
          }}
          ref=${popupRef}
        >
          ${item.suggestions.map(
            (suggestion) => html`
              <div
                class="custom-dropdown-item"
                style=${{ padding: "0.25rem 1rem", cursor: "pointer" }}
                onclick=${() => handleSuggestionClick(suggestion)}
              >
                ${suggestion}
              </div>
            `,
          )}
        </div>
      `}
    </div>
  `;
};

const ScorerSummary = ({ evalDescriptor, addToFilterExpression }) => {
  if (!evalDescriptor) {
    return "";
  }

  const items = scoreFilterItems(evalDescriptor);
  const [openSuggestionIndex, setOpenSuggestionIndex] = useState(null);

  return html`
    <span style=${{ position: "relative" }}>
      ${Array.from(items).map(
        (item, index) => html`
          ${index > 0 ? ", " : ""}
          ${item.isFilterable
            ? html`<${FilterableItem}
                item=${item}
                index=${index}
                openSuggestionIndex=${openSuggestionIndex}
                setOpenSuggestionIndex=${setOpenSuggestionIndex}
                addToFilterExpression=${addToFilterExpression}
              />`
            : html`<span title=${item.tooltip}>${item.canonicalName}</span>`}
        `,
      )}
    </span>
  `;
};

/**
 * A component that displays a summary of parameters.
 *
 * @param {Object} props - The component props.
 * @param {Record<string, any>} props.params - An object containing key-value pairs representing parameters.
 * @returns {import("preact").JSX.Element | string} The component.
 */
const ParamSummary = ({ params }) => {
  if (!params) {
    return "";
  }
  const paraValues = Object.keys(params).map((key) => {
    const val = params[key];
    if (Array.isArray(val) || typeof val === "object") {
      return `${key}: ${JSON.stringify(val)}`;
    } else {
      return `${key}: ${val}`;
    }
  });
  if (paraValues.length > 0) {
    return html`<code style=${{ padding: 0, color: "var(--bs-body-color)" }}
      >${paraValues.join(", ")}</code
    >`;
  } else {
    return "";
  }
};
