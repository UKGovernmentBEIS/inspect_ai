-- Pandoc Lua filter for HTML-to-Markdown conversion (llms.txt support).
-- Applied when converting rendered Quarto HTML pages to .html.md files.

-- Classes whose elements should be dropped entirely.
local drop_classes = {
  ["navbar"] = true,
  ["nav-footer"] = true,
  ["quarto-header"] = true,
  ["quarto-sidebar"] = true,
  ["quarto-page-breadcrumbs"] = true,
  ["page-navigation"] = true,
  ["quarto-search"] = true,
  ["quarto-title-block"] = true,
  ["listing-actions-group"] = true,
  ["visually-hidden"] = true,
  ["copy-page-btn"] = true,
  ["quarto-back-to-top"] = true,
  ["callout-icon-container"] = true,
}

-- IDs whose elements should be dropped entirely.
local drop_ids = {
  ["quarto-header"] = true,
  ["quarto-sidebar"] = true,
  ["quarto-search-results"] = true,
  ["copy-page-btn"] = true,
}

-- Known callout types
local callout_types = {
  ["callout-note"] = "NOTE",
  ["callout-tip"] = "TIP",
  ["callout-warning"] = "WARNING",
  ["callout-important"] = "IMPORTANT",
  ["callout-caution"] = "CAUTION",
}

-- Convert a Quarto callout div into a blockquote.
-- Must run BEFORE inner divs are unwrapped (topdown traversal).
local function convert_callout(div)
  -- Determine callout type from classes
  local type_label = "NOTE"
  for _, cls in ipairs(div.classes) do
    if callout_types[cls] then
      type_label = callout_types[cls]
      break
    end
  end

  -- Extract title and body by walking the raw (not yet unwrapped) children
  local title_text = nil
  local body_blocks = pandoc.List()

  local function walk_content(blocks)
    for _, block in ipairs(blocks) do
      if block.t == "Div" then
        if block.classes:includes("callout-title-container") then
          title_text = pandoc.utils.stringify(block)
        elseif block.classes:includes("callout-body-container") or block.classes:includes("callout-body") then
          body_blocks:extend(block.content)
        elseif block.classes:includes("callout-header") then
          walk_content(block.content)
        elseif block.classes:includes("callout-icon-container") then
          -- drop icon
        else
          body_blocks:extend(block.content)
        end
      else
        body_blocks:insert(block)
      end
    end
  end

  walk_content(div.content)

  -- Fallback: try the HTML title attribute
  if (not title_text or title_text == "") and div.attributes["title"] then
    title_text = div.attributes["title"]
  end

  -- Build the blockquote: bold prefix line, then body
  local prefix_str = type_label .. ":"
  if title_text and title_text ~= "" then
    prefix_str = type_label .. ": " .. title_text
  end
  local prefix = pandoc.Strong(pandoc.Str(prefix_str))
  local result = pandoc.List({pandoc.Para({prefix})})
  result:extend(body_blocks)
  return pandoc.BlockQuote(result)
end

-- Convert a tabset div into sequential sections with headings.
local function convert_tabset(div)
  local result = pandoc.List()
  local tab_names = {}
  local tab_idx = 0

  for _, block in ipairs(div.content) do
    if block.t == "BulletList" and #tab_names == 0 then
      for _, item in ipairs(block.content) do
        local name = pandoc.utils.stringify(item)
        table.insert(tab_names, name)
      end
    elseif block.t == "Div" then
      local is_tab = false
      for _, cls in ipairs(block.classes) do
        if cls == "tab-pane" then
          is_tab = true
          break
        end
      end
      if is_tab then
        tab_idx = tab_idx + 1
        local name = tab_names[tab_idx] or ("Tab " .. tab_idx)
        result:insert(pandoc.Header(3, pandoc.Str(name)))
        result:extend(block.content)
      else
        result:extend(block.content)
      end
    else
      result:insert(block)
    end
  end

  return result
end

-- Use a filter list:
-- Pass 1 (topdown): handle callouts and tabsets while inner structure is intact.
--   Only drops/converts specific elements; leaves other divs alone so pandoc
--   recurses into them and finds nested callouts.
-- Pass 2 (default bottom-up): unwrap remaining divs, rewrite links, fix code blocks.
return {
  -- Pass 1: callouts, tabsets, and drops only (topdown).
  {
    traverse = "topdown",
    Div = function(div)
      -- Drop by ID
      local id = div.identifier or ""
      if drop_ids[id] then
        return {}
      end

      -- Drop by class
      for _, cls in ipairs(div.classes) do
        if drop_classes[cls] then
          return {}
        end
      end

      -- Convert callouts
      if div.classes:includes("callout") then
        return convert_callout(div)
      end

      -- Convert tabsets
      if div.classes:includes("panel-tabset") then
        return convert_tabset(div)
      end

      -- Leave other divs alone so pandoc recurses into their children
      return nil
    end,
  },

  -- Pass 2: unwrap remaining divs, rewrite links, fix code blocks.
  {
    Div = function(div)
      return div.content
    end,

    Link = function(link)
      if not link.target:match("^https?://") then
        link.target = link.target:gsub("%.html#", ".html.md#")
        link.target = link.target:gsub("%.html$", ".html.md")
      end
      return link
    end,

    CodeBlock = function(cb)
      if cb.classes:includes("sourceCode") then
        cb.classes = cb.classes:filter(function(c) return c ~= "sourceCode" end)
        cb.classes = cb.classes:filter(function(c)
          return c ~= "code-with-copy" and c ~= "cell-code"
        end)
      end
      return cb
    end,

    RawBlock = function(raw)
      return {}
    end,

    RawInline = function(raw)
      return {}
    end,
  },
}
