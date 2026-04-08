-- Convert .excalidraw image references to SVG at build time.
--
-- Usage in markdown:
--   ![caption](path/to/diagram.excalidraw)
--   ![caption](path/to/diagram.excalidraw){theme=dark background=true padding=20 scale=2}
--
-- The filter intercepts Image elements whose src ends in .excalidraw,
-- converts them to SVG via a bundled Node.js script, and rewrites the
-- image src to point at the generated .excalidraw.svg file.

local function file_exists(path)
  local f = io.open(path, "r")
  if f then
    f:close()
    return true
  end
  return false
end

local function file_mtime(path)
  -- Use os.execute + stat to get modification time.
  -- Returns nil if the file does not exist.
  local handle = io.popen('stat -f "%m" "' .. path .. '" 2>/dev/null || stat -c "%Y" "' .. path .. '" 2>/dev/null')
  if not handle then return nil end
  local result = handle:read("*a")
  handle:close()
  local mtime = tonumber(result)
  return mtime
end

local function convert_excalidraw(src, attrs)
  -- Resolve the .excalidraw path relative to the current input file
  local input_dir = pandoc.path.directory(quarto.doc.input_file)
  local excalidraw_path = pandoc.path.join({ input_dir, src })

  if not file_exists(excalidraw_path) then
    quarto.log.warning("excalidraw: file not found: " .. excalidraw_path)
    return nil
  end

  -- Output path: foo.excalidraw -> foo.excalidraw.svg
  local svg_path = excalidraw_path .. ".svg"
  local svg_src = src .. ".svg"

  -- Check timestamp cache: skip if SVG is newer than source
  local src_mtime = file_mtime(excalidraw_path)
  local svg_mtime = file_mtime(svg_path)
  if src_mtime and svg_mtime and svg_mtime >= src_mtime then
    return svg_src
  end

  -- Build conversion command
  local script_dir = pandoc.path.directory(PANDOC_SCRIPT_FILE)
  local converter = pandoc.path.join({ script_dir, "..", "resources", "excalidraw", "excalidraw-to-svg.mjs" })

  local cmd = 'node "' .. converter .. '" "' .. excalidraw_path .. '" "' .. svg_path .. '"'

  -- Append options from image attributes
  local theme = attrs["theme"] or "light"
  cmd = cmd .. ' --theme ' .. theme

  if attrs["background"] == "true" then
    cmd = cmd .. ' --background'
  end

  local padding = attrs["padding"]
  if padding then
    cmd = cmd .. ' --padding ' .. padding
  end

  local scale = attrs["scale"]
  if scale then
    cmd = cmd .. ' --scale ' .. scale
  end

  local ok, _, code = os.execute(cmd)
  if not ok then
    quarto.log.warning("excalidraw: conversion failed for " .. src .. " (exit " .. tostring(code) .. ")")
    return nil
  end

  return svg_src
end

function Image(el)
  if not el.src:match("%.excalidraw$") then
    return nil
  end

  local svg_src = convert_excalidraw(el.src, el.attributes)
  if not svg_src then
    return nil
  end

  el.src = svg_src

  -- Remove excalidraw-specific attributes so they don't pass through to HTML
  el.attributes["theme"] = nil
  el.attributes["background"] = nil
  el.attributes["padding"] = nil
  el.attributes["scale"] = nil

  return el
end
