-- Shift header levels within a marked container div
-- Usage: ::: {.shift-headings by=1}
--        {{< include file.md >}}
--        :::

function Div(el)
  if el.classes:includes("shift-headings") then
    local shift = tonumber(el.attributes["by"]) or 1
    return el:walk({
      Header = function(h)
        h.level = h.level + shift
        return h
      end
    })
  end
end
