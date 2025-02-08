-- main interlink filter for user guide

local pandoc = require('pandoc')

refs = {}

-- read the refs if we aren't in the reference dir (it does its own interlinks)
if string.find(PANDOC_STATE.input_files[1], "^reference/") == nil then
    local refs_file = io.open("reference/refs.json", "r")
    if refs_file ~= nil then
        refs = pandoc.json.decode(refs_file:read("a"))
        refs_file:close()
    end
end


local function is_class_name(str)
    -- ^[A-Z] checks for capital letter at start
    -- %S+ checks for one or more non-space characters
    -- $ ensures we reach the end of string
    return string.find(str, "^[A-Z]%S+$") ~= nil
end

local function is_function_call(str)
    -- ^%S+ checks for one or more non-space characters from start
    -- %(%)$ checks for literal () at the end
    return string.find(str, "^%S+%(%)$") ~= nil
end

local function create_interlink(text, ref)
    return pandoc.Span(pandoc.Link(pandoc.Str(text), "reference/" .. ref),
        { class = "element-type-name ref-interlink" })
end


function Code(el)
    if is_class_name(el.text) then
        ref = refs[el.text]
        if ref ~= nil then
            return create_interlink(el.text, ref)
        end
    elseif is_function_call(el.text) then
        func = string.sub(el.text, 1, -3)
        ref = refs[func]
        if ref ~= nil then
            return create_interlink(el.text, ref)
        end
    end
end
