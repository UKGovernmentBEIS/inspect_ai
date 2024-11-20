import { html } from "htm/preact";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

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
        selectedIndex=${scoreIndex(score, scores)}
        selectedIndexChanged=${(index) => {
          setScore(scores[index]);
        }}
      />
    </div>
  `;
};

const ScoreSelector = ({
  scores,
  selectedIndex,
  selectedIndexChanged,
  style,
}) => {
  return html`<select
    class="form-select form-select-sm"
    aria-label=".select-scorer-label"
    style=${{ fontSize: FontSize.smaller, ...style }}
    value=${scores[selectedIndex].name}
    onChange=${(e) => {
      selectedIndexChanged(e.target.selectedIndex);
    }}
  >
    ${scores.map((score) => {
      // Would be nice to hide the bullet when <select> is closed and only show it
      // in the dropdown menu, but this requires a fully manual <select> replacement.
      return html`<option value="${score.name}">
        ${score.scorer != score.name ? "- " : ""}${score.name}
      </option>`;
    })}
  </select>`;
};

const scoreIndex = (score, scores) =>
  scores.findIndex((sc) => {
    return sc.name === score.name && sc.scorer === score.scorer;
  });
