import { html } from "htm/preact";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

export const EpochFilter = ({ epochs, epoch, setEpoch }) => {
  const options = ["all"];
  for (let i = 1; i <= epochs; i++) {
    options.push(i + "");
  }
  return html`
    <div style=${{ display: "flex" }}>
      <span
        class="epoch-filter-label"
        style=${{
          alignSelf: "center",
          fontSize: FontSize.smaller,
          ...TextStyle.label,
          ...TextStyle.secondary,
          marginRight: "0.3em",
          marginLeft: "0.2em",
        }}
        >Epochs:</span
      >
      <select
        class="form-select form-select-sm"
        aria-label=".epoch-filter-label"
        style=${{ fontSize: FontSize.smaller }}
        value=${epoch}
        onChange=${(e) => {
          setEpoch(e.target.value);
        }}
      >
        ${options.map((option) => {
          return html`<option value="${option}">${option}</option>`;
        })}
      </select>
    </div>
  `;
};
