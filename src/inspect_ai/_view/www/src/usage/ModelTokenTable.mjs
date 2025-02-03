import { html } from "htm/preact";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { ModelUsagePanel } from "./UsageCard.mjs";

export const ModelTokenTable = ({ model_usage, style }) => {
  return html`
  <${TokenTable} style=${style}>
    <${TokenHeader}/>
    <tbody>
    ${Object.keys(model_usage).map((key) => {
      return html`<${TokenRow} model=${key} usage=${model_usage[key]} />`;
    })}
    </tbody>
  </${TokenTable}>
  `;
};

const TokenTable = ({ style, children }) => {
  return html`<table
    class="table table-sm"
    style=${{
      width: "100%",
      fontSize: FontSize.smaller,
      marginTop: "0.7rem",
      ...style,
    }}
  >
    ${children}
  </table>`;
};

const thStyle = {
  padding: 0,
  fontWeight: 300,
  fontSize: FontSize.small,
  ...TextStyle.label,
  ...TextStyle.secondary,
};

const TokenHeader = () => {
  return html`<thead>
    <tr>
      <td></td>
      <td
        colspan="3"
        align="center"
        class="card-subheading"
        style=${{
          paddingBottom: "0.7rem",
          fontSize: FontSize.small,
          ...TextStyle.label,
          ...TextStyle.secondary,
        }}
      >
        Tokens
      </td>
    </tr>
    <tr>
      <th style=${thStyle}>Model</th>
      <th style=${thStyle}>Usage</th>
    </tr>
  </thead>`;
};

const TokenRow = ({ model, usage }) => {
  return html`<tr>
    <td>${model}</td>
    <td>
      <${ModelUsagePanel} usage=${usage} />
    </td>
  </tr>`;
};
