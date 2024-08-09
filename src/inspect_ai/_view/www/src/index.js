import { render } from "preact";
import { html } from "htm/preact";

import { App } from "./App.mjs";
import api from "./api/index.mjs";

render(html`<${App} api=${api} />`, document.getElementById("app"));
