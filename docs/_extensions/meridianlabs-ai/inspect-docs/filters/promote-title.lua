-- Promote the first H1 heading to document title when no title is set
-- in frontmatter. This ensures Quarto generates a proper .quarto-title
-- block for pages like README.md that use a markdown H1 instead of
-- YAML frontmatter.

function Pandoc(doc)
  -- skip if title is already set in metadata
  if doc.meta.title then
    return nil
  end

  -- find the first H1 heading
  for i, el in ipairs(doc.blocks) do
    if el.t == "Header" and el.level == 1 then
      -- promote to document title and remove from body
      doc.meta.title = el.content
      doc.blocks:remove(i)
      return doc
    end
  end
end
