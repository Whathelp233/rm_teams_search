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

export function reliabilityTone(grade) {
  return ['A', 'B'].includes(grade) ? 'good' : grade === 'C' ? 'warn' : 'bad'
}
