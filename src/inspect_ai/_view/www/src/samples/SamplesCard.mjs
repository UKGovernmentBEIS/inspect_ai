import { html } from "htm/preact";

import { sharedStyles } from "../Constants.mjs";

import { Card, CardBody, CardHeader } from "../components/Card.mjs";
import { EmptyPanel } from "../components/EmptyPanel.mjs";
import { SampleView } from "./SampleView.mjs";
import { SampleGroupSeparator } from "./SampleGroupSeparator.mjs";

export const SamplesCard = ({
  samples,
  context,
  toggleSample,
  openSamples,
  sampleDescriptor,
  groupBy,
  numbering,
}) => {
  const cardColumnsStyle = {
    marginLeft: "0",
    paddingLeft: "5em",
    paddingRight: "calc(12px + 1em)",
    flexWrap: "nowrap",
  };

  const cardTitleStyle = {
    paddingLeft: "0",
    paddingRight: "1rem",
  };

  const cardColumnLabelStyle = {
    fontSize: "0.7rem",
    fontWeight: "600",
    paddingTop: "3px",
  };

  return html`
    <${Card} id="task-samples">
      <${CardHeader} style=${{ paddingLeft: "0" }}>
      <div class="container-fluid">
        <div class="row" style=${cardColumnsStyle}>
          <div class="col" style=${{
            ...cardTitleStyle,
            ...sharedStyles.scoreGrid.titleCol,
          }}>
            Input
          </div>
          <div class="col" style=${{
            ...cardColumnLabelStyle,
            ...sharedStyles.scoreGrid.targetCol,
          }}>Target</div>
          <div class="col" style=${{
            ...cardColumnLabelStyle,
            ...sharedStyles.scoreGrid.answerCol,
          }}>Answer</div>
          <div class="col" style=${{
            ...cardColumnLabelStyle,
            ...sharedStyles.scoreGrid.scoreCol,
          }}>Score</div>
        </div>
      </div>      
      </${CardHeader}>
      <${CardBody} classes="accordion accordion-flush" style=${{
    padding: "0",
    fontSize: "0.8rem",
  }}>
      ${
        samples.length > 0
          ? samples.map((sample, index, arr) => {
              // TODO: Improve the way numbering items is handled.
              const result = [];

              const epochSize = samples.length / sampleDescriptor.epochs;
              let sampleId;
              if (groupBy === "epoch") {
                if (index === 0 || sample.epoch !== arr[index - 1].epoch) {
                  result.push(
                    html`<${SampleGroupSeparator}
                      label="epoch"
                      group=${sample.epoch}
                    />`
                  );
                }

                if (numbering === "asc") {
                  sampleId = (index % epochSize) + 1;
                } else {
                  sampleId = epochSize - (index % epochSize);
                }
              } else if (groupBy === "sample") {
                if (index === 0 || sample.id !== arr[index - 1].id) {
                  
                  
                  let group = index / sampleDescriptor.epochs + 1;
                  if (numbering === "desc") {
                    group = (samples.length / sampleDescriptor.epochs) - (index / sampleDescriptor.epochs);
                  }
                  
                  
                  result.push(
                    html`<${SampleGroupSeparator}
                      label="sample"
                      group=${group}
                    />`
                  );
                }
                if (numbering === "asc") {
                  sampleId = sample.epoch;
                } else {
                  sampleId = sampleDescriptor.epochs - sample.epoch + 1;
                }
              } else {
                if (numbering === "asc") {
                  sampleId = index + 1;
                } else {
                  sampleId = samples.length - index;
                }
              }

              const expanded =
                samples.length === 1 || openSamples.includes(`${sample.id}-${sample.epoch}`);
              const onToggled = (id) => {
                toggleSample(`${id}-${sample.epoch}`);
              }

              result.push(html`<${SampleView}
                id=${`sample-${index}`}
                index=${sampleId}
                sample=${sample}
                context=${context}
                sampleDescriptor=${sampleDescriptor}
                toggleSample=${onToggled}
                expanded=${expanded}
                noHighlight=${samples.length === 1}
              />`);
              return result;
            })
          : html`<${EmptyPanel}>No Matching Samples</${EmptyPanel}>`
      }
      </${CardBody}>
    </${Card}>
  `;
};
