import { html } from "htm/preact";

import { icons } from "../Constants.mjs";
import { formatTime } from "../utils/Format.mjs";
import { Card, CardHeader, CardBody } from "../components/Card.mjs";
import { MetaDataView } from "../components/MetaDataView.mjs";
import { ModelTokenTable } from "./ModelTokenTable.mjs";

const kUsageCardBodyId = "usage-card-body";

export const UsageCard = ({ stats, context }) => {
  if (!stats) {
    return "";
  }

  const totalDuration = duration(stats);

  const usageMetadataStyle = {
    fontSize: "0.8em",
  };

  return html`

    <${Card}>
      <${CardHeader} icon=${icons.usage} label="Usage"/>
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
          <div class="card-subheading">Duration</div>
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

const duration = (stats) => {
  const start = new Date(stats.started_at);
  const end = new Date(stats.completed_at);
  const durationMs = end.getTime() - start.getTime();
  const durationSec = durationMs / 1000;
  return formatTime(durationSec);
};
