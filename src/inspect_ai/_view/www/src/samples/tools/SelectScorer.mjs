import { html } from "htm/preact";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";
import { parseScoreLabelKey, scoreLabelKey } from "../SamplesDescriptor.mjs";

/**
 * @param {Object} props
 * @param {import("../../Types.mjs").ScoreLabel[]} props.scores
 * @param {import("../../Types.mjs").ScoreLabel} props.score
 * @param {(score: import("../../Types.mjs").ScoreLabel) => void} props.setScore
 * @returns {import("preact").JSX.Element}
 */
export const SelectScorer = ({ scores, score, setScore }) => {
  return html`
    <div style=${{ display: "flex" }}>
      <span
        class="select-scorer-label"
        style=${{
          alignSelf: "center",
          fontSize: FontSize.smaller,
          ...TextStyle.label,
          ...TextStyle.secondary,
          marginRight: "0.3em",
          marginLeft: "0.2em",
        }}
        >Scorer:</span
      >
      <${ScoreSelector}
        scores=${scores}
        selectedScore=${score}
        setScore=${setScore}
      />
    </div>
  `;
};

/**
 * @param {Object} props
 * @param {import("../../Types.mjs").ScoreLabel[]} props.scores
 * @param {import("../../Types.mjs").ScoreLabel} props.selectedScore
 * @param {(score: import("../../Types.mjs").ScoreLabel) => void} props.setScore
 * @returns {import("preact").JSX.Element}
 */
const ScoreSelector = ({ scores, selectedScore, setScore }) => {
  const scorers = new Set(scores.map((score) => score.scorer));
  const needHeadersAndIndent = scorers.size > 1;
  const items = [];
  let currentScorer = undefined;
  for (const score of scores) {
    const scoreKey = scoreLabelKey(score);
    if (score.name == score.scorer) {
      items.push({ display: score.name, value: scoreKey });
    } else {
      if (needHeadersAndIndent && currentScorer != score.scorer) {
        // Cannot select the scorer object, select the first score instead.
        items.push({
          display: score.scorer,
          value: `target:${scoreKey}`,
        });
      }
      items.push({
        display: (needHeadersAndIndent ? "- " : "") + score.name,
        value: scoreKey,
      });
    }
    currentScorer = score.scorer;
  }
  // TODO(andrei-apollo): Implement a custom <select> widget that:
  //   - Makes unclickable titles properly unclickable (instead of selecting the
  //     first score).
  //   - Removes the bullet when the dropdown is closed. Or maybe shows
  //     something like `scorer.score` with the first part grayed out.
  //   - Renders the tree structure more beautifully.
  return html`<select
    class="form-select form-select-sm"
    aria-label=".select-scorer-label"
    style=${{ fontSize: FontSize.smaller }}
    value=${scoreLabelKey(selectedScore)}
    onChange=${(e) => {
      let value = e.target.value.replace(/^target:/, "");
      setScore(parseScoreLabelKey(value));
    }}
  >
    ${items.map(({ display, value }) => {
      return html`<option value="${value}">${display}</option>`;
    })}
  </select>`;
};
