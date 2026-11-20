import assert from 'node:assert/strict';
import test from 'node:test';
import { readStationLink, stationHref } from './stationLink.ts';
import { scenarioComparisonHref } from './campaignHistory.ts';

test('a shared measurement link retains both run identities and exact recorded coordinates, including the clamp', () => {
  const replay = scenarioComparisonHref('p', 'batch', 'tip/load', 'mid/load');
  assert.equal(readStationLink(replay), null);
  const pair = { reference: 'tip/load', comparison: 'mid/load', leftM: 0, rightM: 0.30000000000000004 };
  assert.deepEqual(readStationLink(stationHref(replay, pair.reference, pair.leftM, pair.rightM)), pair);
  assert.equal(readStationLink(replay + '&referenceStationM=-1&comparisonStationM=0'), null);
  assert.equal(readStationLink(replay + '&referenceStationM=&comparisonStationM=0'), null);
});
