import { render } from "preact";
import { html } from "htm/preact";

//import { App } from "./App.mjs";
import { App2 } from "./App2.mjs";
import api from "./api/index.mjs";

render(html`<${App2} api=${api} />`, document.getElementById("app"));

//render(html`<${App} api=${api} />`, document.getElementById("app"));
