// One place for every color and chart style, so the whole dashboard reads as one system.

export const COLORS = {
  // Status palette: always means good / middling / bad, never a category
  good: '#4A7C59',
  mid: '#B07D3A',
  midWarm: '#C4873A',
  bad: '#9B3D2B',
  goodBg: '#D6EAD9',
  goodText: '#2D5E38',
  midBg: '#F0E2C8',
  midText: '#7A4F1A',
  badBg: '#EDD5CF',
  badText: '#6B2418',

  // Categorical palette, used in order
  cat: ['#2D7A74', '#5C5D5A', '#8C7355', '#5B7FA6', '#7D6A8A', '#A67C6D', '#4A6741', '#7A6040', '#3D6B78'],

  gridLine: 'rgba(0,0,0,0.06)',
  axisLabel: '#52525B',
  ink: '#18181B',
}

// Your store vs the competition, everywhere
export const HOME_COLOR = COLORS.cat[0]
export const COMPETITOR_COLOR = COLORS.cat[2]
export const COMPETITOR_TEXT = '#6B5A45'

export const CHART_COLORS = COLORS.cat
export const CHART_COLORS_DESAT = ['#6BADA8', '#8E8F8C', '#B9A688', '#8EA8C6', '#A99AB2', '#C4A99C', '#7E9477', '#A88E72', '#6E9BA5']

export const AGE_BUCKETS = ['0-30', '31-60', '61-90', '90+']
export const AGE_COLORS = {
  '0-30': COLORS.good,
  '31-60': COLORS.mid,
  '61-90': COLORS.midWarm,
  '90+': COLORS.bad,
}

export function ageBucket(days) {
  if (days == null) return null
  if (days <= 30) return '0-30'
  if (days <= 60) return '31-60'
  if (days <= 90) return '61-90'
  return '90+'
}

// Days-on-lot color for bars
export function daysFill(days) {
  if (days <= 30) return COLORS.good
  if (days <= 60) return COLORS.mid
  if (days <= 90) return COLORS.midWarm
  return COLORS.bad
}

// Days-on-lot color for text
export function daysTextColor(days) {
  if (days == null) return '#71717A'
  return daysFill(days)
}

export const TOOLTIP_STYLE = {
  borderRadius: 10,
  border: '1px solid #E4E4E7',
  boxShadow: '0 4px 16px rgb(0 0 0 / 0.08)',
  fontSize: 14,
  padding: '8px 12px',
}

export const GRID_STROKE = COLORS.gridLine
export const AXIS_TICK = { fontSize: 13, fill: COLORS.axisLabel }
