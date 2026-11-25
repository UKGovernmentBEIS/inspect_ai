-- Append a small "Last updated <date>" line to the bottom of each page.
--
-- The date is that of the last git commit touching the page's source file
-- or any file it pulls in via `{{< include >}}` (recursively), so edits to
-- shared snippets count too. File mtimes aren't used as they are
-- meaningless after a fresh checkout.
--
-- Skipped when:
--   - the page sets `date-modified` in its front matter (Quarto already
--     shows that in the title block)
--   - `inspect-docs: last-modified: false` is set
--   - the page is generated API reference (its content comes from
--     docstrings, not the stub .qmd)
--   - git is unavailable, the checkout is shallow, or the files have no
--     commits yet

local MONTHS = {
  "January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December",
}

local function trim(s)
  return (s:gsub("%s+$", ""))
end

local function git(dir, args)
  local cmd = { "-C", dir }
  for _, a in ipairs(args) do
    table.insert(cmd, a)
  end
  local ok, out = pcall(pandoc.pipe, "git", cmd, "")
  if not ok then
    return nil
  end
  out = trim(out)
  if out == "" then
    return nil
  end
  return out
end

-- resolve symlinks (e.g. CHANGELOG.md -> ../CHANGELOG.md) to the real file.
-- `realpath` isn't on older macOS, so fall back to a one-level `readlink`.
local function realpath(path)
  local ok, out = pcall(pandoc.pipe, "realpath", { path }, "")
  if ok and trim(out) ~= "" then
    return trim(out)
  end
  ok, out = pcall(pandoc.pipe, "readlink", { path }, "")
  if ok and trim(out) ~= "" then
    local target = trim(out)
    if pandoc.path.is_relative(target) then
      target = pandoc.path.join({ pandoc.path.directory(path), target })
    end
    return target
  end
  return path
end

-- collect `path` plus every file it (transitively) includes. Includes
-- resolve relative to the including file as Quarto sees it (the symlink,
-- not its target), or to the project root for paths starting with "/".
local function collect_sources(path, project_dir, seen, out)
  local real = realpath(path)
  if seen[real] then
    return
  end
  local f = io.open(real, "r")
  if f == nil then
    return
  end
  local text = f:read("a")
  f:close()
  seen[real] = true
  table.insert(out, real)
  local dir = pandoc.path.directory(path)
  for inc in text:gmatch("{{<%s*include%s+(.-)%s*>}}") do
    inc = inc:gsub('^"(.*)"$', "%1"):gsub("^'(.*)'$", "%1")
    if inc:sub(1, 1) == "/" then
      inc = pandoc.path.join({ project_dir, inc:sub(2) })
    elseif pandoc.path.is_relative(inc) then
      inc = pandoc.path.join({ dir, inc })
    end
    collect_sources(inc, project_dir, seen, out)
  end
end

local function format_date(date)
  local y, m, d = date:match("^(%d+)-(%d+)-(%d+)$")
  if y == nil then
    return date
  end
  return MONTHS[tonumber(m)] .. " " .. tonumber(d) .. ", " .. y
end

function Pandoc(doc)
  local meta = doc.meta
  if meta["date-modified"] ~= nil then
    return nil
  end
  local opts = meta["inspect-docs"]
  if opts ~= nil and opts["last-modified"] == false then
    return nil
  end

  local input = quarto.doc.input_file
  if input == nil or input == "" then
    return nil
  end
  local project_dir = quarto.project.directory or pandoc.path.directory(input)
  local rel = pandoc.path.make_relative(input, project_dir):gsub("\\", "/")
  if rel:match("^reference/") then
    return nil
  end

  local sources = {}
  collect_sources(input, project_dir, {}, sources)
  if #sources == 0 then
    return nil
  end
  local dir = pandoc.path.directory(sources[1])

  -- a shallow clone would date every page to the clone's tip commit
  if git(dir, { "rev-parse", "--is-shallow-repository" }) ~= "false" then
    return nil
  end

  local args = { "log", "-1", "--format=%cs", "--" }
  for _, s in ipairs(sources) do
    table.insert(args, s)
  end
  local date = git(dir, args)
  if date == nil then
    return nil
  end

  doc.blocks:insert(pandoc.Div(
    pandoc.Plain({ pandoc.Str("Last updated " .. format_date(date)) }),
    pandoc.Attr("", { "page-last-modified" })
  ))
  return doc
end
