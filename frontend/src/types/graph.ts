export interface GraphNode {
  id: string
  title: string
  type: string
  graph_layer: number
  graph_role: string | null
  verification: string
  domain: string | null
  concepts: string[]
  unresolved?: boolean
  target_text?: string | null
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  rel_type: string
  source_field?: string | null
}

export interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export type RelTypeStyle = {
  arrow: boolean
  color: string
  dashArray?: string
  width: number
}

export const layerColors: Record<number, string> = {
  0: '#fb7185',
  1: '#3b82f6',
  2: '#8b5cf6',
  3: '#f59e0b',
}

export const roleColors: Record<string, string> = {
  source: '#3b82f6',
  concept: '#8b5cf6',
  index: '#f59e0b',
  unresolved: '#fb7185',
}

export const roleRadius: Record<string, number> = {
  source: 8,
  concept: 10,
  index: 14,
  unresolved: 7,
}

export const verificationColors: Record<string, string> = {
  verified: '#22c55e',
  unverified: '#94a3b8',
  draft: '#f59e0b',
  truncated: '#fb7185',
}

export const relTypeStyles: Record<string, RelTypeStyle> = {
  source_trace: { arrow: true, color: '#3b82f6', width: 1.5 },
  direct_link: { arrow: true, color: '#a78bfa', width: 2 },
  map_contains: { arrow: true, color: '#f59e0b', dashArray: '8 5', width: 1.5 },
  concept_overlap: { arrow: false, color: '#64748b', dashArray: '3 5', width: 1 },
  unresolved_link: { arrow: true, color: '#fb7185', dashArray: '4 4', width: 1.4 },
}
