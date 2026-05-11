-- interlink filter for inline code
--
-- Converts inline code that matches a class name (`ClassName`) or function
-- call (`func()`) pattern into links to reference documentation. Looks up
-- symbols first in the local `refs.json`, then in each configured external
-- package's refs file (downloaded at pre-render time with absolute URLs
-- baked in).
--
-- Supported syntax:
--   `Symbol`               -> global lookup: local first, then externals
--   `pkg::Symbol`          -> lookup only in external_refs[pkg]
--   `Symbol`{.noref}       -> no lookup, rendered as plain code

local pandoc = require('pandoc')

-- resolve refs path relative to the project root. Quarto runs filters with
-- CWD set to the source file's directory, so we need an absolute path to the
-- reference/ directory that holds refs.json.
local project_dir = quarto.project.directory
local reference_dir = project_dir .. "/reference/"

local is_reference = string.find(quarto.doc.input_file, "/reference/") ~= nil
local function refs_path(name)
    return reference_dir .. name
end

-- link prefix, used to build hrefs back into reference/ from the current doc
local function link_prefix()
    if is_reference then
        return ""
    end
    -- compute how many directory hops from the current doc to the project root
    local rel = string.sub(quarto.doc.input_file, #project_dir + 2)  -- skip "/"
    local hops = 0
    for _ in string.gmatch(rel, "/") do
        hops = hops + 1
    end
    return string.rep("../", hops) .. "reference/"
end

local function load_json(path)
    local f = io.open(path, "r")
    if f == nil then return nil end
    local content = f:read("a")
    f:close()
    return pandoc.json.decode(content)
end

-- load local refs
local refs = load_json(refs_path("refs.json")) or {}

-- load external refs via manifest (written by pre-render.py)
local external_refs = {}
local manifest = load_json(refs_path("refs-external.json"))
if manifest ~= nil then
    for _, pkg_name in ipairs(manifest) do
        local ext = load_json(refs_path("refs-" .. pkg_name .. ".json"))
        if ext ~= nil then
            external_refs[pkg_name] = ext
        end
    end
end

local function is_class_name(str)
    return string.find(str, "^[A-Z]%S+$") ~= nil
end

local function is_function_call(str)
    return string.find(str, "^%S+%(%)$") ~= nil
end

local function create_interlink(text, ref)
    return pandoc.Span(pandoc.Link(pandoc.Str(text), link_prefix() .. ref),
        { class = "element-type-name ref-interlink" })
end

local function create_external_link(text, url)
    return pandoc.Span(pandoc.Link(pandoc.Str(text), url),
        { class = "element-type-name ref-interlink" })
end

-- look up a symbol key across local and external refs, in order.
-- returns (link_element, nil) on hit, (nil, nil) on miss.
local function lookup(text, key)
    local ref = refs[key]
    if ref ~= nil then
        return create_interlink(text, ref)
    end
    for _, ext_refs in pairs(external_refs) do
        ref = ext_refs[key]
        if ref ~= nil then
            return create_external_link(text, ref)
        end
    end
    return nil
end

function Code(el)
    -- opt-out via .noref class
    if el.classes:includes("noref") then
        return nil
    end

    local text = el.text

    -- parse pkg::Symbol syntax and route to a specific external package
    local pkg, symbol = string.match(text, "^([%w_]+)::(.+)$")
    if pkg ~= nil and external_refs[pkg] ~= nil then
        text = symbol  -- display text strips the pkg:: prefix
        local key
        if is_class_name(text) then
            key = text
        elseif is_function_call(text) then
            key = string.sub(text, 1, -3)
        else
            return nil
        end
        local ref = external_refs[pkg][key]
        if ref ~= nil then
            return create_external_link(text, ref)
        end
        return nil
    end

    -- global lookup
    if is_class_name(text) then
        return lookup(text, text)
    elseif is_function_call(text) then
        return lookup(text, string.sub(text, 1, -3))
    end
end
