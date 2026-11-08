const normalize = text => (text || '').trim().toLowerCase().replace(/[\s_-]+/g, ' ')

function transposed(wanted, candidate) {
  if (wanted.length < 6 || wanted.length !== candidate.length) return false
  const different = [...wanted].flatMap((letter, index) => letter === candidate[index] ? [] : [index])
  if (different.length !== 2 || different[1] !== different[0] + 1) return false
  const [first, second] = different
  return /[a-z]/i.test(wanted[first]) && /[a-z]/i.test(wanted[second]) && wanted[first] === candidate[second] && wanted[second] === candidate[first]
}

// Uses aliases supplied by the catalog API; agrees with Catalog.resolve_trade.
export function resolveTrade(trades, text) {
  const wanted = normalize(text)
  if (!wanted) return null
  const labels = trades.map(trade => ({ id: trade.id, values: [trade.id, trade.name, ...(trade.aliases || [])].map(normalize) }))
  const exact = labels.filter(trade => trade.values.includes(wanted))
  if (exact.length) return exact.length === 1 ? exact[0].id : null
  const close = labels.filter(trade => trade.values.some(value => transposed(wanted, value)))
  return close.length === 1 ? close[0].id : null
}
