import type { Plugin } from 'unified'
import type { Root, Text } from 'mdast'
import { visit } from 'unist-util-visit'

const CITATION_RE = /\[(S\d+)\]/g

const remarkCitationLink: Plugin<[], Root> = () => {
  return (tree: Root) => {
    visit(tree, 'text', (node: Text, index, parent) => {
      if (!parent || index == null) return

      const matches = [...node.value.matchAll(CITATION_RE)]
      if (matches.length === 0) return

      const children: Root['children'] = []
      let lastIndex = 0

      for (const match of matches) {
        const matchStart = match.index!
        const matchEnd = matchStart + match[0].length
        const citationId = match[1]

        if (matchStart > lastIndex) {
          children.push({ type: 'text', value: node.value.slice(lastIndex, matchStart) })
        }

        children.push({
          type: 'link',
          url: `#citation-${citationId}`,
          data: {
            hName: 'a',
            hProperties: {
              className: 'citation-ref',
              href: `#citation-${citationId}`,
            },
          },
          children: [{ type: 'text', value: `[${citationId}]` }],
        })

        lastIndex = matchEnd
      }

      if (lastIndex < node.value.length) {
        children.push({ type: 'text', value: node.value.slice(lastIndex) })
      }

      parent.children.splice(index, 1, ...children)
      return index + children.length
    })
  }
}

export default remarkCitationLink
