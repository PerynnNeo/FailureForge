export type StationPairLink = { reference: string; comparison: string; leftM: number; rightM: number };

export function readStationLink(hash: string): StationPairLink | null {
  const query = new URLSearchParams(hash.split('?')[1]);
  const reference = query.get('reference'), comparison = query.get('run');
  const left = query.get('referenceStationM'), right = query.get('comparisonStationM');
  if (!reference || !comparison || reference === comparison || !left?.trim() || !right?.trim()) return null;
  const leftM = Number(left), rightM = Number(right);
  return [leftM, rightM].every(n => Number.isFinite(n) && n >= 0) ? { reference, comparison, leftM, rightM } : null;
}

export function stationHref(batchHref: string, reference: string, leftM: number, rightM: number) {
  const [route, search] = batchHref.split('?');
  const query = new URLSearchParams(search);
  query.set('reference', reference);
  query.set('referenceStationM', String(leftM));
  query.set('comparisonStationM', String(rightM));
  return route + '?' + query;
}
