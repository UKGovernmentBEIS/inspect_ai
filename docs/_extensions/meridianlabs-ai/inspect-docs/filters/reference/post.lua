--- filter for post-processing the main ref generation filter (filter.py)
--- does interlinks for reference links and renders raw markdown blocks

local pandoc = require('pandoc')

local function load_json(path)
    local f = io.open(path, "r")
    if f == nil then return nil end
    local content = f:read("a")
    f:close()
    return pandoc.json.decode(content)
end

-- read refs index (try current dir first, then reference/ for non-reference pages)
local refs = load_json("refs.json")
local prefix = ""
if refs == nil then
    refs = load_json("reference/refs.json")
    prefix = "reference/"
end
refs = refs or {}

-- load external refs via manifest (written by pre-render.py)
local external_refs = {}
local manifest_prefix = prefix  -- same directory as local refs.json
local manifest = load_json(manifest_prefix .. "refs-external.json")
if manifest ~= nil then
    for _, pkg_name in ipairs(manifest) do
        local ext = load_json(manifest_prefix .. "refs-" .. pkg_name .. ".json")
        if ext ~= nil then
            external_refs[pkg_name] = ext
        end
    end
end

function Span(el)
    if el.classes:includes("element-type-name") and not el.classes:includes("ref-interlink") then
        local type_name = pandoc.utils.stringify(el)
        -- local refs first
        local type_ref = refs[type_name]
        if type_ref ~= nil then
            el.content = pandoc.Link(el.content:clone(), prefix .. type_ref)
            return el
        end
        -- fallback to each external package in order
        for _, ext_refs in pairs(external_refs) do
            type_ref = ext_refs[type_name]
            if type_ref ~= nil then
                el.content = pandoc.Link(el.content:clone(), type_ref)
                return el
            end
        end
    end
end

function RawBlock(raw)
    -- Only process markdown raw blocks
    if raw.format ~= 'markdown' then
        return nil
    end

    -- Parse the markdown content into pandoc AST
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
        local first_block = doc.blocks[1]
        if first_block then
            return first_block.content
        end
    end
    return nil
end
