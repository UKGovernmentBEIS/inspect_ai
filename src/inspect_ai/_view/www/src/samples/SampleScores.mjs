import { html } from "htm/preact";

/**
 * @param {Object} props
 * @param {import("../api/Types.mjs").SampleSummary} props.sample
 * @param {import("../samples/SamplesDescriptor.mjs").SamplesDescriptor} props.sampleDescriptor
 * @param {string} props.scorer
 * @returns {import("preact").JSX.Element}
 */
export const SampleScores = ({ sample, sampleDescriptor, scorer }) => {
  const scores = scorer
    ? sampleDescriptor.evalDescriptor
        .scorerDescriptor(sample, { scorer, name: scorer })
        .scores()
    : sampleDescriptor.selectedScorerDescriptor(sample).scores();

  if (scores.length === 1) {
    return scores[0].rendered();
  } else {
    const rows = scores.map((score) => {
      return html` <div style=${{ opacity: "0.7" }}>${score.name}</div>
        <div>${score.rendered()}</div>`;
    });
    return html`<div
      style=${{
        display: "grid",
        gridTemplateColumns: "max-content max-content",
        columnGap: "1em",
      }}
    >
      ${rows}
    </div>`;
  }
};
