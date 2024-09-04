//@ts-check
import { html } from "htm/preact";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { formatNumber, formatTime } from "../utils/Format.mjs";
import { Card, CardHeader, CardBody } from "../components/Card.mjs";
import { MetaDataView } from "../components/MetaDataView.mjs";
import { ModelTokenTable } from "./ModelTokenTable.mjs";

const kUsageCardBodyId = "usage-card-body";

/**
 * Renders the UsageCard component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("../types/log").EvalStats} props.stats - The identifier for this view
 * @param {Object} props.context - The
 * @returns {import("preact").JSX.Element | string} The UsageCard component.
 */
export const UsageCard = ({ stats, context }) => {
  if (!stats) {
    return "";
  }

  const totalDuration = duration(stats);
  const usageMetadataStyle = {
    fontSize: FontSize.smaller,
  };

  return html`

    <${Card}>
      <${CardHeader} icon=${ApplicationIcons.usage} label="Usage"/>
      <${CardBody} id=${kUsageCardBodyId} style=${{
        paddingTop: "0",
        paddingBottom: "0",
        borderTop: "solid var(--bs-border-color) 1px",
      }}>
        <div style=${{
          paddingTop: "0",
          paddingBottom: "1em",
          marginLeft: "0",
          display: "flex",
        }}>

          <div style=${{ flex: "1 1 40%", marginRight: "1em" }}>
          <div style=${{ marginTop: "1em", fontSize: FontSize.smaller, ...TextStyle.label, ...TextStyle.secondary }}>Duration</div>
          <${MetaDataView}
            entries="${{
              ["Start"]: new Date(stats.started_at).toLocaleString(),
              ["End"]: new Date(stats.completed_at).toLocaleString(),
              ["Duration"]: totalDuration,
            }}"
            tableOptions="borderless,sm"
            context=${context}
            style=${usageMetadataStyle}
          />
          </div>

          <div style=${{ flex: "1 1 60%" }}>
            <${ModelTokenTable} model_usage=${stats.model_usage}/>
          </div>
        </div>
      </${CardBody}>
    </${Card}>
  `;
};

/**
 * Renders the ModelUsagePanel component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {import("../types/log").ModelUsage1} props.usage - The identifier for this view
 * @param {Object} props.context - The
 * @returns {import("preact").JSX.Element | string} The ModelUsagePanel component.
 */
export const ModelUsagePanel = ({ usage }) => {
  if (!usage) {
    return "";
  }

  const rows = [
    {
      label: "input",
      value: usage.input_tokens,
      secondary: false,
    },
  ];

  if (usage.input_tokens_cache_read) {
    rows.push({
      label: "cache_read",
      value: usage.input_tokens_cache_read,
      secondary: true,
    });
  }

  if (usage.input_tokens_cache_write) {
    rows.push({
      label: "cache_write",
      value: usage.input_tokens_cache_write,
      secondary: true,
    });
  }

  rows.push({
    label: "Output",
    value: usage.output_tokens,
    secondary: false,
    bordered: true,
  });

  rows.push({
    label: "---",
    value: undefined,
    secondary: false,
  });

  rows.push({
    label: "Total",
    value: usage.total_tokens,
    secondary: false,
  });

  return html` <div
    style=${{
      display: "grid",
      gridTemplateColumns: "0 auto auto",
      columnGap: "0.5em",
      fontSize: FontSize.small,
    }}
  >
    ${rows.map((row) => {
      if (row.label === "---") {
        return html`<div
          style=${{
            gridColumn: "-1/1",
            height: "1px",
            backgroundColor: "var(--bs-light-border-subtle)",
          }}
        ></div>`;
      } else {
        return html`
          <div
            style=${{
              ...TextStyle.label,
              ...TextStyle.secondary,
              gridColumn: row.secondary ? "2" : "1/3",
            }}
          >
            ${row.label}
          </div>
          <div style=${{ gridColumn: "3" }}>${formatNumber(row.value)}</div>
        `;
      }
    })}
  </div>`;
};

const duration = (stats) => {
  const start = new Date(stats.started_at);
  const end = new Date(stats.completed_at);
  const durationMs = end.getTime() - start.getTime();
  const durationSec = durationMs / 1000;
  return formatTime(durationSec);
};
