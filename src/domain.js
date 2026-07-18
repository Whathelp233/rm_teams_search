export function canonicalPoint(x, y, side) {
  return side === '蓝' ? [28 - x, 15 - y] : [x, y]
}

// Official coordinates use +Y toward the red helipad, while SVG/image pixels
// increase downward. The competition-map image therefore needs a vertical flip.
export function officialToMap(x, y) {
  return [x, 15 - y]
}

// A dual-team timeline must rotate the entire world, never one side at a time.
// This keeps opponents on opposite sides in the selected team's perspective.
export function teamPerspectivePoint(x, y, selectedSide) {
  return selectedSide === '蓝' ? [28 - x, y] : officialToMap(x, y)
}

export function aggregateHeatCells(cells, project, mergeSides = false) {
  const result = new Map()
  for (const cell of cells) {
    const [x, y] = project(cell)
    const side = mergeSides ? '己' : cell[0]
    const key = `${side}:${x}:${y}`
    const previous = result.get(key)
    if (previous) previous.samples += cell[5]
    else result.set(key, { side, x, y, samples: cell[5] })
  }
  return [...result.values()]
}

export function densityOpacity(samples, maximum) {
  const normalized = Math.log1p(samples) / Math.log1p(Math.max(1, maximum))
  return Math.max(.025, Math.min(.88, normalized * normalized * .88))
}

export function reliabilityTone(grade) {
  return ['A', 'B'].includes(grade) ? 'good' : grade === 'C' ? 'warn' : 'bad'
}
