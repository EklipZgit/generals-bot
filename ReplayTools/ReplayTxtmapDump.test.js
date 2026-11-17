// Roundtrip tests for ReplayTxtmapDump.js board-orientation transforms.
// Run: node ReplayTools/ReplayTxtmapDump.test.js
// Covers every canonical tile index on several rectangular dims for all six
// orientations, plus display-dim swapping and known coordinate mappings used by
// the truemap grid, general markers, and recorded-move coordinates.

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const {
  ORIENTATIONS,
  displayDims,
  canonToDisplayIndex,
  displayToCanonIndex,
  normalizeOrientation,
  displayXYFromCanon,
  verifyAgainstBotMap,
  dumpTxtmap,
  parseTxtmap,
} = require('./ReplayTxtmapDump');

const DIMS = [
  [1, 1],
  [2, 5],
  [5, 2],
  [5, 3],
  [3, 5],
  [7, 4],
  [4, 7],
  [26, 25],
  [25, 26],
];

let checks = 0;

for (const [w, h] of DIMS) {
  for (const orientation of ORIENTATIONS) {
    const [dispW, dispH] = displayDims(w, h, orientation);
    const swapsDims = orientation === 'rot90cw' || orientation === 'rot90ccw' || orientation === 'antiTranspose';
    assert.strictEqual(dispW, swapsDims ? h : w, `displayDims width ${orientation} ${w}x${h}`);
    assert.strictEqual(dispH, swapsDims ? w : h, `displayDims height ${orientation} ${w}x${h}`);

    for (let index = 0; index < w * h; index++) {
      const displayIndex = canonToDisplayIndex(index, w, h, orientation);
      assert.ok(
        displayIndex >= 0 && displayIndex < dispW * dispH,
        `${orientation} ${w}x${h} index ${index} -> ${displayIndex} out of range`);
      const back = displayToCanonIndex(displayIndex, dispW, w, h, orientation);
      assert.strictEqual(
        back, index,
        `${orientation} roundtrip failed ${w}x${h}: ${index} -> ${displayIndex} -> ${back}`);
      checks++;
    }
  }
}

// mirrorX/rot180 are involutions on the canonical frame: applying the display
// transform twice must return the original index.
for (const orientation of ['none', 'mirrorX', 'rot180']) {
  for (const [w, h] of DIMS) {
    for (let index = 0; index < w * h; index++) {
      const once = canonToDisplayIndex(index, w, h, orientation);
      const twice = canonToDisplayIndex(once, w, h, orientation);
      assert.strictEqual(twice, index, `${orientation} not an involution at ${index}`);
      checks++;
    }
  }
}

// Known coordinate mappings (canonical x,y -> display x,y) on a 5x3 map.
// rot90cw: canonical (x,y) -> display (h-1-y, x) = (2-y, x)
// rot90ccw: canonical (x,y) -> display (y, w-1-x) = (y, 4-x)
// antiTranspose: canonical (x,y) -> display (h-1-y, w-1-x) = (2-y, 4-x)
function displayXY(index, w, h, orientation) {
  const [dw] = displayDims(w, h, orientation);
  const d = canonToDisplayIndex(index, w, h, orientation);
  return [d % dw, Math.floor(d / dw)];
}

const canonIndex = (x, y, w) => y * w + x;

// canonical (0,0): cw -> display (2,0); ccw -> display (0,4)
assert.deepStrictEqual(displayXY(canonIndex(0, 0, 5), 5, 3, 'rot90cw'), [2, 0]);
assert.deepStrictEqual(displayXY(canonIndex(0, 0, 5), 5, 3, 'rot90ccw'), [0, 4]);
assert.deepStrictEqual(displayXY(canonIndex(0, 0, 5), 5, 3, 'antiTranspose'), [2, 4]);
// canonical (4,2) bottom-right: cw -> (0,4); ccw -> (2,0); antiTranspose -> (0,0)
assert.deepStrictEqual(displayXY(canonIndex(4, 2, 5), 5, 3, 'rot90cw'), [0, 4]);
assert.deepStrictEqual(displayXY(canonIndex(4, 2, 5), 5, 3, 'rot90ccw'), [2, 0]);
assert.deepStrictEqual(displayXY(canonIndex(4, 2, 5), 5, 3, 'antiTranspose'), [0, 0]);
// canonical (2,1) exact center maps to display center (1,2) under all three swaps
assert.deepStrictEqual(displayXY(canonIndex(2, 1, 5), 5, 3, 'rot90cw'), [1, 2]);
assert.deepStrictEqual(displayXY(canonIndex(2, 1, 5), 5, 3, 'rot90ccw'), [1, 2]);
assert.deepStrictEqual(displayXY(canonIndex(2, 1, 5), 5, 3, 'antiTranspose'), [1, 2]);
// mirrorX on (0,0) -> (4,0); rot180 -> (4,2)
assert.deepStrictEqual(displayXY(canonIndex(0, 0, 5), 5, 3, 'mirrorX'), [4, 0]);
assert.deepStrictEqual(displayXY(canonIndex(0, 0, 5), 5, 3, 'rot180'), [4, 2]);
checks += 6;

// ---------------------------------------------------------------------------
// Orientation validation + display-frame coordinate seam
// ---------------------------------------------------------------------------

assert.strictEqual(normalizeOrientation(undefined), 'none');
assert.strictEqual(normalizeOrientation(''), 'none');
assert.strictEqual(normalizeOrientation('rot90cw'), 'rot90cw');
assert.strictEqual(normalizeOrientation('antiTranspose'), 'antiTranspose');
assert.strictEqual(normalizeOrientation('mirrorX'), 'mirrorX');
assert.throws(() => normalizeOrientation('bogus'), /unknown orientation/);
assert.throws(() => normalizeOrientation('ROT90CW'), /unknown orientation/);
assert.throws(() => normalizeOrientation('rot90'), /unknown orientation/);
checks += 6;

// displayXYFromCanon: canonical index -> {x, y} in the display frame. These are
// the exact transforms applied to General= footer fields and --moves-turns
// recorded endpoints, so a wrong mapping corrupts both.
// 5x3 canonical under rot90cw -> 3x5 display.
assert.deepStrictEqual(displayXYFromCanon(10, 5, 3, 'rot90cw'), { x: 0, y: 0 });
assert.deepStrictEqual(displayXYFromCanon(14, 5, 3, 'rot90cw'), { x: 0, y: 4 });
assert.deepStrictEqual(displayXYFromCanon(10, 5, 3, 'rot90ccw'), { x: 2, y: 4 });
assert.deepStrictEqual(displayXYFromCanon(14, 5, 3, 'rot90ccw'), { x: 2, y: 0 });
assert.deepStrictEqual(displayXYFromCanon(10, 5, 3, 'antiTranspose'), { x: 0, y: 4 });
assert.deepStrictEqual(displayXYFromCanon(14, 5, 3, 'antiTranspose'), { x: 0, y: 0 });
assert.deepStrictEqual(displayXYFromCanon(0, 5, 3, 'mirrorX'), { x: 4, y: 0 });
assert.deepStrictEqual(displayXYFromCanon(0, 5, 3, 'rot180'), { x: 4, y: 2 });
assert.deepStrictEqual(displayXYFromCanon(7, 5, 3, 'none'), { x: 2, y: 1 });
checks += 7;

// ---------------------------------------------------------------------------
// dumpTxtmap / verifyAgainstBotMap on a fake 5x3 canonical game
// ---------------------------------------------------------------------------

// Minimal fake of the generals-events sim objects dumpTxtmap/verify read.
// _map holds owner index (>=0) or a negative terrain code; _armies holds counts.
const FAKE_MAP = { TILE_MOUNTAIN: -1, TILE_LOOKOUT: -2, TILE_OBSERVATORY: -3 };

function fakeGame(width, height, ownerAt, armyAt, generals) {
  const size = width * height;
  // -99 is deliberately not any FAKE_MAP terrain code: unowned cells must
  // fall through cellForCanon's terrain switch to the empty-cell default.
  const mapCells = new Array(size).fill(-99);
  const armies = new Array(size).fill(0);
  for (const [index, owner] of Object.entries(ownerAt)) {
    mapCells[Number(index)] = owner;
  }
  for (const [index, army] of Object.entries(armyAt)) {
    armies[Number(index)] = army;
  }
  return {
    map: {
      width,
      height,
      _map: mapCells,
      _armies: armies,
      getTunnelLimit: () => 0,
      getStrongholdStrength: () => 0,
    },
    citySet: new Set(),
    swamps: [],
    deserts: [],
    generals,
    sockets: generals.map(() => ({ dead: false })),
    scores: generals.map(() => ({ total: 0, tiles: 0 })),
    cities: [],
  };
}

const FAKE_REPLAY = {
  id: 'TESTREPLAY',
  usernames: ['p0', 'p1'],
  teams: null,
  modifiers: [],
  afks: [],
  stars: [1, 1],
};

// 5x3 canonical: p0 general at canon index 10 = (x0,y2), p1 at 14 = (x4,y2).
// Under rot90cw the display frame is 3 wide x 5 tall.
const dumpGame = fakeGame(
  5, 3,
  { 10: 0, 14: 1 },
  { 10: 3, 14: 7 },
  [10, 14]);
const dumpOut = dumpTxtmap(dumpGame, FAKE_MAP, FAKE_REPLAY, 31, 0, {}, 'rot90cw');
const dumpLines = dumpOut.split('\n');

// Grid dims: the border bars carry one '|' per display column, and the rows
// between them must number displayHeight (5 for rot90cw on 5x3).
const barLine = dumpLines[0];
assert.strictEqual((barLine.match(/\|/g) || []).length, 3,
  `rot90cw dump bar should have 3 display columns, got '${barLine}'`);
const closingBarIndex = dumpLines.indexOf(barLine, 1);
assert.strictEqual(closingBarIndex, 6, `expected 5 grid rows between bars, layout: ${dumpLines.slice(0, 8).join('|')}`);
// canon (0,2) -> display (0,0): cellForCanon emits owner+G+army ('aG3') leading
// row 0; canon (4,2) -> display (0,4): 'bG7' leads the last row.
assert.ok(dumpLines[1].startsWith('aG3'), `row0 should start with aG3, got '${dumpLines[1]}'`);
assert.ok(dumpLines[5].startsWith('bG7'), `row4 should start with bG7, got '${dumpLines[5]}'`);
checks += 4;

// General= footer fields are display-frame coords for the same orientation.
assert.ok(dumpOut.includes('aGeneral=0,0'), `expected aGeneral=0,0 in dump:\n${dumpOut}`);
assert.ok(dumpOut.includes('bGeneral=0,4'), `expected bGeneral=0,4 in dump:\n${dumpOut}`);
checks += 2;

// verifyAgainstBotMap must reject a bot grid whose dims do not equal the
// orientation's display dims BEFORE comparing cells - on rectangular boards a
// wrong orientation would otherwise alias rows.
const verifyGame = fakeGame(5, 3, { 10: 0 }, { 10: 1 }, [-1, -1]);
// Correct dims (3x5) with one own cell whose true cell matches: no errors.
const goodGrid = [
  ['a1', '', ''],
  ['', '', ''],
  ['', '', ''],
  ['', '', ''],
  ['', '', ''],
];
const goodErrors = verifyAgainstBotMap(verifyGame, FAKE_MAP,
  { grid: goodGrid }, 0, 'rot90cw');
assert.deepStrictEqual(goodErrors, [], `expected no verify errors, got ${goodErrors}`);
checks += 1;

// Wrong dims for the same orientation (e.g. a 'none'-frame 5x3 grid offered
// under rot90cw, or vice versa) must produce a dimension error, not cell diffs.
const wrongDimsGrid = [
  ['a1', '', '', '', ''],
  ['', '', '', '', ''],
  ['', '', '', '', ''],
];
const dimErrors = verifyAgainstBotMap(verifyGame, FAKE_MAP,
  { grid: wrongDimsGrid }, 0, 'rot90cw');
assert.strictEqual(dimErrors.length, 1, `expected single dim error, got ${dimErrors}`);
assert.ok(dimErrors[0].includes('3x5'), `dim error should name expected 3x5 dims, got '${dimErrors[0]}'`);
// The canonical-orientation grid also fails under 'none' expectations.
const noneErrors = verifyAgainstBotMap(verifyGame, FAKE_MAP,
  { grid: goodGrid }, 0, 'none');
assert.strictEqual(noneErrors.length, 1, `expected single dim error for none, got ${noneErrors}`);
assert.ok(noneErrors[0].includes('5x3'), `dim error should name expected 5x3 dims, got '${noneErrors[0]}'`);
checks += 3;

// ---------------------------------------------------------------------------
// parseTxtmap ragged rows: the game client trims trailing empty cells, so a
// grid row can be shorter than the header-declared width. parseTxtmap must pad
// the missing trailing cells out to width * cellWidth with blank cells,
// mirroring Python TextMapLoader. Oversized rows must stay oversized so strict
// verification keeps rejecting them. Regression for the 50ZwYtndy truemap dump
// failure ("bot grid is 25x29 but none expects 26x29"): trimmed trailing
// neutral/fog columns produced ragged 25-cell rows under a 26-wide header.
// ---------------------------------------------------------------------------

const raggedDir = fs.mkdtempSync(path.join(os.tmpdir(), 'replay-txtmap-dump-'));
try {
  const raggedPath = path.join(raggedDir, 'ragged.txtmap');
  fs.writeFileSync(raggedPath, [
    '|   |   |   |   ',
    'aG1',
    'M   bG1',
    '',
    '|   |   |   |   ',
    'turn=179',
    '',
  ].join('\n'));
  const parsed = parseTxtmap(raggedPath);
  assert.strictEqual(parsed.width, 4, `expected header width 4, got ${parsed.width}`);
  assert.strictEqual(parsed.grid.length, 3, `expected 3 grid rows, got ${parsed.grid.length}`);
  for (const row of parsed.grid) {
    assert.strictEqual(row.length, 4, `expected 4 cells per row, got ${row.length}: ${JSON.stringify(row)}`);
  }
  // First tokens preserved; each cell padded to cellWidth (4) with blanks.
  assert.strictEqual(parsed.grid[0][0], 'aG1 ', `row0 cell0 should be 'aG1 ', got '${parsed.grid[0][0]}'`);
  assert.strictEqual(parsed.grid[1][0], 'M   ', `row1 cell0 should be 'M   ', got '${parsed.grid[1][0]}'`);
  assert.strictEqual(parsed.grid[1][1], 'bG1 ', `row1 cell1 should be 'bG1 ', got '${parsed.grid[1][1]}'`);
  // Every trimmed/missing trailing cell must be a blank 4-char cell.
  const blankCells = [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 0], [2, 1], [2, 2], [2, 3]];
  for (const [r, x] of blankCells) {
    assert.strictEqual(parsed.grid[r][x], '    ', `grid[${r}][${x}] should be blank, got '${parsed.grid[r][x]}'`);
  }
  assert.strictEqual(parsed.data.turn, '179', `footer turn should be '179', got '${parsed.data.turn}'`);
  checks += 18;
} finally {
  fs.rmSync(raggedDir, { recursive: true, force: true });
}

console.log(`ReplayTxtmapDump orientation tests: ${checks} checks passed`);
