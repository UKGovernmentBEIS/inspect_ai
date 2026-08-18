-- Convert GitHub-style callouts to Quarto callouts.
--
-- GitHub uses:   > [!NOTE]
--                > Content here.
--
-- This filter detects that pattern in BlockQuotes and produces
-- a native quarto.Callout node so Quarto renders it properly.

local callout_types = {
  NOTE      = "note",
  TIP       = "tip",
  IMPORTANT = "important",
  WARNING   = "warning",
  CAUTION   = "caution",
}

function BlockQuote(el)
  -- need at least one block inside
  if #el.content == 0 then
    return nil
  end

  -- first block must be a Para whose first inline is a Str like "[!NOTE]"
  local first = el.content[1]
  if first.t ~= "Para" or #first.content == 0 then
    return nil
  end

  -- GitHub renders the marker as: [!TYPE] possibly followed by a SoftBreak
  -- and then the rest of the paragraph. The marker may be a single Str token
  -- or split across Str("[!") + Str("NOTE]") etc. Stringify the first inline
  -- and match.
  local first_text = pandoc.utils.stringify(first.content[1])
  local tag = first_text:match("^%[!(%u+)%]$")
  if not tag or not callout_types[tag] then
    return nil
  end

  -- strip the marker token and any immediately following SoftBreak / space
  local remaining = pandoc.List()
  local skip = true
  for i = 2, #first.content do
    if skip and (first.content[i].t == "SoftBreak" or
                 first.content[i].t == "LineBreak" or
                 (first.content[i].t == "Space")) then
      skip = false
    else
      skip = false
      remaining:insert(first.content[i])
    end
  end

  -- build callout content: remaining inlines from the first para (if any)
  -- plus all subsequent blocks
  local content = pandoc.Blocks({})
  if #remaining > 0 then
    content:insert(pandoc.Para(remaining))
  end
  for i = 2, #el.content do
    content:insert(el.content[i])
  end

  return quarto.Callout({
    type = callout_types[tag],
    content = content,
  })
end
