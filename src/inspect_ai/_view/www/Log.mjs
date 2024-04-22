
import { html } from 'htm/preact';
import { useEffect, useState, useRef } from 'preact/hooks';

import { eval_log } from 'api'

export const Log = (props) => {


  const divRef = useRef()
  const codeRef = useRef()

  /**
   * 
   * @param {import('./log').EvalLog} log 
   */
  const setLog = (log) => {
    divRef.current.scrollTop = 0;
    if (log) {
      codeRef.current.innerHTML = Prism.highlight(
        JSON.stringify(log, null, 2),
        Prism.languages.javascript,
        'javacript'
      )
    } else {
      codeRef.current.innerHTML = ""
    }
  }

  useEffect(() => {
    if (props.logs.files.length > 0) {
      const log_file = props.logs.files[props.selected].name
      eval_log(log_file).then(setLog)
    } else {
      setLog(null)
    }
  }, [props.logs, props.selected])

  return html`
      <div ref=${divRef} class="log p-2">
        <pre><code ref=${codeRef}></code></pre>
    
      </div >
  `;
}

