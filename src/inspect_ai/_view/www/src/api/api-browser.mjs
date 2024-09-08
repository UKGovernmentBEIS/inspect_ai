import { asyncJsonParse } from "../utils/Json.mjs";
import { download_file } from "./api-shared.mjs";

const loaded_time = Date.now();
let last_eval_time = 0;

async function client_events() {
  const params = new URLSearchParams();
  params.append("loaded_time", loaded_time.valueOf());
  params.append("last_eval_time", last_eval_time.valueOf());
  return (await api("GET", `/api/events?${params.toString()}`)).parsed;
}

async function eval_logs() {
  const logs = await api("GET", `/api/logs`);
  last_eval_time = Date.now();
  return logs.parsed;
}

async function eval_log(file, headerOnly) {
  return await api("GET", `/api/logs/${file}?header-only=${headerOnly}`);
}

async function eval_log_headers(files) {
  const params = new URLSearchParams();
  for (const file of files) {
    params.append("file", file);
  }
  return (await api("GET", `/api/log-headers?${params.toString()}`)).parsed;
}

async function api(method, path, body) {
  // build headers
  const headers = {
    Accept: "application/json",
    Pragma: "no-cache",
    Expires: "0",
    ["Cache-Control"]: "no-cache",
  };
  if (body) {
    headers["Content-Type"] = "application/json";
  }

  // make request
  const response = await fetch(`${path}`, { method, headers, body });
  if (response.ok) {
    const text = await response.text();
    return {
      parsed: await asyncJsonParse(text),
      raw: text,
    };
  } else if (response.status !== 200) {
    const message = (await response.text()) || response.statusText;
    const error = new Error(`Error: ${response.status}: ${message})`);
    throw error;
  } else {
    throw new Error(`${response.status} - ${response.statusText} `);
  }
}

async function open_log_file() {
  // No op
}

export default {
  client_events,
  eval_logs,
  eval_log,
  eval_log_headers,
  download_file,
  open_log_file,
};
