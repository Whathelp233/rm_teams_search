export function canonicalPoint(x, y, side) {
  return side === '蓝' ? [28 - x, 15 - y] : [x, y]
}

export function reliabilityTone(grade) {
  return ['A', 'B'].includes(grade) ? 'good' : grade === 'C' ? 'warn' : 'bad'
}
