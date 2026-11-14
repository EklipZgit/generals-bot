'use strict';

// CLI tool: downloads a .gior replay (or reads a local one), runs the
// generals-events replay simulator to a given turn, and dumps the TRUE map
// state in the .txtmap format used by this repo's test suite.
//
// This file lives in the bot repo, but the replay simulator and deserializer
// live in the public generals-events repo. Module loads are anchored at
// <generals-events>/functions/src/util/ resolved (in order) from:
//   1. --generals-events-repo <path>
//   2. the `generals_events_repo` key in run_config.txt (the same
//      key=value file run-bot.ps1 reads, one folder above this repo)
//   3. <repo_root>/../generals/generals-events (repo_root also from
//      run_config.txt, defaulting to this repo's own root)
//
// Replay acquisition mirrors ReplayLoader's bounded policy: for each server
// region it tries S3 -> (only when /api/serverSettings reports
// aws_replay_saving_down) the game-server /api/replay backup -> S3 once more.
// 'auto' walks the known regions in order, after checking the local on-disk
// replay_data/ fallback used while AWS replay saving is down. replay_data is
// written by the (private) game server repo, so it resolves as the parent of
// the generals-events checkout - which is exactly the layout used when the
// events package is developed inside the game repo.
//
// Usage:
//   node ReplayTxtmapDump.js --replay-id <id> [--server auto|na|eu|bot|ek|loc]
//       --turn <n> [--player-index <i>] --out <file.txtmap>
//       [--save-replay <file.gior>] [--copy-data-from <botmap.txtmap>]
//       [--generals-events-repo <path>] [--replay-file <file.gior>]
//
// --copy-data-from inherits footer keys the simulator cannot know (bot
// metadata like PATHABLE_CITY_THRESHOLD, bot_target_player, per-player
// AggressionFactor/Delta25*/KnowsKingLocation/etc.) and cross-checks the
// visible board state: every non-'D' tile owned by player_index in the bot
// txtmap plus all {c}Score/{c}Tiles values must match the simulated truth or
// the dump is rejected - that keeps turn off-by-ones from silently writing
// subtly-wrong "true" maps.

const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');

const REPLAY_ID = /^[A-Za-z0-9_-]{1,200}$/;
const REAL_SERVERS = ['na', 'bot', 'eu', 'ek'];

const BACKUP_ORIGINS = {
  na: 'https://generals.io',
  eu: 'https://eu.generals.io',
  bot: 'https://bot.generals.io',
  ek: 'http://45.50.38.248:8080',
};

const PLAYER_CHARS = 'abcdefghijklmnop';

// Footer keys copied verbatim from the bot's exported txtmap: they encode
// game options or bot-side metadata that the true-state dump must carry over
// so the test loader sees the same game configuration.
const COPIED_SCALAR_KEYS = [
  'PATHABLE_CITY_THRESHOLD',
  'bot_target_player',
  'mode',
  'teams',
  'walled_city_base_value',
  'is_custom_map',
  'spawn_fairness',
  'modifiers',
];

// Per-player footer keys that describe bot-side estimation, not board truth.
// The simulated truth cannot produce them but the test loader reads them, so
// they pass through unchanged when present.
const COPIED_PLAYER_SUFFIXES = [
  'AggressionFactor',
  'Delta25Tiles',
  'Delta25Score',
  'CityGainedTurn',
  'CityLostTurn',
  'LastSeenMoveTurn',
  'KnowsKingLocation',
  'KnowsAllyKingLocation',
];

function parseArgs(argv) {
  const args = { server: 'auto', verify: true };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('--')) {
      throw new Error(`unexpected argument ${arg}`);
    }
    const key = arg.slice(2);
    if (key === 'no-verify') {
      args.verify = false;
      continue;
    }
    if (i + 1 >= argv.length) {
      throw new Error(`missing value for ${arg}`);
    }
    args[key.replace(/-([a-z])/g, (m, c) => c.toUpperCase())] = argv[++i];
  }
  return args;
}

// Reads the key=value run_config.txt kept one folder above the bot repo
// (same file Initialize-RunConfig parses in run-bot.ps1). Missing file
// yields an empty config.
function readRunConfig(configPath) {
  const config = {};
  let lines;
  try {
    lines = fs.readFileSync(configPath, 'utf8').split(/\r?\n/);
  } catch (error) {
    return config;
  }
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }
    const sep = line.indexOf('=');
    if (sep < 0) {
      continue;
    }
    const key = line.slice(0, sep).trim();
    if (key) {
      config[key] = line.slice(sep + 1).trim();
    }
  }
  return config;
}

// Resolves the generals-events repo checkout: --generals-events-repo flag,
// then run_config.txt's generals_events_repo key, then the sibling layout
// <repo_root>/../generals/generals-events.
function resolveGeneralsEventsRepo(args) {
  if (args.generalsEventsRepo) {
    return args.generalsEventsRepo;
  }
  const config = readRunConfig(
    path.resolve(__dirname, '..', '..', 'run_config.txt'));
  const repoRoot = config.repo_root || path.resolve(__dirname, '..');
  const configured = config.generals_events_repo
      || path.join(repoRoot, '..', 'generals', 'generals-events');
  return configured.replace(/[\\/]+$/, '');
}

// All generals-events modules (and their own dependencies like axios) are
// required through an anchor inside the events package's util dir, so its
// node_modules resolution and relative requires behave exactly as if this
// file still lived there.
function loadEventsDeps(generalsEventsRepo) {
  const utilDir = path.join(
    generalsEventsRepo, 'functions', 'src', 'util');
  const eventsRequire = createRequire(path.join(utilDir, 'anchor.js'));
  return {
    axios: eventsRequire('axios').default,
    ReplayDeserializer: eventsRequire('./ReplayDeserializer'),
    EventReplaySimulation: eventsRequire('./EventReplaySimulation'),
    Map: eventsRequire('./Map'),
  };
}

async function fetchBytes(axios, url) {
  const response = await axios.get(url,
    { responseType: 'arraybuffer', timeout: 15000, maxRedirects: 0 });
  const data = response.data;
  const bytes = ArrayBuffer.isView(data)
      ? Buffer.from(data.buffer, data.byteOffset, data.byteLength)
      : Buffer.from(data);
  if (!bytes.byteLength) {
    throw new Error('empty replay body');
  }
  return bytes;
}

async function savingDown(axios, origin) {
  try {
    const response = await axios.get(`${origin}/api/serverSettings`,
      { timeout: 10000, maxRedirects: 0 });
    return response.data && response.data.aws_replay_saving_down === true;
  } catch (error) {
    return false;
  }
}

// The local-disk fallback the game server writes while AWS replay saving is
// down (ReplayStorage): <replay_data>/<serverId>/<id>/replay.gior. Any
// serverId folder holding the id counts - bot games on a local dev server
// land in 'dev' but a prod-name serverId works too.
function findLocalReplayBytes(replayDataRoot, replayId) {
  let serverDirs;
  try {
    serverDirs = fs.readdirSync(replayDataRoot, { withFileTypes: true });
  } catch (error) {
    return null;
  }
  for (const entry of serverDirs) {
    if (!entry.isDirectory()) {
      continue;
    }
    const candidate = path.join(replayDataRoot, entry.name, replayId, 'replay.gior');
    try {
      const bytes = fs.readFileSync(candidate);
      if (bytes.byteLength) {
        return { bytes, source: `local:${candidate}` };
      }
    } catch (error) {
      // Absent or unreadable entry; keep scanning other server folders.
    }
  }
  return null;
}

async function fetchRemoteReplay(axios, replayId, server) {
  const s3 = `https://generalsio-replays-${server}.s3.amazonaws.com/${encodeURIComponent(replayId)}.gior`;
  const backup = `${BACKUP_ORIGINS[server]}/api/replay/${encodeURIComponent(replayId)}`;
  const urls = [s3, backup, s3];
  for (const [index, url] of urls.entries()) {
    try {
      return { bytes: await fetchBytes(axios, url), source: url };
    } catch (error) {
      // Same gate as ReplayLoader: the backup route is only contacted when a
      // fresh settings fetch explicitly reports replay saving down.
      if (index === 0 && !await savingDown(axios, BACKUP_ORIGINS[server])) break;
    }
  }
  return null;
}

async function acquireReplayBytes(args, axios, generalsEventsRepo) {
  if (args.replayFile) {
    return { bytes: fs.readFileSync(args.replayFile), source: `file:${args.replayFile}` };
  }
  if (!args.replayId || !REPLAY_ID.test(args.replayId)) {
    throw new Error('a valid --replay-id (or --replay-file) is required');
  }

  // Cheap disk check first: covers games played on this machine's local
  // server while AWS saving is down without any network calls. replay_data
  // sits beside the generals-events checkout when the events package is
  // developed inside the game repo; it simply will not exist elsewhere.
  const replayDataRoot = args.replayDataDir
      || path.join(generalsEventsRepo, '..', 'replay_data');
  const local = findLocalReplayBytes(replayDataRoot, args.replayId);
  if (local) {
    return local;
  }

  const servers = args.server === 'auto' ? REAL_SERVERS : [args.server];
  for (const server of servers) {
    if (server === 'loc') {
      // 'loc' replays only exist inside replay_data (checked above) or the
      // emulator suite, which is not a supported source here.
      continue;
    }
    if (!BACKUP_ORIGINS[server]) {
      throw new Error(`unknown --server '${server}' (expected auto|na|eu|bot|ek|loc)`);
    }
    const result = await fetchRemoteReplay(axios, args.replayId, server);
    if (result) {
      return result;
    }
  }
  throw new Error(`replay ${args.replayId} unavailable on all attempted sources`);
}

// Parses a bot-exported .txtmap: returns { grid: string[][], data: {} }.
// grid cells are keyed [y][x]; data is the key=value footer.
function parseTxtmap(filePath) {
  const rows = fs.readFileSync(filePath, 'utf8').split(/\r?\n/);
  const widthRow = rows[0];
  const width = (widthRow.match(/\|/g) || []).length;
  const cellWidth = widthRow.split('|')[1].length + 1;
  const grid = [];
  const data = {};
  let footer = false;
  for (let r = 1; r < rows.length; r++) {
    const row = rows[r];
    if (row.startsWith('|')) {
      footer = true;
      continue;
    }
    if (!footer) {
      const cells = [];
      for (let i = 0; i < row.length; i += cellWidth) {
        cells.push(row.substr(i, cellWidth));
      }
      grid.push(cells);
    } else {
      const kvp = row.trim();
      if (!kvp) {
        continue;
      }
      const eq = kvp.indexOf('=');
      if (eq < 0) {
        continue;
      }
      data[kvp.slice(0, eq)] = kvp.slice(eq + 1);
    }
  }
  return { grid, data, width };
}

function tileOwnerChar(owner) {
  return PLAYER_CHARS[owner];
}

// Builds one txtmap cell for a simulated tile. Mirrors the bot's
// Tile.get_value_representation: playerChar, C, L|O|S|E|M(elif), G,
// army ('N' prefix for unowned non-city), and a trailing 'D' for
// discovered-not-visible tiles (never emitted - the true map is omniscient).
function cellFor(game, Map, index) {
  const owner = game.map._map[index];
  const army = game.map._armies[index];
  const isCity = game.citySet.has(index);
  const isSwamp = game.swamps.includes(index);
  const isDesert = game.deserts.includes(index);
  const isTunnel = game.map.getTunnelLimit(index) > 0;
  const isStronghold = game.map.getStrongholdStrength(index) > 0;

  if (isTunnel || isStronghold) {
    throw new Error(`tile ${index} is a tunnel/stronghold; txtmap has no representation for it`);
  }

  let cell = '';
  if (owner >= 0) {
    cell += tileOwnerChar(owner);
  }
  if (isCity) {
    cell += 'C';
  } else if (owner < 0) {
    switch (game.map._map[index]) {
      case Map.TILE_MOUNTAIN:
        return 'M';
      case Map.TILE_LOOKOUT:
        return 'L';
      case Map.TILE_OBSERVATORY:
        return 'O';
      default:
        break;
    }
    if (isSwamp) {
      cell += 'S';
    } else if (isDesert) {
      cell += 'E';
    }
  } else {
    if (isSwamp) {
      cell += 'S';
    } else if (isDesert) {
      cell += 'E';
    }
  }

  const isGeneral = owner >= 0 && game.generals[owner] === index;
  if (isGeneral) {
    cell += 'G';
  }

  if (army !== 0 || owner >= 0) {
    if (owner < 0 && !isCity) {
      cell += 'N';
    }
    cell += String(army);
  }

  return cell;
}

function dumpTxtmap(game, Map, replay, turn, playerIndex, inherited) {
  const width = game.map.width;
  const height = game.map.height;

  const cells = [];
  let cellWidth = 3;
  for (let y = 0; y < height; y++) {
    const row = [];
    for (let x = 0; x < width; x++) {
      const cell = cellFor(game, Map, y * width + x);
      row.push(cell);
      cellWidth = Math.max(cellWidth, cell.length + 1);
    }
    cells.push(row);
  }

  const lines = [];
  const bar = Array(width).fill('|' + ' '.repeat(cellWidth - 1)).join('');
  lines.push(bar);
  for (const row of cells) {
    lines.push(row.map(cell => cell.padEnd(cellWidth)).join('').trimEnd());
  }
  lines.push(bar);

  lines.push(`turn=${turn}`);
  lines.push(`player_index=${playerIndex}`);

  for (const key of COPIED_SCALAR_KEYS) {
    if (key in inherited) {
      lines.push(`${key}=${inherited[key]}`);
    }
  }
  if (!('mode' in inherited)) {
    const teams = replay.teams;
    let mode = 'ffa';
    if (!teams && replay.usernames.length === 2) {
      mode = '1v1';
    } else if (teams && teams.some(t => teams.indexOf(t) !== teams.lastIndexOf(t))) {
      mode = 'team';
    } else if (teams) {
      mode = 'custom_team';
    }
    lines.push(`mode=${mode}`);
  }
  if (!('teams' in inherited) && replay.teams) {
    lines.push(`teams=${replay.teams.join(',')}`);
  }
  if (!('modifiers' in inherited) && replay.modifiers.length) {
    lines.push(`modifiers=${replay.modifiers.join(',')}`);
  }

  const afkTurnByPlayer = {};
  for (const afk of replay.afks) {
    if (!(afk.index in afkTurnByPlayer)) {
      afkTurnByPlayer[afk.index] = afk.turn;
    }
  }

  for (let i = 0; i < replay.usernames.length; i++) {
    const c = tileOwnerChar(i);
    const dead = game.sockets[i].dead || game.generals[i] === undefined
        || game.generals[i] === null || game.generals[i] < 0;
    const score = game.scores[i] || { total: 0, tiles: 0 };
    const cityCount = game.cities.filter(
      city => game.map._map[city] === i).length + (dead ? 0 : 1);

    lines.push(`${c}Username=${replay.usernames[i]}`);
    if (replay.stars && replay.stars[i] !== undefined) {
      lines.push(`${c}Stars=${replay.stars[i]}`);
    }
    lines.push(`${c}Score=${score.total}`);
    lines.push(`${c}Tiles=${score.tiles}`);
    lines.push(`${c}StandingArmy=${score.total - score.tiles}`);
    lines.push(`${c}CityCount=${cityCount}`);
    if (!dead) {
      const gx = game.generals[i] % width;
      const gy = Math.floor(game.generals[i] / width);
      lines.push(`${c}General=${gx},${gy}`);
    }
    lines.push(`${c}Dead=${dead ? 'True' : 'False'}`);
    const afkTurn = afkTurnByPlayer[i];
    lines.push(`${c}LeftGame=${afkTurn !== undefined ? 'True' : 'False'}`);
    lines.push(`${c}LeftGameTurn=${afkTurn !== undefined ? afkTurn : -1}`);

    for (const suffix of COPIED_PLAYER_SUFFIXES) {
      const key = `${c}${suffix}`;
      if (key in inherited) {
        lines.push(`${key}=${inherited[key]}`);
      }
    }
  }

  return lines.join('\n') + '\n';
}

// Every cell the bot could see is ground truth and must match the simulated
// state exactly: own tiles are always visible, and any non-'D' foreign tile
// next to own land is currently visible too. Fog guesses ('a1' without 'D'
// outside vision) legitimately differ - they are the point of the dump.
function verifyAgainstBotMap(game, Map, botTxtmap, playerIndex) {
  const errors = [];
  const { grid } = botTxtmap;
  const width = game.map.width;

  // First pass: collect the bot's own tiles; vision = own tile + adjacents.
  const visibleTruth = new Set();
  for (let y = 0; y < grid.length; y++) {
    for (let x = 0; x < grid[y].length; x++) {
      const cell = grid[y][x];
      if (cell.startsWith(tileOwnerChar(playerIndex)) && !cell.includes('D')) {
        visibleTruth.add(y * width + x);
        for (const [dx, dy] of [[0, 1], [0, -1], [1, 0], [-1, 0], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
          const nx = x + dx;
          const ny = y + dy;
          if (ny >= 0 && ny < grid.length && nx >= 0 && nx < grid[ny].length) {
            visibleTruth.add(ny * width + nx);
          }
        }
      }
    }
  }

  for (let y = 0; y < grid.length; y++) {
    for (let x = 0; x < grid[y].length; x++) {
      const index = y * width + x;
      if (!visibleTruth.has(index)) {
        continue;
      }
      const botCell = grid[y][x];
      const trueCell = cellFor(game, Map, index);
      if (botCell.trim() === trueCell) {
        continue;
      }
      // The bot's file may write a discovered-mountain/observatory shorthand
      // or a stale 'D' memory of a tile that later changed - those cells were
      // not re-verified this turn. Only 'D'-free own cells and 'D'-free
      // foreign cells in vision are hard requirements.
      if (botCell.includes('D')) {
        continue;
      }
      errors.push(`(${x},${y}) bot='${botCell.trim()}' true='${trueCell.trim()}'`);
    }
  }

  return errors;
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.turn) {
    throw new Error('--turn <n> is required');
  }
  if (!args.out) {
    throw new Error('--out <file.txtmap> is required');
  }
  const targetTurn = parseInt(args.turn, 10);

  const generalsEventsRepo = resolveGeneralsEventsRepo(args);
  const { axios, ReplayDeserializer, EventReplaySimulation, Map } =
      loadEventsDeps(generalsEventsRepo);

  const { bytes, source } = await acquireReplayBytes(
    args, axios, generalsEventsRepo);
  const replay = ReplayDeserializer(bytes);
  if (!replay) {
    throw new Error('replay bytes failed to decode');
  }

  const inherited = {};
  let botTxtmap = null;
  if (args.copyDataFrom) {
    botTxtmap = parseTxtmap(args.copyDataFrom);
    Object.assign(inherited, botTxtmap.data);
  }

  const playerIndex = args.playerIndex !== undefined
      ? parseInt(args.playerIndex, 10)
      : (inherited.player_index !== undefined ? parseInt(inherited.player_index, 10) : 0);

  const players = replay.usernames.map(
    name => ({ name, kills: 0, lastTurn: 0, killed: [], killedBy: [], tilesAfterFirstRound: 0 }));
  const game = new EventReplaySimulation(replay, players, [], new Set());
  while (!game.isOver() && game.turn < targetTurn) {
    game.nextTurn();
  }
  if (game.turn < targetTurn) {
    console.error(`warning: game ended at turn ${game.turn} before target turn ${targetTurn}; dumping final state`);
  }
  game.recalculateScores();

  if (botTxtmap && args.verify !== false) {
    const errors = verifyAgainstBotMap(game, Map, botTxtmap, playerIndex);
    if (errors.length) {
      throw new Error(
        `simulated turn ${game.turn} contradicts the bot's visible board:\n  ${errors.slice(0, 20).join('\n  ')}`);
    }
    const scoreErrors = [];
    for (let i = 0; i < replay.usernames.length; i++) {
      const c = tileOwnerChar(i);
      for (const [suffix, simValue] of [['Score', game.scores[i].total], ['Tiles', game.scores[i].tiles]]) {
        const key = `${c}${suffix}`;
        if (key in botTxtmap.data && parseInt(botTxtmap.data[key], 10) !== simValue) {
          scoreErrors.push(`${key} bot=${botTxtmap.data[key]} true=${simValue}`);
        }
      }
    }
    if (scoreErrors.length) {
      throw new Error(
        `simulated turn ${game.turn} scoreboard contradicts the bot's recorded values:\n  ${scoreErrors.join('\n  ')}`);
    }
  }

  const output = dumpTxtmap(game, Map, replay, game.turn, playerIndex, inherited);
  fs.mkdirSync(path.dirname(path.resolve(args.out)), { recursive: true });
  fs.writeFileSync(args.out, output);

  if (args.saveReplay) {
    fs.mkdirSync(path.dirname(path.resolve(args.saveReplay)), { recursive: true });
    fs.writeFileSync(args.saveReplay, bytes);
  }

  const scoreSummary = game.scores.map(
    (s, i) => `${tileOwnerChar(i)}=${s.total}/${s.tiles}`).join(' ');
  console.log(`dumped true map for replay ${replay.id} from ${source} at turn ${game.turn}: ${scoreSummary}`);
}

main().catch(error => {
  console.error(error.stack || String(error));
  process.exit(1);
});
