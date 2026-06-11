import type { Plugin } from 'unified'
import type { Root, Text } from 'mdast'
import { visit } from 'unist-util-visit'

const WIKILINK_RE = /\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]/g

function fallbackHref(target: string) {
  return `#${encodeURIComponent(target)}`
}

const remarkWikiLink: Plugin<[], Root> = () => {
  return (tree: Root) => {
    visit(tree, 'text', (node: Text, index, parent) => {
      if (!parent || index == null) return

      const matches = [...node.value.matchAll(WIKILINK_RE)]
      if (matches.length === 0) return

      const children: Root['children'] = []
      let lastIndex = 0

      for (const match of matches) {
        const matchStart = match.index!
        const matchEnd = matchStart + match[0].length
        const target = match[1].trim()
        const display = match[2]?.trim() ?? target

        if (matchStart > lastIndex) {
          children.push({ type: 'text', value: node.value.slice(lastIndex, matchStart) })
        }

        children.push({
          type: 'link',
          url: fallbackHref(target),
          data: {
            hName: 'a',
            hProperties: {
              className: 'wiki-link',
              'data-wiki-target': target,
              href: fallbackHref(target),
            },
          },
          children: [{ type: 'text', value: display }],
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

export default remarkWikiLink
