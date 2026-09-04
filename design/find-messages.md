# Find on the Messages tab (server side)

The view server answers Cmd+F for the Messages tab: it tells the viewer
which rows of a sample match and what text matched; the viewer highlights
and counts in the rendered row. Client side: ts-mono `design/pluggable-find.md`.

Terms: a sample is addressed by `sample_id` and `epoch` (its repetition
number). A **sealed** sample is finished and stored in the log; a **live**
one is still being written and served from the recorder's buffer. A **row** is
what the Messages tab shows as one block: a non-tool message plus the tool
messages that follow it. A **projection** is the text the viewer renders a
row from under the current display settings.

## Contract

`POST /find-messages/{log}`

```
request  { sample_id, epoch, text, after?: anchor,
           projection?: { unlabeled_roles?, tool_call_style?, display_mode? } }
response { rows: [{ anchor, index, count, texts }], at_end, complete }
```

One response is one page: the matching rows after `after` (from the top when
absent), in order, ending at the server's row cap or shortly after the first
hit. The client keeps requesting with `after` = the last anchor it got.

- `at_end`: the page reached the last row the sample has right now.
  `complete`: the sample is sealed. Both true means every match has been
  seen; `complete: false` means the client re-scans on its next poll.
- `anchor`: the row's name, the same across polls of a live sample: its
  head message id, with `#<row index>` appended while a *prior* row already
  holds that string (`_rows.row_anchors`; the client mirrors it in
  `messageRowAnchorIds`). An unknown `after` restarts from the top.
- `index`: the row's position in the sample, for scrolling to a row the
  viewer has not loaded yet.
- `count`: matches in the row's projection, an estimate the viewer corrects
  against what it rendered. `texts`: the distinct substrings that matched,
  as written in the projection, for the viewer to highlight literally.
- `projection`: the viewer's display settings. `unlabeled_roles`: roles
  whose heading the viewer hides; `tool_call_style`: `complete` (calls and
  outputs), `compact` (calls only) or `omit`; `display_mode`: `rendered`
  markdown or `raw` source. Defaults are the viewer's defaults. Empty
  `text` returns no rows. Unknown sample: 404.

## Decisions

- **Anchors depend only on earlier rows.** A running sample is re-scanned
  on every poll and the viewer puts the user back on their row by anchor,
  so appending messages must never rename one; consulting only prior rows
  for collisions guarantees that.
- **Return rows and matched text, not offsets.** Positions exist only in the
  rendered DOM, which the server does not model. Rows plus literal
  substrings let the viewer find the exact spot itself and stay correct when
  rendering changes.
- **Search the text the user reads.** A row is projected to what the viewer
  shows for it, including the headings the viewer adds (`assistant`,
  `tool: bash`, `Reasoning`), because users search for those words too.
  Under `rendered`, markdown syntax is removed so "some bold" matches
  `some **bold**` as it does in a browser; tool arguments and outputs are
  searched verbatim (`_projection.project_row`).
- **Fold like a browser, on the server.** Matching is a literal substring
  over NFKD → combining marks dropped → `casefold`, which is Chrome's
  find-in-page behaviour (İ/i, ß/ss, é/e, ﬁ/fi). JavaScript cannot do this
  (`RegExp` `iu` is simple case folding; `Intl.Collator` compares whole
  strings), so the fold is Python and the offsets are mapped back so
  `texts` are source substrings (`_util.textsearch`). Scout's grep shares
  the module with `casefold` only and regex support.
- **Pages are time slices; the client sums.** There is no per-page total.
  A page ends ~50ms after its first hit so the first result shows quickly
  on a sample of any size; the client adds `count` over pages and shows a
  lower bound until `at_end && complete`.
- **Cache sealed samples, rebuild live ones.** The folded rows of a sealed
  sample cannot change, so a few are kept in memory keyed by log path and
  sample. A live sample is rebuilt from the recorder's buffer on every
  request, like the live Messages tab does. The key carries no file mtime or
  attempt number: a log rewritten in place at the same path, or a sample
  re-run under the same id and epoch, serves the earlier rows until
  eviction, which costs less than stat-ing a possibly remote file per
  keystroke.
- **Search chunked logs whole.** The log reader (`read_eval_log_sample`)
  reassembles a sample stored in the chunked per-sample layout, so the
  endpoint reads it like any other and the scan covers conversation the tab
  has not paged in.

## Why not

- Render parity with the viewer (tool views, argument summaries, citation
  numbers): the viewer corrects `count` against the DOM and skips a row that
  renders none of its `texts`; a server-side renderer would rot.
- GET with browser caching: live samples must not be cached and hawk's auth
  is part of the request; the viewer caches sealed pages itself.
- A backward direction: the viewer keeps every matching row of a forward
  scan, so wrapping to the last match is local once the scan is done.
- A `limit` parameter: the row cap and time budget are the page size; no
  client had a reason to choose.
