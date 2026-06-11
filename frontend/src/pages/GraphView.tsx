import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, ExternalLink, X } from 'lucide-react'
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationNodeDatum,
} from 'd3-force'
import ReactFlow, {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  useEdgesState,
  useNodesState,
  type Edge,
  type EdgeProps,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type NodeProps,
  type NodeTypes,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { useInstanceStore } from '@/stores/useInstanceStore'
import { getGraph } from '@/services/graph'
import { updateNoteVerification, type UserVerification } from '@/services/notes'
import type { GraphEdge, GraphNode } from '@/types/api'
import { layerColors, relTypeStyles, roleColors, roleRadius, verificationColors } from '@/types/graph'
import { formatApiError, formatGraphLayer, formatNoteType, formatRelationType, formatVerification } from '@/lib/i18nFormat'
import { LoadingState } from '@/components/shared/LoadingState'
import { useTranslation } from 'react-i18next'

interface FilterState {
  layers: Set<number>
  domains: Set<string>
  verifications: Set<string>
}

type PositionXY = {
  x: number
  y: number
}

type NodeVisual = {
  color: string
  fill: string
  radius: number
  ringColor: string
  shortLabel: string
  size: number
}

type GraphNodeData = GraphNode & {
  degree: number
  dimmed: boolean
  radius: number
  related: boolean
  selected: boolean
  visualSize: number
}

type GraphEdgeData = {
  active: boolean
  dimmed: boolean
  curveOffset: number
  relType: string
  sourceRadius: number
  targetRadius: number
}

type SimNode = SimulationNodeDatum & {
  id: string
  graphLayer: number
  radius: number
}

type SimLink = {
  source: string | SimNode
  target: string | SimNode
  relType: string
}

type FilteredGraph = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  degrees: Map<string, number>
  nodeIds: Set<string>
}

const LAYOUT_WIDTH = 1220
const LAYOUT_HEIGHT = 820
const LAYOUT_CENTER = { x: LAYOUT_WIDTH / 2, y: LAYOUT_HEIGHT / 2 }
const LABEL_GAP = 8
const RELAX_FRAMES = 36
const REVIEW_STATUSES: UserVerification[] = ['verified', 'unverified', 'draft']
const FILTER_VERIFICATIONS = ['verified', 'unverified', 'draft', 'truncated']

const hiddenHandleStyle: CSSProperties = {
  width: 6,
  height: 6,
  border: 0,
  background: 'transparent',
  opacity: 0,
  pointerEvents: 'none',
}

function getCenterHandleStyle(radius: number): CSSProperties {
  return {
    ...hiddenHandleStyle,
    bottom: 'auto',
    left: '50%',
    right: 'auto',
    top: radius,
    transform: 'translate(-50%, -50%)',
  }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function getGraphRole(node: Pick<GraphNode, 'graph_layer' | 'graph_role'> & { unresolved?: boolean }) {
  if (node.unresolved) return 'unresolved'
  if (node.graph_role) return node.graph_role
  if (node.graph_layer === 1) return 'source'
  if (node.graph_layer === 3) return 'index'
  return 'concept'
}

function getNodeVisual(node: Pick<GraphNode, 'graph_layer' | 'graph_role' | 'verification'> & { unresolved?: boolean }, degree = 0): NodeVisual {
  const role = getGraphRole(node)
  const color = roleColors[role] || layerColors[node.graph_layer] || '#64748b'
  const shortLabel = role === 'unresolved' ? 'MISS' : node.graph_layer === 3 ? 'MAP' : node.graph_layer === 1 ? 'SRC' : 'CARD'
  const baseRadius = roleRadius[role] || roleRadius.concept
  const radius = clamp(baseRadius + Math.log2(Math.max(degree, 0) + 1) * 2, baseRadius, baseRadius + 8)

  return {
    color,
    fill: color,
    radius,
    ringColor: `${color}66`,
    shortLabel,
    size: Math.round(radius * 2),
  }
}

function getEdgeVisual(relType: string, active = false, dimmed = false): CSSProperties {
  const relStyle = relTypeStyles[relType] || relTypeStyles.direct_link
  const isConcept = relType === 'concept_overlap'

  return {
    stroke: relStyle.color,
    strokeDasharray: relStyle.dashArray,
    strokeLinecap: 'round',
    opacity: dimmed ? 0.08 : active ? 0.92 : isConcept ? 0.25 : 0.4,
    strokeWidth: active ? relStyle.width + 0.8 : relStyle.width,
  }
}

function getEdgeLabelStyle(active = false): CSSProperties {
  return {
    color: 'var(--graph-edge-label-text)',
    fontSize: 10,
    fontWeight: 700,
    opacity: active ? 1 : 0,
    pointerEvents: 'none',
    transition: 'opacity 120ms ease',
  }
}

function getEdgeLabelBgStyle(active = false): CSSProperties {
  return {
    backgroundColor: active ? 'var(--graph-edge-label-bg)' : 'transparent',
    borderColor: active ? 'var(--graph-edge-label-border)' : 'transparent',
    opacity: active ? 1 : 0,
    transition: 'opacity 120ms ease',
  }
}

function buildConnectivity(edges: GraphEdge[]): Map<string, Set<string>> {
  const connectivity = new Map<string, Set<string>>()
  for (const edge of edges) {
    if (!connectivity.has(edge.source)) connectivity.set(edge.source, new Set())
    if (!connectivity.has(edge.target)) connectivity.set(edge.target, new Set())
    connectivity.get(edge.source)!.add(edge.target)
    connectivity.get(edge.target)!.add(edge.source)
  }
  return connectivity
}

function countDegrees(edges: GraphEdge[]): Map<string, number> {
  const degree = new Map<string, number>()
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1)
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1)
  }
  return degree
}

function pointOnEllipse(cx: number, cy: number, rx: number, ry: number, angle: number) {
  return {
    x: cx + Math.cos(angle) * rx,
    y: cy + Math.sin(angle) * ry,
  }
}

function sortByTitle(nodes: GraphNode[]) {
  return [...nodes].sort((a, b) => a.title.localeCompare(b.title) || a.id.localeCompare(b.id))
}

function createSeedPositions(nodes: GraphNode[]): Map<string, PositionXY> {
  const positions = new Map<string, PositionXY>()
  const maps = sortByTitle(nodes.filter((node) => node.graph_layer === 3))
  const cards = sortByTitle(nodes.filter((node) => node.graph_layer === 2))
  const sources = sortByTitle(nodes.filter((node) => node.graph_layer === 1))

  maps.forEach((node, index) => {
    const offset = (index - (maps.length - 1) / 2) * 138
    positions.set(node.id, { x: LAYOUT_CENTER.x + offset, y: LAYOUT_CENTER.y - 92 })
  })

  cards.forEach((node, index) => {
    const angle = cards.length === 1 ? Math.PI / 2 : -Math.PI * 0.9 + (Math.PI * 1.8 * index) / (cards.length - 1)
    positions.set(node.id, pointOnEllipse(LAYOUT_CENTER.x, LAYOUT_CENTER.y + 24, 390, 260, angle))
  })

  sources.forEach((node, index) => {
    const angle = sources.length === 1 ? Math.PI / 2 : Math.PI * 0.18 + (Math.PI * 0.64 * index) / (sources.length - 1)
    positions.set(node.id, pointOnEllipse(LAYOUT_CENTER.x, LAYOUT_CENTER.y + 190, 480, 160, angle))
  })

  nodes.forEach((node, index) => {
    if (!positions.has(node.id)) {
      positions.set(node.id, pointOnEllipse(LAYOUT_CENTER.x, LAYOUT_CENTER.y, 320, 220, (Math.PI * 2 * index) / nodes.length))
    }
  })

  return positions
}

function getRelationDistance(relType: string) {
  if (relType === 'direct_link') return 120
  if (relType === 'map_contains') return 150
  if (relType === 'source_trace') return 175
  if (relType === 'concept_overlap') return 260
  return 180
}

function getLayerAnchorX(graphLayer: number) {
  if (graphLayer === 1) return LAYOUT_CENTER.x
  return LAYOUT_CENTER.x
}

function getLayerAnchorY(graphLayer: number) {
  if (graphLayer === 3) return LAYOUT_CENTER.y - 120
  if (graphLayer === 1) return LAYOUT_CENTER.y + 165
  return LAYOUT_CENTER.y + 10
}

function createSimulationNodes(
  nodes: GraphNode[],
  previousPositions: Map<string, PositionXY>,
  degrees: Map<string, number>
): SimNode[] {
  const seedPositions = createSeedPositions(nodes)

  return nodes.map((node) => {
    const visual = getNodeVisual(node, degrees.get(node.id) || 0)
    const position = previousPositions.get(node.id) || seedPositions.get(node.id) || LAYOUT_CENTER

    return {
      id: node.id,
      graphLayer: node.graph_layer,
      radius: visual.radius,
      x: position.x,
      y: position.y,
    }
  })
}

function createSimulationLinks(edges: GraphEdge[], nodeIds: Set<string>): SimLink[] {
  return edges
    .filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))
    .map((edge) => ({
      source: edge.source,
      target: edge.target,
      relType: edge.rel_type,
    }))
}

function clampSimulationNodes(simNodes: SimNode[]) {
  for (const node of simNodes) {
    node.x = clamp(node.x || 0, 70, LAYOUT_WIDTH - 170)
    node.y = clamp(node.y || 0, 60, LAYOUT_HEIGHT - 180)
  }
}

function applyForceLayout(
  nodes: GraphNode[],
  edges: GraphEdge[],
  previousPositions: Map<string, PositionXY>,
  degrees: Map<string, number>
): Map<string, PositionXY> {
  const simNodes = createSimulationNodes(nodes, previousPositions, degrees)
  const nodeIds = new Set(nodes.map((node) => node.id))
  const simLinks = createSimulationLinks(edges, nodeIds)

  forceSimulation(simNodes)
    .force(
      'link',
      forceLink<SimNode, SimLink>(simLinks)
        .id((node) => node.id)
        .distance((link) => getRelationDistance(link.relType))
        .strength((link) => (link.relType === 'concept_overlap' ? 0.08 : 0.22))
    )
    .force('charge', forceManyBody<SimNode>().strength((node) => (node.graphLayer === 3 ? -520 : -380)))
    .force('center', forceCenter<SimNode>(LAYOUT_CENTER.x, LAYOUT_CENTER.y))
    .force('collide', forceCollide<SimNode>().radius((node) => node.radius + 28).strength(0.98))
    .force('x', forceX<SimNode>((node) => getLayerAnchorX(node.graphLayer)).strength(0.025))
    .force('y', forceY<SimNode>((node) => getLayerAnchorY(node.graphLayer)).strength(0.038))
    .stop()
    .tick(previousPositions.size ? 180 : 280)

  clampSimulationNodes(simNodes)

  return new Map(simNodes.map((node) => [node.id, { x: node.x || 0, y: node.y || 0 }]))
}

function runRelaxationStep(
  currentNodes: Node<GraphNodeData>[],
  graph: FilteredGraph,
  alpha: number
): Map<string, PositionXY> {
  const simNodes: SimNode[] = currentNodes.map((node) => ({
    id: node.id,
    graphLayer: node.data.graph_layer,
    radius: node.data.radius,
    x: node.position.x,
    y: node.position.y,
  }))
  const nodeIds = new Set(simNodes.map((node) => node.id))
  const simLinks = createSimulationLinks(graph.edges, nodeIds)

  forceSimulation(simNodes)
    .alpha(alpha)
    .alphaDecay(0.28)
    .velocityDecay(0.62)
    .force(
      'link',
      forceLink<SimNode, SimLink>(simLinks)
        .id((node) => node.id)
        .distance((link) => getRelationDistance(link.relType))
        .strength((link) => (link.relType === 'concept_overlap' ? 0.04 : 0.14))
    )
    .force('charge', forceManyBody<SimNode>().strength(-240))
    .force('collide', forceCollide<SimNode>().radius((node) => node.radius + 20).strength(0.92))
    .force('x', forceX<SimNode>((node) => getLayerAnchorX(node.graphLayer)).strength(0.01))
    .force('y', forceY<SimNode>((node) => getLayerAnchorY(node.graphLayer)).strength(0.016))
    .stop()
    .tick(4)

  clampSimulationNodes(simNodes)

  return new Map(simNodes.map((node) => [node.id, { x: node.x || 0, y: node.y || 0 }]))
}

function getPairKey(source: string, target: string) {
  return [source, target].sort().join('|')
}

function getPairMeta(edges: GraphEdge[]) {
  const count = new Map<string, number>()
  const seen = new Map<string, number>()
  const indexByEdgeId = new Map<string, number>()

  for (const edge of edges) {
    const key = getPairKey(edge.source, edge.target)
    count.set(key, (count.get(key) || 0) + 1)
  }

  for (const edge of edges) {
    const key = getPairKey(edge.source, edge.target)
    const index = seen.get(key) || 0
    indexByEdgeId.set(edge.id, index)
    seen.set(key, index + 1)
  }

  return { count, indexByEdgeId }
}

function getEdgeCurveOffset(index: number, total: number) {
  if (total <= 1) return 0
  return (index - (total - 1) / 2) * 24
}

function getCircleEdgePoint(center: PositionXY, radius: number, toward: PositionXY): PositionXY {
  const dx = toward.x - center.x
  const dy = toward.y - center.y
  const distance = Math.hypot(dx, dy)

  if (distance === 0) {
    return { x: center.x, y: center.y - radius }
  }

  return {
    x: center.x + (dx / distance) * radius,
    y: center.y + (dy / distance) * radius,
  }
}

function getQuadraticEdgePath(source: PositionXY, target: PositionXY, curveOffset: number) {
  const midX = (source.x + target.x) / 2
  const midY = (source.y + target.y) / 2
  const dx = target.x - source.x
  const dy = target.y - source.y
  const distance = Math.hypot(dx, dy) || 1
  const normalX = -dy / distance
  const normalY = dx / distance
  const controlX = midX + normalX * curveOffset
  const controlY = midY + normalY * curveOffset
  const labelT = 0.5
  const labelX =
    (1 - labelT) * (1 - labelT) * source.x + 2 * (1 - labelT) * labelT * controlX + labelT * labelT * target.x
  const labelY =
    (1 - labelT) * (1 - labelT) * source.y + 2 * (1 - labelT) * labelT * controlY + labelT * labelT * target.y

  return {
    labelX,
    labelY,
    path: `M ${source.x},${source.y} Q ${controlX},${controlY} ${target.x},${target.y}`,
  }
}

function syncPositionCache(nodes: Node<GraphNodeData>[], cache: Map<string, PositionXY>) {
  for (const node of nodes) {
    cache.set(node.id, node.position)
  }
}

function applyFocusToNodes(
  nodes: Node<GraphNodeData>[],
  focusNodeId: string | null,
  selectedNodeId: string | null,
  connectivity: Map<string, Set<string>>
): Node<GraphNodeData>[] {
  const focusedConnections = focusNodeId ? connectivity.get(focusNodeId) || new Set<string>() : null

  return nodes.map((node) => {
    const isFocused = focusNodeId === node.id
    const isRelated = Boolean(focusedConnections?.has(node.id))
    return {
      ...node,
      data: {
        ...node.data,
        dimmed: Boolean(focusNodeId) && !isFocused && !isRelated,
        related: isRelated,
        selected: selectedNodeId === node.id,
      },
    }
  })
}

function applyFocusToEdges(edges: Edge<GraphEdgeData>[], focusNodeId: string | null): Edge<GraphEdgeData>[] {
  return edges.map((edge) => {
    const relType = edge.data?.relType || 'direct_link'
    const isActive = Boolean(focusNodeId && (edge.source === focusNodeId || edge.target === focusNodeId))
    const isDimmed = Boolean(focusNodeId && !isActive)
    return {
      ...edge,
      data: {
        active: isActive,
        curveOffset: edge.data?.curveOffset || 0,
        dimmed: isDimmed,
        relType,
        sourceRadius: edge.data?.sourceRadius || roleRadius.concept,
        targetRadius: edge.data?.targetRadius || roleRadius.concept,
      },
      labelStyle: getEdgeLabelStyle(isActive),
      labelBgStyle: getEdgeLabelBgStyle(isActive),
      style: getEdgeVisual(relType, isActive, isDimmed),
    }
  })
}

function FilterPanel({
  filters,
  setFilters,
  availableDomains,
  showUnresolved,
  onShowUnresolvedChange,
}: {
  filters: FilterState
  setFilters: React.Dispatch<React.SetStateAction<FilterState>>
  availableDomains: string[]
  showUnresolved: boolean
  onShowUnresolvedChange: (value: boolean) => void
}) {
  const { t } = useTranslation('graph')

  const layerLabels: Record<number, string> = {
    1: t('layer.sourceNotes'),
    2: t('layer.knowledgeCards'),
    3: t('layer.knowledgeMaps'),
  }

  const toggleLayer = (layer: number) => {
    setFilters((prev) => {
      const next = new Set(prev.layers)
      if (next.has(layer)) next.delete(layer)
      else next.add(layer)
      return { ...prev, layers: next }
    })
  }

  const toggleVerification = (value: string) => {
    setFilters((prev) => {
      const next = new Set(prev.verifications)
      if (next.has(value)) next.delete(value)
      else next.add(value)
      return { ...prev, verifications: next }
    })
  }

  const toggleDomain = (domain: string) => {
    setFilters((prev) => {
      const next = new Set(prev.domains)
      if (next.has(domain)) next.delete(domain)
      else next.add(domain)
      return { ...prev, domains: next }
    })
  }

  return (
    <div className="graph-panel w-56 shrink-0 rounded-lg p-4">
      <h3 className="graph-panel-title text-sm font-semibold">{t('filter.title')}</h3>

      <div className="mt-4 space-y-2">
        <p className="graph-section-label text-xs font-medium uppercase tracking-[0.18em]">{t('filter.layer')}</p>
        {[1, 2, 3].map((layer) => (
          <label key={layer} className="graph-option flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={filters.layers.has(layer)}
              onChange={() => toggleLayer(layer)}
              className="graph-checkbox rounded"
            />
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: layerColors[layer] }} />
            <span>{layerLabels[layer]}</span>
          </label>
        ))}
      </div>

      <div className="mt-5 space-y-2">
        <p className="graph-section-label text-xs font-medium uppercase tracking-[0.18em]">{t('filter.verification')}</p>
        {FILTER_VERIFICATIONS.map((value) => (
          <label key={value} className="graph-option flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={filters.verifications.has(value)}
              onChange={() => toggleVerification(value)}
              className="graph-checkbox rounded"
            />
            <span className="h-2.5 w-2.5 rounded-full border" style={{ borderColor: verificationColors[value] }} />
            <span>{formatVerification(t, value)}</span>
          </label>
        ))}
      </div>

      {availableDomains.length > 0 && (
        <div className="mt-5 space-y-2">
          <p className="graph-section-label text-xs font-medium uppercase tracking-[0.18em]">{t('filter.domain')}</p>
          <div className="max-h-40 space-y-1 overflow-y-auto pr-1">
            {availableDomains.map((domain) => (
              <label key={domain} className="graph-option flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={filters.domains.has(domain)}
                  onChange={() => toggleDomain(domain)}
                  className="graph-checkbox rounded"
                />
                <span className="truncate">{domain}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="graph-divider mt-5 space-y-2 border-t pt-4">
        <label className="graph-option flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            checked={showUnresolved}
            onChange={(event) => onShowUnresolvedChange(event.target.checked)}
            className="graph-checkbox mt-0.5 rounded"
          />
          <span className="min-w-0">
            <span className="flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 text-rose-500" />
              {t('filter.unresolved')}
            </span>
            <span className="graph-faint mt-1 block text-[11px] leading-4">{t('filter.unresolvedHint')}</span>
          </span>
        </label>
      </div>
    </div>
  )
}

function GraphCircleNode({ data }: NodeProps<GraphNodeData>) {
  const visual = getNodeVisual(data, data.degree)
  const dimmed = data.dimmed && !data.selected
  const labelWidth = clamp(116 + data.degree * 3, 116, 172)
  const labelTop = visual.size + LABEL_GAP
  const ringWidth = data.selected ? 2.5 : data.related ? 2 : 1.5

  return (
    <div
      className="relative"
      style={{
        width: labelWidth,
        height: labelTop + 32,
        marginLeft: -(labelWidth / 2),
        marginTop: -visual.radius,
        opacity: dimmed ? 0.28 : 1,
        transition: 'opacity 120ms ease, filter 120ms ease',
        filter: dimmed ? 'saturate(0.55)' : 'none',
      }}
    >
      <Handle id="source-center" type="source" position={Position.Right} style={getCenterHandleStyle(visual.radius)} />
      <Handle id="target-center" type="target" position={Position.Left} style={getCenterHandleStyle(visual.radius)} />

      <div
        aria-hidden="true"
        className="absolute left-1/2 top-0 grid -translate-x-1/2 place-items-center rounded-full text-white"
        style={{
          width: visual.size,
          height: visual.size,
          backgroundColor: visual.fill,
          border: `${ringWidth}px solid ${visual.ringColor}`,
          boxShadow: 'none',
        }}
      >
        <span className="font-mono text-[7px] font-semibold tracking-normal text-white/90">{visual.shortLabel}</span>
      </div>

      <div
        className="absolute left-1/2 -translate-x-1/2 text-center"
        style={{ top: labelTop, width: labelWidth }}
      >
        <p className="graph-node-title truncate text-[10px] font-medium leading-4">
          {data.title}
        </p>
      </div>
    </div>
  )
}

function FloatingCircleEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  markerEnd,
  label,
  labelStyle,
  labelBgStyle,
  style,
  data,
}: EdgeProps<GraphEdgeData>) {
  const { t } = useTranslation('common')
  const sourceCenter = { x: sourceX, y: sourceY }
  const targetCenter = { x: targetX, y: targetY }
  const sourceRadius = data?.sourceRadius || roleRadius.concept
  const targetRadius = data?.targetRadius || roleRadius.concept
  const sourcePoint = getCircleEdgePoint(sourceCenter, sourceRadius, targetCenter)
  const targetPoint = getCircleEdgePoint(targetCenter, targetRadius, sourceCenter)
  const { path, labelX, labelY } = getQuadraticEdgePath(sourcePoint, targetPoint, data?.curveOffset || 0)
  const active = Boolean(data?.active)

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} interactionWidth={18} />
      {active && label && (
        <EdgeLabelRenderer>
          <div
            className="graph-edge-label nodrag nopan rounded border px-1.5 py-0.5 text-[10px] font-semibold"
            style={{
              ...labelBgStyle,
              ...labelStyle,
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              whiteSpace: 'nowrap',
            }}
          >
            {formatRelationType(t, typeof label === 'string' ? label : data?.relType)}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

function GraphDetailPanel({
  node,
  relatedEdges,
  onVerificationChange,
  onClose,
  onOpen,
}: {
  node: GraphNode
  relatedEdges: GraphEdge[]
  onVerificationChange: (nodeId: string, verification: UserVerification) => Promise<void>
  onClose: () => void
  onOpen: () => void
}) {
  const { t } = useTranslation(['graph', 'common'])
  const [updating, setUpdating] = useState<UserVerification | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const visual = getNodeVisual(node, relatedEdges.length)
  const isUnresolved = Boolean(node.unresolved)
  const relationCounts = relatedEdges.reduce<Record<string, number>>((acc, edge) => {
    acc[edge.rel_type] = (acc[edge.rel_type] || 0) + 1
    return acc
  }, {})
  const handleVerificationChange = async (verification: UserVerification) => {
    if (verification === node.verification || updating) return
    setUpdating(verification)
    setMessage(null)
    setError(null)
    try {
      await onVerificationChange(node.id, verification)
      setMessage(t('detail.updateSuccess'))
    } catch (e) {
      setError(formatApiError(t, e))
    } finally {
      setUpdating(null)
    }
  }

  return (
    <aside className="graph-detail-panel absolute right-4 top-4 z-10 w-80 rounded-lg p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="grid h-11 w-11 shrink-0 place-items-center rounded-full border font-mono text-[10px] font-semibold text-white"
            style={{
              background: visual.fill,
              borderColor: visual.ringColor,
            }}
          >
            {visual.shortLabel}
          </span>
          <div className="min-w-0">
            <h2 className="graph-detail-title truncate text-sm font-semibold">{node.title}</h2>
            <p className="graph-muted truncate text-xs">
              {isUnresolved ? t('detail.unresolvedNode') : node.domain || t('detail.noDomain')}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="graph-detail-close rounded-md p-1 transition-colors"
          aria-label={t('detail.closeDetails')}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2 text-xs">
        <div className="graph-detail-card rounded-md p-2">
          <p className="graph-muted">{t('detail.type')}</p>
          <p className="graph-detail-title mt-1 truncate font-medium">{formatNoteType(t, node.type)}</p>
        </div>
        <div className="graph-detail-card rounded-md p-2">
          <p className="graph-muted">{t('detail.layer')}</p>
          <p className="graph-detail-title mt-1 font-medium">{formatGraphLayer(t, node.graph_layer)}</p>
        </div>
        <div className="graph-detail-card rounded-md p-2">
          <p className="graph-muted">{t('detail.state')}</p>
          <p className="graph-detail-title mt-1 truncate font-medium">{formatVerification(t, node.verification)}</p>
        </div>
      </div>

      {!isUnresolved ? (
        <div className="graph-detail-card mt-4 rounded-md p-2.5">
          <p className="graph-section-label text-xs font-medium uppercase tracking-[0.18em]">{t('detail.setStatus')}</p>
          {node.verification === 'truncated' && (
            <p className="graph-warning mt-2 text-[11px] leading-4">{t('detail.truncatedHint')}</p>
          )}
          <div className="mt-2 grid grid-cols-3 gap-1.5">
            {REVIEW_STATUSES.map((status) => {
              const active = node.verification === status
              return (
                <button
                  key={status}
                  type="button"
                  disabled={active || Boolean(updating)}
                  onClick={() => void handleVerificationChange(status)}
                  className={`rounded border px-2 py-1.5 text-[10px] font-medium transition-colors ${
                    active
                      ? 'graph-review-button-active'
                      : 'graph-review-button disabled:opacity-60'
                  }`}
                >
                  {updating === status ? '...' : t(`common:reviewActions.${status}`)}
                </button>
              )
            })}
          </div>
          {message && <p className="graph-success mt-2 text-[11px]">{message}</p>}
          {error && <p className="graph-error mt-2 text-[11px]">{error}</p>}
        </div>
      ) : (
        <div className="graph-unresolved-card mt-4 rounded-md p-2.5">
          <p className="graph-error text-xs font-medium uppercase tracking-[0.18em]">{t('detail.unresolvedTitle')}</p>
          <p className="graph-muted mt-2 text-[11px] leading-4">{t('detail.unresolvedHint')}</p>
        </div>
      )}

      {Object.keys(relationCounts).length > 0 && (
        <div className="mt-4">
          <p className="graph-section-label text-xs font-medium uppercase tracking-[0.18em]">{t('detail.relations')}</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {Object.entries(relationCounts).map(([relType, count]) => {
              const relStyle = relTypeStyles[relType] || relTypeStyles.direct_link
              return (
                <span
                  key={relType}
                  className="graph-detail-title rounded-full border px-2 py-1 text-[10px] font-medium"
                  style={{
                    borderColor: `${relStyle.color}66`,
                    backgroundColor: `${relStyle.color}1f`,
                  }}
                >
                  {formatRelationType(t, relType)} x{count}
                </span>
              )
            })}
          </div>
        </div>
      )}

      {node.concepts.length > 0 && (
        <div className="mt-4">
          <p className="graph-section-label text-xs font-medium uppercase tracking-[0.18em]">{t('detail.concepts')}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {node.concepts.slice(0, 8).map((concept) => (
              <span key={concept} className="graph-concept-chip rounded-full px-2 py-1 text-[10px]">
                {concept}
              </span>
            ))}
          </div>
        </div>
      )}

      {!isUnresolved && (
        <button
          type="button"
          onClick={onOpen}
          className="graph-open-button mt-4 flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-xs font-semibold transition-colors"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          {t('detail.openNote')}
        </button>
      )}
    </aside>
  )
}

const nodeTypes: NodeTypes = { custom: GraphCircleNode }
const edgeTypes: EdgeTypes = { floating: FloatingCircleEdge }

export default function GraphView() {
  const navigate = useNavigate()
  const { instanceId } = useInstanceStore()
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNodeData>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<GraphEdgeData>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [rawData, setRawData] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null)
  const [showUnresolved, setShowUnresolved] = useState(false)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const positionCacheRef = useRef<Map<string, PositionXY>>(new Map())
  const connectivityRef = useRef<Map<string, Set<string>>>(new Map())
  const nodesRef = useRef<Node<GraphNodeData>[]>([])
  const filteredGraphRef = useRef<FilteredGraph | null>(null)
  const relaxingFrameRef = useRef<number | null>(null)
  const draggingNodeIdRef = useRef<string | null>(null)
  const hoveredNodeIdRef = useRef<string | null>(null)
  const selectedNodeIdRef = useRef<string | null>(null)
  const { t } = useTranslation(['graph', 'common'])

  const [filters, setFilters] = useState<FilterState>({
    layers: new Set([1, 2, 3]),
    domains: new Set<string>(),
    verifications: new Set(FILTER_VERIFICATIONS),
  })

  const availableDomains = useMemo(() => {
    if (!rawData) return []
    const domains = new Set<string>()
    for (const node of rawData.nodes) {
      if (!node.unresolved && node.domain) domains.add(node.domain)
    }
    return [...domains].sort()
  }, [rawData])

  const filteredGraph = useMemo<FilteredGraph | null>(() => {
    if (!rawData) return null
    const filteredNodes = rawData.nodes.filter(
      (node) =>
        (node.unresolved ? showUnresolved : filters.layers.has(node.graph_layer)) &&
        (filters.domains.size === 0 || (node.domain && filters.domains.has(node.domain))) &&
        (node.unresolved || filters.verifications.has(node.verification))
    )
    const nodeIds = new Set(filteredNodes.map((node) => node.id))
    const filteredEdges = rawData.edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target))

    return {
      nodes: filteredNodes,
      edges: filteredEdges,
      degrees: countDegrees(filteredEdges),
      nodeIds,
    }
  }, [rawData, filters, showUnresolved])

  const nodeById = useMemo(() => {
    const map = new Map<string, GraphNode>()
    for (const node of rawData?.nodes || []) {
      map.set(node.id, node)
    }
    return map
  }, [rawData])

  const selectedNode = selectedNodeId ? nodeById.get(selectedNodeId) || null : null
  const selectedRelatedEdges = useMemo(() => {
    if (!rawData || !selectedNodeId) return []
    return rawData.edges.filter((edge) => edge.source === selectedNodeId || edge.target === selectedNodeId)
  }, [rawData, selectedNodeId])
  const stats = useMemo(() => ({ nodeCount: nodes.length, edgeCount: edges.length }), [edges.length, nodes.length])

  const stopRelaxation = useCallback(() => {
    if (relaxingFrameRef.current !== null) {
      cancelAnimationFrame(relaxingFrameRef.current)
      relaxingFrameRef.current = null
    }
  }, [])

  const runInteractiveRelaxation = useCallback(() => {
    const graph = filteredGraphRef.current
    if (!graph || graph.nodes.length === 0) return

    stopRelaxation()
    const currentNodes = nodesRef.current
    if (currentNodes.length === 0) return

    let frame = 0
    const step = () => {
      if (draggingNodeIdRef.current) {
        relaxingFrameRef.current = null
        return
      }

      const alpha = 0.38 * (1 - frame / RELAX_FRAMES) + 0.025
      const positions = runRelaxationStep(nodesRef.current, graph, alpha)

      setNodes((current) => {
        const next = current.map((node) => {
          const position = positions.get(node.id)
          return position ? { ...node, position } : node
        })
        syncPositionCache(next, positionCacheRef.current)
        return next
      })

      frame += 1
      if (frame < RELAX_FRAMES) {
        relaxingFrameRef.current = requestAnimationFrame(step)
      } else {
        relaxingFrameRef.current = null
      }
    }

    relaxingFrameRef.current = requestAnimationFrame(step)
  }, [setNodes, stopRelaxation])

  const updateFocusStyles = useCallback(
    (focusNodeId: string | null, selectedId: string | null) => {
      setNodes((current) => applyFocusToNodes(current, focusNodeId, selectedId, connectivityRef.current))
      setEdges((current) => applyFocusToEdges(current, focusNodeId))
    },
    [setEdges, setNodes]
  )

  useEffect(() => {
    nodesRef.current = nodes
  }, [nodes])

  useEffect(() => {
    hoveredNodeIdRef.current = hoveredNodeId
  }, [hoveredNodeId])

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId
  }, [selectedNodeId])

  useEffect(() => {
    filteredGraphRef.current = filteredGraph
  }, [filteredGraph])

  useEffect(() => {
    return () => stopRelaxation()
  }, [stopRelaxation])

  useEffect(() => {
    if (!filteredGraph) {
      positionCacheRef.current.clear()
      connectivityRef.current.clear()
      setNodes([])
      setEdges([])
      return
    }

    const { nodes: filteredNodes, edges: filteredEdges, degrees, nodeIds } = filteredGraph
    connectivityRef.current = buildConnectivity(filteredEdges)
    const positions = applyForceLayout(filteredNodes, filteredEdges, positionCacheRef.current, degrees)
    for (const [id, position] of positions) {
      positionCacheRef.current.set(id, position)
    }

    const selectedId = selectedNodeIdRef.current
    const focusNodeId = hoveredNodeIdRef.current || selectedId
    const focusedConnections = focusNodeId ? connectivityRef.current.get(focusNodeId) || new Set<string>() : null
    const pairMeta = getPairMeta(filteredEdges)

    const flowNodes: Node<GraphNodeData>[] = filteredNodes.map((node) => {
      const degree = degrees.get(node.id) || 0
      const visual = getNodeVisual(node, degree)
      const isFocused = focusNodeId === node.id
      const isRelated = Boolean(focusedConnections?.has(node.id))
      return {
        id: node.id,
        type: 'custom',
        position: positions.get(node.id) || { x: 0, y: 0 },
        draggable: true,
        data: {
          ...node,
          degree,
          dimmed: Boolean(focusNodeId) && !isFocused && !isRelated,
          radius: visual.radius,
          related: isRelated,
          selected: selectedId === node.id,
          visualSize: visual.size,
        },
      }
    })

    const flowEdges: Edge<GraphEdgeData>[] = filteredEdges.map((edge) => {
      const isActive = Boolean(focusNodeId && (edge.source === focusNodeId || edge.target === focusNodeId))
      const isDimmed = Boolean(focusNodeId && !isActive)
      const relStyle = relTypeStyles[edge.rel_type] || relTypeStyles.direct_link
      const pairKey = getPairKey(edge.source, edge.target)
      const pairCount = pairMeta.count.get(pairKey) || 1
      const pairIndex = pairMeta.indexByEdgeId.get(edge.id) || 0
      const sourceNode = nodeById.get(edge.source)
      const targetNode = nodeById.get(edge.target)
      const sourceDegree = degrees.get(edge.source) || 0
      const targetDegree = degrees.get(edge.target) || 0
      const sourceRadius = sourceNode ? getNodeVisual(sourceNode, sourceDegree).radius : roleRadius.concept
      const targetRadius = targetNode ? getNodeVisual(targetNode, targetDegree).radius : roleRadius.concept

      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: 'source-center',
        targetHandle: 'target-center',
        type: 'floating',
        label: edge.rel_type,
        labelStyle: getEdgeLabelStyle(isActive),
        labelBgStyle: getEdgeLabelBgStyle(isActive),
        markerEnd: relStyle.arrow ? { type: MarkerType.ArrowClosed, color: relStyle.color, width: 16, height: 16 } : undefined,
        style: getEdgeVisual(edge.rel_type, isActive, isDimmed),
        data: {
          active: isActive,
          curveOffset: getEdgeCurveOffset(pairIndex, pairCount),
          dimmed: isDimmed,
          relType: edge.rel_type,
          sourceRadius,
          targetRadius,
        },
      }
    })

    setNodes(flowNodes)
    setEdges(flowEdges)

    if (selectedId && !nodeIds.has(selectedId)) {
      setSelectedNodeId(null)
    }
  }, [filteredGraph, nodeById, setEdges, setNodes])

  useEffect(() => {
    const focusNodeId = hoveredNodeId || selectedNodeId
    updateFocusStyles(focusNodeId, selectedNodeId)
  }, [hoveredNodeId, selectedNodeId, updateFocusStyles])

  const openNote = useCallback(
    (id: string) => {
      navigate(`/note/${encodeURIComponent(id)}`, {
        state: { returnLabelKey: 'noteDetail:return.graph', returnTo: '/graph' },
      })
    },
    [navigate]
  )

  const updateNodeVerification = useCallback(
    async (nodeId: string, verification: UserVerification) => {
      if (!instanceId) return
      const updatedNote = await updateNoteVerification(instanceId, nodeId, verification)
      setRawData((current) => {
        if (!current) return current
        return {
          ...current,
          nodes: current.nodes.map((node) =>
            node.id === nodeId ? { ...node, verification: updatedNote.verification } : node
          ),
        }
      })
    },
    [instanceId]
  )

  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes)
    },
    [onNodesChange]
  )

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id)
  }, [])

  const onNodeDoubleClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if ((node.data as GraphNodeData | undefined)?.unresolved) return
      openNote(node.id)
    },
    [openNote]
  )

  const onNodeMouseEnter = useCallback((_: React.MouseEvent, node: Node) => {
    setHoveredNodeId((current) => (current === node.id ? current : node.id))
  }, [])

  const onNodeMouseLeave = useCallback(() => {
    setHoveredNodeId((current) => (current === null ? current : null))
  }, [])

  const onNodeDragStart = useCallback(
    (_: React.MouseEvent, node: Node<GraphNodeData>) => {
      stopRelaxation()
      draggingNodeIdRef.current = node.id
      positionCacheRef.current.set(node.id, node.position)
    },
    [stopRelaxation]
  )

  const onNodeDrag = useCallback((_: React.MouseEvent, node: Node<GraphNodeData>) => {
    positionCacheRef.current.set(node.id, node.position)
  }, [])

  const onNodeDragStop = useCallback(
    (_: React.MouseEvent, node: Node<GraphNodeData>) => {
      draggingNodeIdRef.current = null
      positionCacheRef.current.set(node.id, node.position)
      runInteractiveRelaxation()
    },
    [runInteractiveRelaxation]
  )

  useEffect(() => {
    if (!instanceId) {
      return
    }

    let cancelled = false
    queueMicrotask(() => {
      if (cancelled) return
      setLoading(true)
      setLoadError(null)
      getGraph(instanceId, { include_unresolved: showUnresolved })
        .then((data) => {
          if (!cancelled) setRawData(data)
        })
        .catch((e) => {
          if (cancelled) return
          setRawData(null)
          setLoadError(formatApiError(t, e))
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
    })
    return () => { cancelled = true }
  }, [instanceId, showUnresolved, t])

  if (!instanceId) {
    return <p className="text-muted-foreground text-sm">{t('common:selectInstance')}</p>
  }

  if (loading) return <LoadingState />

  if (loadError) {
    return <div className="rounded-md bg-error/10 p-3 text-sm text-error">{loadError}</div>
  }

  return (
    <div className="graph-page h-[calc(100vh-8rem)] min-h-0">
      <div className="flex h-full gap-3">
        <FilterPanel
          filters={filters}
          setFilters={setFilters}
          availableDomains={availableDomains}
          showUnresolved={showUnresolved}
          onShowUnresolvedChange={setShowUnresolved}
        />

        <div className="graph-canvas relative min-w-0 flex-1 overflow-hidden rounded-lg">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={handleNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onNodeDoubleClick={onNodeDoubleClick}
            onNodeMouseEnter={onNodeMouseEnter}
            onNodeMouseLeave={onNodeMouseLeave}
            onNodeDragStart={onNodeDragStart}
            onNodeDrag={onNodeDrag}
            onNodeDragStop={onNodeDragStop}
            onPaneClick={() => setSelectedNodeId(null)}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.28 }}
            minZoom={0.25}
            maxZoom={1.6}
            proOptions={{ hideAttribution: true }}
          >
            <Background
              variant={BackgroundVariant.Dots}
              gap={24}
              size={1}
              color="var(--graph-grid)"
            />
            <Controls className="graph-controls" />
            <MiniMap
              pannable
              zoomable
              nodeColor={(node) => getNodeVisual(node.data as GraphNode, (node.data as GraphNodeData).degree).color}
              maskColor="var(--graph-minimap-mask)"
              className="graph-minimap"
            />
          </ReactFlow>

          <div className="graph-stat pointer-events-none absolute left-4 top-4 rounded-lg px-3 py-2 text-xs">
            <span className="graph-stat-strong font-semibold">{stats.nodeCount}</span> {t('status.nodesUnit')}
            <span className="graph-faint mx-2">/</span>
            <span className="graph-stat-strong font-semibold">{stats.edgeCount}</span> {t('status.relationsUnit')}
          </div>

          {selectedNode && (
            <GraphDetailPanel
              node={selectedNode}
              relatedEdges={selectedRelatedEdges}
              onVerificationChange={updateNodeVerification}
              onClose={() => setSelectedNodeId(null)}
              onOpen={() => openNote(selectedNode.id)}
            />
          )}
        </div>
      </div>
    </div>
  )
}
