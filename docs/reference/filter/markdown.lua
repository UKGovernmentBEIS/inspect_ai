local text = require('text')
local pandoc = require('pandoc')

function RawBlock(raw)
    -- Only process markdown raw blocks
    if raw.format ~= 'markdown' then
        return nil
    end

    -- Parse the markdown content into pandoc AST
    -- Note: pandoc.read returns a Pandoc document, we want its blocks
    local doc = pandoc.read(raw.text, 'markdown')
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
    local doc = pandoc.read(raw.text, 'markdown')
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
