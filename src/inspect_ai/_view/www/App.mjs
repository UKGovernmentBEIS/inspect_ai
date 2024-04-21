
import { html } from 'htm/preact';
import { useState, useEffect } from 'preact/hooks'

import { client_events, eval_logs } from 'api'

import { Log } from './Log.mjs'

export function App() {

  const [selected, setSelected] = useState(0)
  const [logs, setLogs] = useState({ log_dir: "", files: [] })

  // reset selection when logs are refreshed
  useEffect(() => {
    setSelected(0)
  }, [logs])

  useEffect(() => {
    // initial fetch of logs
    eval_logs().then(setLogs)

    // poll every 1s for events
    setInterval(() => {
      client_events().then(events => {
        if (events.includes("reload")) {
          window.location.reload(true)
        }
        if (events.includes("refresh-evals")) {
          eval_logs().then(setLogs)
        }
      })
    }, 1000)

  }, [])


  return html`
    <div>
      <${Header} 
        logs=${logs} 
      />
      <${Sidebar} 
        logs=${logs} 
        selected=${selected}
        onSelected=${(index) => setSelected(index)}
      />
      <${Log} 
        logs=${logs} selected=${selected}
      /> 
    </div>
  `
}

const Header = (props) => {
  return html`
    <nav class="navbar sticky-top bg-light shadow-sm">
      <div class="container-fluid">
        <span class="navbar-brand mb-0">
          <i class="bi bi-gear"></i> Inspect View
        </span>
        <span class="navbar-text">
          ${props.logs.log_dir}
        </span>
      </div>
    </nav>
  `;
}

const Sidebar = (props) => {

  return html`
    <div class="sidebar border-end">
      <ul class="list-group">
        ${props.logs.files.map((file, index) => {
    const active = index === props.selected ? " active" : ""
    const time = new Date(file.mtime)
    return html`
      <li 
        class="list-group-item list-group-item-action${active}"
        onclick=${() => props.onSelected(index)}
      >
        <div class="d-flex w-100 justify-content-between">
          <small class="mb-1">${file.task}</small>
        </div>
        <small class="mb-1 text-muted">
          ${time.toDateString()} ${time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </p>
      </li>
    `})
    }
      </ul>
    </div>
  `
}


