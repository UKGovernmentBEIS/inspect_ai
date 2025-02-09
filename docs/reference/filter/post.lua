--- filter for post-processing the main ref generation filter (filter.py)
--- does interlinks for reference links and renders raw markdown blocks

local pandoc = require('pandoc')

-- read refs index
refs_file = io.open("refs.json", "r")
refs = pandoc.json.decode(refs_file:read("a"))
refs_file:close()

function Span(el)
    if el.classes:includes("element-type-name") and not el.classes:includes("ref-interlink") then
        type = pandoc.utils.stringify(el)
        type_ref = refs[type]
        if type_ref ~= nil then
            el.content = pandoc.Link(el.content:clone(), type_ref)
            return el
        end
    end
end

function RawBlock(raw)
    -- Only process markdown raw blocks
    if raw.format ~= 'markdown' then
        return nil
    end

    -- Parse the markdown content into pandoc AST
    -- Note: pandoc.read returns a Pandoc document, we want its blocks
    local doc = pandoc.read(raw.text, 'markdown+autolink_bare_uris')
    if doc and doc.blocks then
        return doc.blocks
    end
    return nil
end

function RawInline(raw)
    -- Only process markdown raw inlines
    if raw.format ~= 'markdown' then
        return nil
    end

    -- Parse the markdown content into pandoc AST
    local doc = pandoc.read(raw.text, 'markdown+autolink_bare_uris')
    if doc and doc.blocks then
        -- For inline content, we want the inlines from the first block
        -- (typically a Para or Plain block)
        local first_block = doc.blocks[1]
        if first_block then
            return first_block.content
        end
    end
    return nil
end
