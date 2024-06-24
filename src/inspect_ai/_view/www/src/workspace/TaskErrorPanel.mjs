import { html } from "htm/preact";
import { icons } from "../Constants.mjs";

import { Card, CardHeader, CardBody } from "../components/Card.mjs";
import { ANSIDisplay } from "../components/AnsiDisplay.mjs";

export const TaskErrorCard = ({ evalError }) => {
  return html`
    <${Card}>
      <${CardHeader} icon=${icons.error} label="Task Failed: ${evalError.message}"></${CardHeader}>
      <${CardBody} style=${{ fontSize: "0.8em" }}>
        <${ANSIDisplay} output=${evalError.traceback_ansi}/>
      </${CardBody}>
    </${Card}>
  `;
};
