"""Scan recent 1v1 game logs and grade the bot's enemy-general prediction metrics.

For every turn in the second half of each scanned 1v1 game where the bot still
tracked >= --min-emergences emergence sources and more than
--min-valid-positions valid enemy-general candidate tiles, the bot state is
reconstructed from that turn's txtmap (the same resume path continuation
tests use: TextMapLoader -> MapBase -> EklipZBot.load_resume_data, plus the
fog-land rebuild a live post-resume turn performs) and every per-tile
general-prediction metric is scored against the TRUE enemy general position,
dumped once per game by the replay parser (ReplayTools/ReplayTxtmapDump.js).

Metrics (each metric's argmax set over valid candidate tiles is that metric's
"most likely general position" rating; ties all count):

  composite        the foundValue the live prediction maximizes:
                   connectedSpread + spawnFairness + ed
  ed               gated emergence locality (the rendered 'ed' value):
                   (emgLocality + edBonus) * pathConsistency gate
  edUngated        emgLocality + edBonus before the path-consistency gate
  emgLocality      emergenceLocationMap * 10
  edBonus          emergence distance-sum bonus matrix value
  pathConsistency  max(EMERGENCE_PATH_CONSISTENCY_FLOOR, 1 - pathPenalty);
                   1.0 means the candidate's shortest route to our general
                   explains every observed emergence source (row only
                   emitted when a penalty matrix exists for the turn)
  sf1/10 sf1/5 sf1/4 sf1/3 sf1/2
                   pseudo-metrics: the top X fraction of candidates sorted by
                   raw spawn-fairness weight, graded like an argmax set.
                   hit% = truth inside the top slice; max_val = the top
                   weight in the slice. Measures how predictive a fairness
                   threshold
                   is rather than the weight curve itself (the raw weight
                   plateau ties nearly every candidate at the same max).
  connectedSpread  fog-land BFS spread seeded from coreConnected tiles
  coreBase         per-core-seed base value (emg*4 + distToEmg*20); nonzero
                   only on coreConnected tiles
  precontact       'u' undiscovered-priorities grid (pre-contact scorer)
  connected        1.0 if the tile is in the fog-land connected set
  predicted        pseudo-metric for the serialized
                   targetPlayerExpectedGeneralLocation pick: closest and
                   furthest are both that tile's manhattan distance to the
                   true general (what the live composite actually chose)

(everOwned was dropped: any tile the enemy has been SEEN owning was visible
at ownership time, so its general-hood is already resolved and it can never
be a valid candidate — the column was identically 0.0 with every candidate
tied at the max, a trivial 100% hit with no discriminative content.)

Per turn, per metric: max value, argmax set size, closest/furthest manhattan
distance of the argmax set to the true general, the metric's value AT the
true general tile and AT the serialized predicted tile (both computed even
when the tile is not itself a candidate), whether the true tile is in the
argmax set, and the fraction of candidates that outscored it. Aggregates
are emitted twice: "By Game"
(average within each game first, then across games equally) and "By Turn"
(every qualifying turn pooled). Turn-level columns also carry the serialized
vs reconstructed valid-candidate counts and whether the true general was
still in the valid set.

Usage (from repo root):
  .\\.venv\\Scripts\\python.exe LiveGameAnalysis\\ScanRecentGamesForGeneralPrediction.py --max-games 10
"""

from __future__ import annotations

import argparse
import csv
import math
import shutil
import subprocess
import sys
import time
import traceback
import typing
from dataclasses import dataclass, field
from pathlib import Path

import logbook
import openpyxl
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, PatternFill
from openpyxl.utils import get_column_letter

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import base.client.map
import EarlyExpandUtils
import SearchUtils
from Gather import GatherDebug
from ArmyTracker import (
    EMERGENCE_PATH_CONSISTENCY_FLOOR,
    ArmyTracker,
    spawn_fairness_prediction_value,
)
from base.client.map import MapBase, PLAYER_CHAR_BY_INDEX, Score, Tile
from bot_ek0x45 import EklipZBot
from BotModules.BotStateQueries import BotStateQueries
from BotModules.BotTargeting import BotTargeting
from DistanceMapperImpl import DistanceMapperImpl
from Interfaces import MapMatrixInterface
from MapMatrix import MapMatrix, TileSet
from Path import Path as BotPath
from Sim.TextMapLoader import TextMapLoader


LOG_CHANNEL = 'gp-scan'
LOGGER = logbook.Logger(LOG_CHANNEL)

DEFAULT_OUTPUT_ROOT = Path(r'C:\cascade-debug-output\generals-bot\general-prediction-scan')
# Replay-derived artifacts (.gior downloads, .truemap.txtmap dumps) live under
# this cache instead of inside the game log folders: writing into a grouped
# log folder bumps its LastWriteTime, which makes long-finished games look
# freshly modified in Explorer's sort-by-date. Entries older than the
# retention window are deleted by cleanup_replay_dump_cache on each scan run.
REPLAY_DUMP_CACHE_ROOT = Path(r'C:\cascade-debug-output\generals-bot\replay-dump-cache')
REPLAY_DUMP_CACHE_MAX_AGE_DAYS = 7
TRUMAP_DUMP_TIMEOUT_S = 240

# Order here is the report row order. 'predicted' is a pseudo-metric for the
# bot's serialized pick rather than a per-tile score.
ALL_METRICS: typing.List[str] = [
    'composite',
    'ed',
    'edUngated',
    'emgLocality',
    'edBonus',
    'pathConsistency',
    'sf1/10',
    'sf1/5',
    'sf1/4',
    'sf1/3',
    'sf1/2',
    'connectedSpread',
    'coreBase',
    'precontact',
    'connected',
    'predicted',
]

# Human-readable meaning of each metric row, emitted in the summary CSV's
# 'description' column and the report's METRIC LEGEND block.
METRIC_DESCRIPTIONS: typing.Dict[str, str] = {
    'composite': (
        'Score the live bot maximizes to pick the general tile: '
        'connectedSpread + spawnFairness + ed. Its argmax is the prediction.'),
    'ed': (
        "Gated emergence-distance score (the 'ed' value rendered on tiles "
        'in-game): (emgLocality + edBonus) * pathConsistency gate'),
    'edUngated': 'emgLocality + edBonus, before the path-consistency gate multiplies it down',
    'emgLocality': (
        'emergenceLocationMap[tile] * 10 — density of observed enemy '
        'emergences around this tile (emergences point at where the general went)'),
    'edBonus': (
        'Emergence distance-sum bonus matrix: rewards tiles whose distances '
        'to emergence sources are consistent with the expected general distance'),
    'pathConsistency': (
        'Gate = max(FLOOR, 1 - pathPenalty); 1.0 means the candidate\'s '
        'shortest route to our general can explain every observed emergence '
        'source. Multiplier on ed, not an additive term. Only emitted on '
        'turns where a penalty matrix exists.'),
    'sf1/10': (
        'Top 10% of candidates by raw spawn-fairness weight, graded as a '
        'set: hit% = truth inside the top slice, max_val = the top weight '
        'in the slice. Tests whether elite fairness picks out the general.'),
    'sf1/5': (
        'Top 20% of candidates by raw spawn-fairness weight, graded as a '
        'set: hit% = truth inside the top slice, max_val = the top weight '
        'in the slice.'),
    'sf1/4': (
        'Top 25% of candidates by raw spawn-fairness weight, graded as a '
        'set: hit% = truth inside the top slice, max_val = the top weight '
        'in the slice.'),
    'sf1/3': (
        'Top 33% of candidates by raw spawn-fairness weight, graded as a '
        'set: hit% = truth inside the top slice, max_val = the top weight '
        'in the slice.'),
    'sf1/2': (
        'Top 50% of candidates by raw spawn-fairness weight, graded as a '
        'set: hit% = truth inside the top slice, max_val = the top weight '
        'in the slice.'),
    'connectedSpread': (
        'Fog-land BFS spread seeded from core-connected tiles with '
        'base/(dist+4) decay — how deep inside the enemy-connected fog '
        'region the tile sits, weighted toward emergence sources'),
    'coreBase': (
        'BFS seed value on core-connected tiles only: emg*4 + distToEmg*20; '
        '0 elsewhere. Mostly a plateau over the enemy core region — a '
        'membership signal, not a ranker.'),
    'precontact': "'u' undiscovered-priorities grid — the pre-contact general-location scorer",
    'connected': '1.0 if the tile is in the fog-land connected set (enemy-connected fog)',
    'predicted': (
        'Serialized targetPlayerExpectedGeneralLocation — the live '
        'composite pick. closest and furthest are both its manhattan '
        'distance to the true general.'),
}

CSV_FIELDS = [
    'game', 'replay_id', 'turn', 'metric',
    'max_val', 'argmax_count', 'closest', 'furthest', 'argmax_avg',
    'true_val', 'pred_val', 'true_in_argmax', 'true_rank',
    'candidates', 'valid_serialized', 'valid_loaded',
    'emg_sources', 'expected_dist',
    'pred_x', 'pred_y', 'pred_dist',
    'true_x', 'true_y', 'true_in_valid',
    'unverified', 'error',
]


@dataclass(slots=True)
class TurnFooter:
    """Cheap footer-only metadata parsed from one txtmap snapshot."""

    turn: int
    path: Path
    emergence_count: int
    valid_positions: int
    enemy_general_known: bool
    target_player: int
    predicted_general: str
    footer: typing.Dict[str, str]


@dataclass(slots=True)
class GamePlan:
    """Cheap eligibility scan result for one recent game folder."""

    folder: Path
    replay_id: str
    player_index: int
    enemy_index: int
    enemy_char: str
    launch_estimate: int
    last_turn: int
    footers: typing.List[TurnFooter]
    qualifying: typing.List[TurnFooter]
    known_general_turns: int
    skip_reason: str


@dataclass(slots=True)
class MetricRow:
    """One turn's argmax-vs-truth stats for one metric (or 'predicted')."""

    turn: int
    metric: str
    max_val: float | None
    argmax_count: int
    closest: int | None
    furthest: int | None
    argmax_avg: float | None
    true_val: float | None
    pred_val: float | None
    true_in_argmax: float | None
    true_rank: float | None
    candidates: int
    valid_serialized: int
    valid_loaded: int
    emg_sources: int
    expected_dist: int | None
    pred_x: int
    pred_y: int
    pred_dist: int | None
    true_x: int
    true_y: int
    true_in_valid: float
    unverified: int
    error: str


@dataclass(slots=True)
class GameResult:
    """Aggregated scan output for one game."""

    game: str
    replay_id: str
    player_index: int
    enemy_index: int
    true_x: int
    true_y: int
    unverified: int
    rows: typing.List[MetricRow]
    known_general_turns: int
    error_turns: int
    notes: typing.List[str] = field(default_factory=list)


@dataclass(slots=True)
class Args:
    """CLI options that scan internals consume."""

    scan_root: str
    out: str
    max_games: int
    min_emergences: int
    min_valid_positions: int
    second_half_after: float
    turn_stride: int
    game_filter: str
    generals_events_repo: str
    skip_precontact: bool
    strict: bool


# ---------------------------------------------------------------------------
# run_config / folder scanning
# ---------------------------------------------------------------------------


def read_run_config() -> typing.Dict[str, str]:
    """Parse <repo>/../run_config.txt (key=value, '#' comments)."""
    cfg: typing.Dict[str, str] = {}
    path = REPOSITORY_ROOT.parent / 'run_config.txt'
    if not path.exists():
        LOGGER.warn(f'run_config.txt not found at {path}; --scan-root required')
        return cfg
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        cfg[key.strip()] = value.strip()
    return cfg


def list_game_folders(scan_root: Path, args: Args) -> typing.List[Path]:
    """Return recent grouped game folders (newest first) that hold txtmaps."""
    folders = [p for p in scan_root.iterdir() if p.is_dir() and '---' in p.name]
    folders.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    if args.game_filter:
        folders = [p for p in folders if args.game_filter in p.name]
    kept: typing.List[Path] = []
    for folder in folders:
        if any(True for _ in folder.glob('*.txtmap')):
            kept.append(folder)
        if len(kept) >= args.max_games:
            break
    return kept


# ---------------------------------------------------------------------------
# txtmap footer parsing (cheap pass — no Tile construction)
# ---------------------------------------------------------------------------


def parse_footer(path: Path) -> typing.Dict[str, str]:
    """Parse only the k=v footer section of a txtmap (grid rows skipped)."""
    footer: typing.Dict[str, str] = {}
    in_footer = False
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for i, line in enumerate(f):
            if i == 0:
                continue  # width row also starts with '|'
            if line.startswith('|'):
                in_footer = True
                continue
            if not in_footer:
                continue
            eq = line.find('=')
            if eq <= 0:
                continue
            footer[line[:eq].strip()] = line[eq + 1:].strip()
    return footer


def emergence_source_indexes(footer: typing.Dict[str, str], char: str) -> typing.Set[int]:
    """Return serialized tile indexes that are enemy emergence sources."""
    sources: typing.Set[int] = set()
    uneliminated = footer.get(f'{char}UneliminatedEmergences', '')
    if uneliminated:
        for idx, token in enumerate(uneliminated.split(',')):
            if token.strip():
                sources.add(idx)
    unrecaptured = footer.get(f'{char}UnrecapturedEmergences', '')
    for idx, ch in enumerate(unrecaptured):
        if ch == '1':
            sources.add(idx)
    return sources


def build_game_plan(folder: Path, args: Args) -> GamePlan:
    """Cheap footer scan deciding whether/which turns of one folder qualify."""
    replay_id = folder.name.rsplit('---', 1)[-1]
    txtmaps = sorted(
        (p for p in folder.glob('*.txtmap') if p.stem.isdigit()),
        key=lambda p: int(p.stem))
    if not txtmaps:
        return GamePlan(folder, replay_id, -1, -1, '?', 24, 0, [], [], 0, 'no txtmaps')

    first_footer = parse_footer(txtmaps[0])
    mode = first_footer.get('mode', '')
    player_index = int(first_footer.get('player_index', '0') or '0')
    enemy_index = 1 - player_index
    enemy_char = PLAYER_CHAR_BY_INDEX[enemy_index]
    if mode != '1v1':
        return GamePlan(folder, replay_id, player_index, enemy_index, enemy_char, 24, 0, [], [], 0, f'mode={mode}')

    footers: typing.List[TurnFooter] = []
    for path in txtmaps:
        footer = parse_footer(path)
        turn = int(footer.get('turn', path.stem) or path.stem)
        footers.append(TurnFooter(
            turn=turn,
            path=path,
            emergence_count=len(emergence_source_indexes(footer, enemy_char)),
            valid_positions=footer.get(f'{enemy_char}ValidGeneralPos', '').count('1'),
            enemy_general_known=f'{enemy_char}General' in footer,
            target_player=int(footer.get('bot_target_player', '-1') or '-1'),
            predicted_general=footer.get('targetPlayerExpectedGeneralLocation', ''),
            footer=footer))

    # Mirror ArmyTracker.scan_movement_and_emergences: launch timing is set the
    # first turn the player's tile count exceeds 1 (turn-1 for the usual
    # 1->2 emergence, 24 for custom maps that start with more land).
    launch_estimate = 24
    for tf in sorted(footers, key=lambda t: t.turn):
        tiles = int(tf.footer.get(f'{enemy_char}Tiles', '0') or '0')
        if tiles > 1:
            launch_estimate = tf.turn - 1 if tiles == 2 else 24
            break

    last_turn = max(tf.turn for tf in footers)
    half_cut = last_turn * args.second_half_after
    known_turns = 0
    qualifying: typing.List[TurnFooter] = []
    for tf in footers:
        if tf.turn <= half_cut:
            continue
        if tf.emergence_count < args.min_emergences:
            continue
        if tf.valid_positions <= args.min_valid_positions:
            continue
        if tf.enemy_general_known:
            known_turns += 1
            continue
        qualifying.append(tf)
    if args.turn_stride > 1:
        qualifying = qualifying[::args.turn_stride]

    skip = ''
    if not qualifying:
        max_emg = max((t.emergence_count for t in footers), default=0)
        second_half = [t for t in footers if t.turn > half_cut]
        max_valid = max((t.valid_positions for t in second_half), default=0)
        skip = (f'no qualifying turns (maxEmg={max_emg}, '
                f'maxValidAfterHalf={max_valid}, lastTurn={last_turn})')
    return GamePlan(
        folder, replay_id, player_index, enemy_index, enemy_char,
        launch_estimate, last_turn, footers, qualifying, known_turns, skip)


# ---------------------------------------------------------------------------
# true-map acquisition (ReplayTools/ReplayTxtmapDump.js)
# ---------------------------------------------------------------------------


def replay_dump_cache_folder(replay_id: str) -> Path:
    """Return (creating if needed) the per-replay analysis-dump cache folder."""
    folder = REPLAY_DUMP_CACHE_ROOT / replay_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def cleanup_replay_dump_cache(max_age_days: int = REPLAY_DUMP_CACHE_MAX_AGE_DAYS) -> int:
    """Delete cache files older than the retention window; return the count."""
    if not REPLAY_DUMP_CACHE_ROOT.is_dir():
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for child in REPLAY_DUMP_CACHE_ROOT.iterdir():
        entries = [child] if child.is_file() else list(child.iterdir())
        for entry in entries:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        if child.is_dir() and not any(child.iterdir()):
            child.rmdir()
    return removed


def detect_replay_server(folder: Path) -> str:
    """Infer the server a replay came from by sniffing the game log header."""
    log_files = [p for p in folder.glob('_*.txt')]
    if not log_files:
        return 'auto'
    try:
        head = log_files[0].open('r', encoding='utf-8', errors='replace').read(65536)
    except OSError:
        return 'auto'
    if 'botws.generals.io' in head or 'bot.generals.io' in head:
        return 'bot'
    if 'euws.generals.io' in head or 'eu.generals.io' in head:
        return 'eu'
    if 'localhost' in head or '127.0.0.1' in head:
        return 'loc'
    if 'ws.generals.io' in head or 'us.generals.io' in head or 'generals.io' in head:
        return 'na'
    return 'auto'


def truemap_scoreboard_matches(bot_footer: typing.Dict[str, str], true_path: Path) -> bool:
    """Compare footer scoreboard fields between the bot map and the dumped true map."""
    true_footer = parse_footer(true_path)
    for char, _index in TextMapLoader.get_player_char_index_map():
        for suffix in ('Score', 'Tiles'):
            key = f'{char}{suffix}'
            if key in bot_footer and key in true_footer and bot_footer[key] != true_footer[key]:
                return False
    return True


def dump_true_map(
        plan: GamePlan,
        first_turn: TurnFooter,
        generals_events_repo: str) -> typing.Tuple[Path | None, bool, str]:
    """Dump (or reuse) the replay-parsed true map at the first qualifying turn.

    Returns (path, orientation_unverified, note). Mirrors
    ScanRecentGamesForFogDesyncs.ps1's Invoke-ReplayTrueMapDump. Dumps land in
    the replay-dump cache (REPLAY_DUMP_CACHE_ROOT/<replayId>/), never in the
    game log folder; .gior/.truemap files already sitting in the log folder
    from older runs are still reused read-only.
    """
    map_path = first_turn.path
    true_path = REPLAY_DUMP_CACHE_ROOT / plan.replay_id / f'{map_path.stem}.truemap.txtmap'
    if true_path.exists():
        return true_path, False, 'cached'
    legacy_true_path = map_path.with_name(f'{map_path.stem}.truemap.txtmap')
    if legacy_true_path.exists():
        return legacy_true_path, False, 'cached (log folder)'

    node = shutil.which('node')
    if node is None:
        return None, False, 'node not on PATH'
    dumper = REPOSITORY_ROOT / 'ReplayTools' / 'ReplayTxtmapDump.js'
    if not dumper.exists():
        return None, False, f'missing {dumper}'

    cache_folder = replay_dump_cache_folder(plan.replay_id)
    gior = cache_folder / f'{plan.replay_id}.gior'
    legacy_gior = plan.folder / f'{plan.replay_id}.gior'
    args = [node, str(dumper)]
    if gior.exists():
        args += ['--replay-file', str(gior)]
    elif legacy_gior.exists():
        args += ['--replay-file', str(legacy_gior)]
    else:
        args += [
            '--replay-id', plan.replay_id,
            '--server', detect_replay_server(plan.folder),
            '--save-replay', str(gior)]
    args += [
        '--turn', str(first_turn.turn),
        '--player-index', str(plan.player_index),
        '--generals-events-repo', generals_events_repo,
        '--out', str(true_path),
        '--copy-data-from', str(map_path)]

    run = subprocess.run(args, capture_output=True, text=True, timeout=TRUMAP_DUMP_TIMEOUT_S)
    if run.returncode == 0 and true_path.exists():
        return true_path, False, 'dumped'

    LOGGER.warn(f'{plan.folder.name}: truemap dump failed ({run.returncode}); retrying --no-verify')
    run = subprocess.run(
        args + ['--no-verify'], capture_output=True, text=True, timeout=TRUMAP_DUMP_TIMEOUT_S)
    if run.returncode != 0 or not true_path.exists():
        return None, False, f'dump failed rc={run.returncode}: {run.stderr[-300:]}'
    if not truemap_scoreboard_matches(first_turn.footer, true_path):
        true_path.unlink()
        return None, False, 'unverified truemap rejected (scoreboard mismatch)'
    return true_path, True, 'dumped --no-verify (orientation unverified)'


def find_enemy_general_in_truemap(true_path: Path, enemy_index: int) -> typing.Tuple[int, int] | None:
    """Parse the truemap grid for the enemy-owned general cell ('G' flag)."""
    enemy_char = PLAYER_CHAR_BY_INDEX[enemy_index]
    lines = true_path.read_text(encoding='utf-8', errors='replace').splitlines()
    if not lines:
        return None
    width_row = lines[0]
    cell_width = len(width_row.split('|')[1]) + 1
    indent = len(width_row) - len(width_row.lstrip())
    y = 0
    for line in lines[1:]:
        if line.startswith('|'):
            break
        if indent:
            line = line[indent:]
        for x in range(len(line) // cell_width):
            cell = line[x * cell_width:(x + 1) * cell_width].strip()
            if cell.endswith('D'):
                cell = cell[:-1]
            if not cell or cell[0] != enemy_char:
                continue
            if 'G' in cell[1:]:
                return (x, y)
        y += 1
    return None


# ---------------------------------------------------------------------------
# bot reconstruction + metric evaluation
# ---------------------------------------------------------------------------


def rebuild_bot_from_txtmap(plan: GamePlan, tf: TurnFooter) -> typing.Tuple[EklipZBot, MapBase]:
    """Rebuild the bot state for one dumped turn the way a resumed game does."""
    raw = tf.path.read_text(encoding='utf-8', errors='replace')
    board = TextMapLoader.load_map_from_string(raw)
    data = tf.footer

    num_players = 0
    for char, index in TextMapLoader.get_player_char_index_map():
        if f'{char}Tiles' in data:
            num_players = index + 1
    num_players = max(num_players, plan.player_index + 1)
    teams = None
    if 'teams' in data:
        teams = [int(t) for t in data['teams'].split(',')]
        num_players = max(num_players, len(teams))

    usernames = [c for c, _idx in TextMapLoader.get_player_char_index_map()]
    game_map = MapBase(
        player_index=plan.player_index,
        teams=teams,
        user_names=usernames[0:num_players],
        turn=tf.turn,
        map_grid_y_x=board,
        replay_url='general-prediction-scan')
    game_map.update_scores([Score(n, 1, 1, False) for n in range(num_players)])
    game_map.update_turn(tf.turn)
    game_map.update(bypassDeltas=True)
    TextMapLoader.load_map_data_into_map(game_map, data)
    game_map.turn = tf.turn

    general = next(
        (t for t in game_map.pathable_tiles if t.isGeneral and t.player == plan.player_index),
        None)
    if general is None:
        raise RuntimeError(f'{tf.path.name}: no general tile for p{plan.player_index}')
    game_map.friendly_team = game_map.team_ids_by_player_index[general.player]
    game_map.generals[general.player] = general
    game_map.resume_data = data
    game_map.distance_mapper = DistanceMapperImpl(game_map)

    bot = EklipZBot()
    bot.no_file_logging = True
    bot.initialize_from_map_for_first_time(game_map)
    bot.is_pre_resume_init_turn = True
    # GameSimulator runs receive_update_no_move once before load_resume_data,
    # whose analyze pass stores the board scoreboard into
    # opponent_tracker.current_team_scores. BotSerialization.load_resume_data
    # (and later consumers) crash on .cityCount when it is still None, so seed
    # the same "last seen team scores" directly from the loaded board.
    for team in game_map.unique_teams:
        if bot.opponent_tracker.current_team_scores[team] is None:
            bot.opponent_tracker.current_team_scores[team] = (
                game_map.get_team_stats_by_team_id(team))
    # Island restore crashes on some live dumps (island_ids matrices with tiles
    # lacking a leaf-island entry); the init-time recalculate_tile_islands is
    # equivalent for the general-prediction metrics, which never read islands.
    bot.load_resume_data(data, skip_island_restore=True)
    bot.info_render_general_undiscovered_prediction_values = False
    # No init_turn ever runs on this reconstructed bot, so perf_timer.current_move
    # is still None; get_path_to_target_player et al use begin_move_event.
    bot.perf_timer.begin_move(tf.turn)

    # Rebuild the per-turn fog-land/prediction state a live turn computes after
    # resume: enemy launch timing (the txtmap can't store it), the path to the
    # target player (drives expectedGeneralDistance), and the connected/core
    # fog-land sets (drive the connectedSpread component).
    tracker = bot.armyTracker
    tracker.player_launch_timings[plan.enemy_index] = plan.launch_estimate
    bot.shortest_path_to_target_player = BotTargeting.get_path_to_target_player(
        bot,
        isAllIn=BotStateQueries.is_all_in(bot),
        cutLength=None,
        fromTile=bot.general)
    if bot.shortest_path_to_target_player is None:
        fallback = BotPath()
        fallback.add_next(bot.general)
        fallback.add_next(next(iter(bot.general.movableNoObstacles)))
        bot.shortest_path_to_target_player = fallback
    _banned, connected, core, _path, _gen_dist, _reach = tracker.get_fog_connected_based_on_emergences(
        plan.enemy_index, bot.targetPlayerExpectedGeneralLocation)
    tracker.connectedByPlayer[plan.enemy_index] = connected
    tracker.coreConnectedByPlayer[plan.enemy_index] = core
    return bot, game_map


def manhattan(a: Tile, b: Tile) -> int:
    """Manhattan distance between two tiles."""
    return abs(a.x - b.x) + abs(a.y - b.y)


def parse_xy(value: str) -> typing.Tuple[int, int] | None:
    """Parse a serialized 'x,y' coordinate, or None when absent."""
    if not value:
        return None
    parts = value.split(',')
    if len(parts) != 2:
        return None
    return (int(parts[0]), int(parts[1]))


def evaluate_turn(
        plan: GamePlan,
        tf: TurnFooter,
        true_xy: typing.Tuple[int, int],
        unverified: bool,
        skip_precontact: bool) -> typing.List[MetricRow]:
    """Reconstruct the bot at one turn and grade every prediction metric."""
    bot, game_map = rebuild_bot_from_txtmap(plan, tf)
    tracker: ArmyTracker = bot.armyTracker
    enemy = plan.enemy_index
    true_tile = game_map.At(true_xy[0], true_xy[1])

    expected_dist = bot.shortest_path_to_target_player.length
    ed_bonus = tracker.build_emergence_distance_bonus_matrix(enemy, expected_dist)
    dist_to_us = game_map.get_distance_matrix_including_obstacles(bot.general)
    # Penalty is built for the ENEMY explicitly (not bot.targetPlayer) so the
    # metric measures the enemy route-explanation signal even on turns where
    # targetPlayer is unset; identical to the live call when targeting the enemy.
    source_weights = tracker.build_emergence_path_source_weights(
        enemy, bot.win_condition_analyzer.city_contestation_history)
    penalty: MapMatrixInterface[float] | None = None
    if len(source_weights) > 0:
        penalty = tracker.build_emergence_path_consistency_penalty_matrix(
            enemy, source_weights, dist_to_us, expected_dist)

    # Fog-land connected spread — replicates BotTargeting lines 1002-1011 exactly.
    values = MapMatrix(game_map, 0.0)
    emg = tracker.emergenceLocationMap[enemy]
    uneliminated = tracker.uneliminated_emergence_events[enemy]
    connected_set = tracker.connectedByPlayer[enemy]
    core_set = tracker.coreConnectedByPlayer[enemy]
    dist_to_emg = SearchUtils.build_distance_map_matrix(game_map, uneliminated.keys())
    if connected_set is not None:
        rng = game_map.rows / 3

        def foreach_func(cur_tile: Tile, state: typing.Tuple[float, int]) -> typing.Tuple[float, int]:
            base_float, dist = state
            values.raw[cur_tile.tile_index] += base_float / (dist + 4)
            return (base_float, dist + 1)

        start_tiles = {
            t: (emg[t] * 4 + dist_to_emg.raw[t.tile_index] * 20, 1)
            for t in core_set}
        SearchUtils.breadth_first_foreach_with_state(
            game_map, start_tiles, rng, foreach_func, None, noLog=True)

    u_grid: MapMatrixInterface[float] | None = None
    if not skip_precontact:
        u_grid = BotTargeting.find_expected_1v1_general_location_on_undiscovered_map(
            bot,
            BotTargeting.get_safe_per_tile_bfs_depth(bot),
            tracker.min_spawn_distance)

    valid = tracker.valid_general_positions_by_player[enemy]
    sf_weights = tracker.spawn_fairness_weights_by_player[enemy]
    sf_active = tracker.spawn_fairness_active
    source_tiles = set(uneliminated.keys()) | tracker.unrecaptured_emergence_events[enemy]
    candidates = [
        t for t in game_map.pathable_tiles
        if not (t.discovered or t.isMountain or t.isNotPathable or t.isCity) and valid[t]]
    valid_loaded = sum(1 for t in game_map.get_all_tiles() if valid[t])
    if not candidates:
        raise RuntimeError(f't{tf.turn}: 0 valid candidates after reconstruction')

    def tile_values(t: Tile) -> typing.Dict[str, float]:
        i = t.tile_index
        spread = values.raw[i]
        sf_raw = sf_weights.raw[i]
        sf_val = spawn_fairness_prediction_value(sf_raw) if sf_active else 0.0
        emg_loc = emg[t] * 10
        edb = ed_bonus.raw[i]
        locality = emg_loc + edb
        gate = 1.0 if penalty is None else max(
            EMERGENCE_PATH_CONSISTENCY_FLOOR, 1.0 - penalty.raw[i])
        ed = locality * gate if (locality != 0 and penalty is not None) else locality
        out = {
            'composite': spread + sf_val + ed,
            'ed': ed,
            'edUngated': locality,
            'emgLocality': emg_loc,
            'edBonus': edb,
            'connectedSpread': spread,
            'coreBase': (emg[t] * 4 + dist_to_emg.raw[i] * 20) if t in core_set else 0.0,
            'connected': 1.0 if t in connected_set else 0.0,
        }
        if penalty is not None:
            out['pathConsistency'] = gate
        if u_grid is not None:
            out['precontact'] = u_grid.raw[i]
        return out

    metric_vals: typing.Dict[str, typing.Dict[Tile, float]] = {}
    for tile in candidates:
        for name, val in tile_values(tile).items():
            metric_vals.setdefault(name, {})[tile] = val
    true_vals = tile_values(true_tile)

    pred_xy = parse_xy(tf.predicted_general)
    pred_dist: int | None = None
    pred_x = pred_y = -1
    pred_tile: Tile | None = None
    if pred_xy is not None:
        pred_x, pred_y = pred_xy
        pred_tile = game_map.At(pred_x, pred_y)
        pred_dist = manhattan(pred_tile, true_tile)
    elif bot.targetPlayerExpectedGeneralLocation is not None:
        pred_tile = bot.targetPlayerExpectedGeneralLocation
        pred_x, pred_y = pred_tile.x, pred_tile.y
        pred_dist = manhattan(pred_tile, true_tile)
    # Per-metric value AT the live pick — the "how far off was the prediction
    # under this metric" comparator vs max_val (tile_values works on any tile,
    # so the pick still gets scored if reconstruction disagrees on candidacy).
    pred_vals: typing.Dict[str, float] | None = (
        tile_values(pred_tile) if pred_tile is not None else None)

    def base_row(metric: str) -> MetricRow:
        return MetricRow(
            turn=tf.turn,
            metric=metric,
            max_val=None,
            argmax_count=0,
            closest=None,
            furthest=None,
            argmax_avg=None,
            true_val=None,
            pred_val=None,
            true_in_argmax=None,
            true_rank=None,
            candidates=len(candidates),
            valid_serialized=tf.valid_positions,
            valid_loaded=valid_loaded,
            emg_sources=len(source_tiles),
            expected_dist=expected_dist,
            pred_x=pred_x,
            pred_y=pred_y,
            pred_dist=pred_dist,
            true_x=true_xy[0],
            true_y=true_xy[1],
            true_in_valid=1.0 if valid[true_tile] else 0.0,
            unverified=1 if unverified else 0,
            error='')

    rows: typing.List[MetricRow] = []
    for metric, vals in metric_vals.items():
        row = base_row(metric)
        max_val = max(vals.values())
        argmax = {t for t, v in vals.items() if v == max_val}
        row.max_val = max_val
        row.argmax_count = len(argmax)
        dists = [manhattan(t, true_tile) for t in argmax]
        row.closest = min(dists)
        row.furthest = max(dists)
        row.argmax_avg = sum(dists) / len(dists)
        row.true_val = true_vals[metric]
        row.pred_val = pred_vals[metric] if pred_vals is not None else None
        row.true_in_argmax = 1.0 if true_tile in argmax else 0.0
        outscoring = sum(1 for v in vals.values() if v > row.true_val)
        row.true_rank = outscoring / len(vals)
        rows.append(row)

    # Top-fraction spawn-fairness slices: the raw weight plateau ties most
    # candidates at the same max (useless as an argmax), so instead sort
    # candidates by weight and grade the top X% slice as if it were the
    # argmax set. hit% = truth inside the top slice; max_val = the top
    # weight in the slice. Only emitted while spawn fairness is active —
    # weights are all-zero otherwise and the slices would be arbitrary.
    if sf_active:
        sf_ranked = sorted(
            candidates,
            key=lambda t: sf_weights.raw[t.tile_index],
            reverse=True)
        for metric_name, frac in (
                ('sf1/10', 0.1), ('sf1/5', 0.2), ('sf1/4', 0.25),
                ('sf1/3', 1.0 / 3.0), ('sf1/2', 0.5)):
            top_n = max(1, math.ceil(len(sf_ranked) * frac))
            top_set = set(sf_ranked[:top_n])
            row = base_row(metric_name)
            # max_val = the top weight IN the slice (the slice's true max),
            # not the cutoff weight at the boundary — reporting the cutoff
            # made avg_max_score sit below avg_score_at_true, which is
            # nonsense since truth always holds the max fairness weight.
            row.max_val = sf_weights.raw[sf_ranked[0].tile_index]
            row.argmax_count = len(top_set)
            dists = [manhattan(t, true_tile) for t in top_set]
            row.closest = min(dists)
            row.furthest = max(dists)
            row.argmax_avg = sum(dists) / len(dists)
            row.true_val = sf_weights.raw[true_tile.tile_index]
            row.pred_val = (
                sf_weights.raw[pred_tile.tile_index]
                if pred_tile is not None else None)
            row.true_in_argmax = 1.0 if true_tile in top_set else 0.0
            outscoring = sum(
                1 for t in candidates
                if sf_weights.raw[t.tile_index] > row.true_val)
            row.true_rank = outscoring / len(candidates)
            rows.append(row)

    pred_row = base_row('predicted')
    pred_row.argmax_count = 1
    pred_row.closest = pred_dist
    pred_row.furthest = pred_dist
    pred_row.argmax_avg = pred_dist
    pred_row.true_in_argmax = 1.0 if pred_dist == 0 else 0.0
    rows.append(pred_row)
    return rows


# ---------------------------------------------------------------------------
# aggregation + reporting
# ---------------------------------------------------------------------------


def mean_or_none(vals: typing.Iterable[float | int | None]) -> float | None:
    """Mean of non-None values; None when empty."""
    nums = [v for v in vals if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)


def fmt(v: float | int | None, digits: int = 2) -> str:
    """Format an optional float for the fixed-width report."""
    if v is None:
        return '-'
    return f'{v:.{digits}f}'


def summarize_rows(rows: typing.List[MetricRow]) -> typing.Dict[str, float | None]:
    """Mean stats for one metric over a row collection."""
    return {
        'closest': mean_or_none(r.closest for r in rows),
        'furthest': mean_or_none(r.furthest for r in rows),
        'avg_dist': mean_or_none(r.argmax_avg for r in rows),
        'max_val': mean_or_none(r.max_val for r in rows),
        'true_val': mean_or_none(r.true_val for r in rows),
        'pred_val': mean_or_none(r.pred_val for r in rows),
        'argmax': mean_or_none(r.argmax_count for r in rows),
        'max_pct': mean_or_none(
            r.argmax_count / r.candidates for r in rows if r.candidates > 0),
        'hit': mean_or_none(r.true_in_argmax for r in rows),
        'rank': mean_or_none(r.true_rank for r in rows),
        'pred_dist': mean_or_none(r.pred_dist for r in rows),
        'true_in_valid': mean_or_none(r.true_in_valid for r in rows),
        'candidates': mean_or_none(r.candidates for r in rows),
    }


def table_lines(
        title: str,
        metric_summaries: typing.List[typing.Tuple[str, int, int, typing.Dict[str, float | None]]]
) -> typing.List[str]:
    """Render one fixed-width aggregate table."""
    lines = [
        '',
        f'=== {title} ===',
        f'{"metric":<16} {"maxN":>6} {"closest":>8} {"furthest":>8} '
        f'{"avgD":>8} '
        f'{"maxVal":>9} {"trueVal":>9} {"trMx%":>6} '
        f'{"predVal":>9} {"trPr%":>6} {"hit%":>6} '
        f'{"maxPct":>6} {"rank%":>6} {"predD":>6} {"cand":>6} '
        f'{"games":>5} {"turns":>6}',
    ]
    for metric, games_n, turns_n, s in metric_summaries:
        hit = s['hit'] * 100 if s['hit'] is not None else None
        max_pct = s['max_pct'] * 100 if s['max_pct'] is not None else None
        rank = s['rank'] * 100 if s['rank'] is not None else None
        true_max = pct_ratio(s['true_val'], s['max_val'])
        true_pred = pct_ratio(s['true_val'], s['pred_val'])
        lines.append(
            f'{metric:<16} {fmt(s["argmax"]):>6} {fmt(s["closest"]):>8} '
            f'{fmt(s["furthest"]):>8} {fmt(s["avg_dist"]):>8} '
            f'{fmt(s["max_val"]):>9} {fmt(s["true_val"]):>9} '
            f'{fmt(true_max, 1):>6} '
            f'{fmt(s["pred_val"]):>9} {fmt(true_pred, 1):>6} {fmt(hit, 1):>6} '
            f'{fmt(max_pct, 1):>6} {fmt(rank, 1):>6} '
            f'{fmt(s["pred_dist"]):>6} {fmt(s["candidates"], 1):>6} '
            f'{games_n:>5} {turns_n:>6}')
    return lines


def pct_ratio(numer: float | None, denom: float | None) -> float | None:
    """numer/denom as a 0-100 percent, or None when undefined."""
    if numer is None or denom in (None, 0):
        return None
    return numer / denom * 100.0


def write_summary_xlsx(
        path: Path,
        by_turn: typing.List[typing.Tuple[str, int, int, typing.Dict[str, float | None]]],
        by_game: typing.List[typing.Tuple[str, int, int, typing.Dict[str, float | None]]]) -> None:
    """Write the aggregate tables as a formatted .xlsx matching the hand-built
    Sheets version: same layout and widths, a footnote row of column
    descriptions under the data, and 3-color conditional formatting.

    Distance columns center their scale at the block's pred_dist_to_true, so a
    metric shades green exactly when its argmax tiles land nearer the true
    general than the live pick did on average. The pct_*_score ratio columns
    are live formulas centered at a fixed 50% midpoint; avg_score_at_true /
    avg_score_at_pred carry baked fills matching the color their ratio cell
    earns on that same scale (color scales can't read a neighbor's value, so
    the score cells get the computed fill directly)."""
    GREEN = 'FF57BB8A'
    WHITE = 'FFFFFFFF'
    RED = 'FFE67C73'

    headers = [
        'aggregation', 'description', 'metric', 'avg_tiles_at_max',
        'closest_argmax_dist', 'furthest_argmax_dist', 'avg_argmax_dist',
        'avg_max_score', 'avg_score_at_true', 'pct_true_score_vs_max',
        'avg_score_at_pred', 'pct_true_score_vs_pred',
        'pct_true_ties_max', 'pct_cands_at_max',
        'pct_cands_above_true', 'pred_dist_to_true', 'avg_cands',
        'games', 'turns']
    footnotes: typing.Dict[str, str] = {
        'D': "average number of candidate tiles tied at the metric's max "
             'score; ~1 means a sharp unique peak, large means a plateau.',
        'E': "Manhattan distance from the true general to the nearest tile "
             "tied for the metric's maximum score, averaged over turns.",
        'F': 'same, but to the furthest max-tied tile; equals closest when '
             'only one tile ties for max.',
        'G': 'mean Manhattan distance from the true general across ALL tiles '
             "tied for the metric's max, averaged over turns — for wide "
             'plateau metrics this is the honest center of where the metric '
             'points.',
        'H': "the metric's highest score achieved by any candidate tile that "
             'turn, averaged.',
        'I': "the metric's score evaluated at the true general tile (even "
             "though it's not a candidate), averaged.",
        'J': 'avg_score_at_true / avg_max_score as a percent — what fraction '
             'of the best score the true tile captured. Higher = the metric '
             'nearly maxes at truth.',
        'K': 'the metric\'s score evaluated at the tile the bot actually '
             'picked, averaged; comparing it to avg_max_score shows how '
             'justified the pick was under that metric.',
        'L': 'avg_score_at_true / avg_score_at_pred as a percent — how '
             "truth's score compares to the pick's under this metric. "
             'Higher = the metric prefers truth over its own pick.',
        'M': 'percent of turns where the true general tile was in the '
             'max-tied set (the metric\'s "hit rate").',
        'N': 'avg_tiles_at_max as a percent of all valid candidates; how much '
             'of the candidate set shares the top score.',
        'O': 'average percent of candidates scoring strictly above the true '
             "general tile (truth's percentile rank: 0 = nothing outscored "
             'truth, 50 = truth is mid-pack).',
        'P': 'Manhattan distance between the bot\'s serialized prediction and '
             'the true general, averaged; the bottom-line accuracy of the '
             'live pick.',
        'Q': 'average number of valid candidate tiles evaluated per turn.',
    }

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'general_prediction_summary'
    ws.append(headers)
    for col_idx, width in enumerate(
            (9.8, 94.9, 14.0, 14.0, 16.2, 16.5, 15.0, 12.0, 14.8, 18.5, 15.2,
             18.5, 14.6, 15.0, 17.9, 14.0, 9.0, 6.0, 4.8), start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    def pct_of(v: float | None) -> float | None:
        return None if v is None else v * 100.0

    # (excel_row, max_val, true_val, pred_val) per data row — the score cells
    # get baked fills matched to the ratio columns' scale below.
    row_scores: typing.List[typing.Tuple[int, float | None, float | None, float | None]] = []
    block_bounds: typing.List[typing.Tuple[int, int, float | None]] = []
    for agg_name, summaries in (('by_turn', by_turn), ('by_game', by_game)):
        first_row = ws.max_row + 1
        pred_anchor: float | None = None
        for metric, games_n, turns_n, s in summaries:
            row_i = ws.max_row + 1
            ws.append([
                agg_name, METRIC_DESCRIPTIONS[metric], metric, s['argmax'],
                s['closest'], s['furthest'], s['avg_dist'],
                s['max_val'], s['true_val'],
                None, s['pred_val'], None,
                pct_of(s['hit']),
                pct_of(s['max_pct']), pct_of(s['rank']),
                s['pred_dist'], s['candidates'], games_n, turns_n])
            for col in (4, 5, 6, 7, 8, 9, 11, 13, 14, 15, 16, 17):
                ws.cell(row=row_i, column=col).number_format = '0.00'
            for col in (10, 12):
                ws.cell(row=row_i, column=col).number_format = '0%'
            ws.cell(row=row_i, column=10).value = f'=IF(H{row_i}=0,"",I{row_i}/H{row_i})'
            ws.cell(row=row_i, column=12).value = f'=IF(K{row_i}=0,"",I{row_i}/K{row_i})'
            row_scores.append((row_i, s['max_val'], s['true_val'], s['pred_val']))
            if pred_anchor is None and s['pred_dist'] is not None:
                pred_anchor = s['pred_dist']
        block_bounds.append((first_row, ws.max_row, pred_anchor))

    footnote_row = ws.max_row + 1
    for letter, text in footnotes.items():
        cell = ws[f'{letter}{footnote_row}']
        cell.value = text
        cell.alignment = Alignment(wrap_text=True, vertical='top')
    # Wrapped footnotes don't auto-size row height in Excel — estimate lines
    # from each column's width so the whole description is visible.
    est_lines = max(
        math.ceil(len(text) / max(ws.column_dimensions[letter].width - 2, 8))
        for letter, text in footnotes.items()) if footnotes else 1
    ws.row_dimensions[footnote_row].height = est_lines * 13.5 + 4

    # Distance columns: green at/below 1.0 (essentially exact), white exactly
    # at the block's pred_dist_to_true, saturated red at 1.5x the pick's
    # distance — a fixed band so values aren't crushed into data-min/max.
    for first_row, last_row, anchor in block_bounds:
        if anchor is None:
            continue
        for col in ('E', 'F', 'G'):
            ws.conditional_formatting.add(
                f'{col}{first_row}:{col}{last_row}',
                ColorScaleRule(
                    start_type='num', start_value=1.0, start_color=GREEN,
                    mid_type='num', mid_value=anchor, mid_color=WHITE,
                    end_type='num', end_value=anchor * 1.5, end_color=RED))

    # pct_true_score_vs_max / pct_pred_score_vs_true: live formulas shaded on a
    # fixed 50% midpoint — green = the truth/pick score nears the best score.
    last_data_row = footnote_row - 1
    if last_data_row >= 2:
        # pct_true_score_vs_max: green when truth captures most of the max.
        ws.conditional_formatting.add(
            f'J2:J{last_data_row}',
            ColorScaleRule(
                start_type='min', start_color=RED,
                mid_type='num', mid_value=0.5, mid_color=WHITE,
                end_type='max', end_color=GREEN))
        # pct_true_score_vs_pred: fixed 50%-150% band — red at/below 50%
        # (truth scores half or less of the wrong pick), white at 100%,
        # green at/above 150% (metric strongly prefers truth over its pick).
        ws.conditional_formatting.add(
            f'L2:L{last_data_row}',
            ColorScaleRule(
                start_type='num', start_value=0.5, start_color=RED,
                mid_type='num', mid_value=1.0, mid_color=WHITE,
                end_type='num', end_value=1.5, end_color=GREEN))

        # Ratio columns centered at the column median: hit% and plateau share
        # green at max; tied-tile count and pct_cands_above_true shade green
        # at min (fewer tiles outscoring truth = truth ranked higher).
        for col, start_c, end_c in (
                ('D', GREEN, RED), ('M', RED, GREEN),
                ('N', RED, GREEN), ('O', GREEN, RED)):
            ws.conditional_formatting.add(
                f'{col}2:{col}{last_data_row}',
                ColorScaleRule(
                    start_type='min', start_color=start_c,
                    mid_type='percentile', mid_value=50, mid_color=WHITE,
                    end_type='max', end_color=end_c))

    # Baked fills matching each ratio column's color: avg_score_at_true gets
    # pct_true_score_vs_max's color, avg_score_at_pred gets
    # pct_pred_score_vs_true's (a color scale can't read a neighbor's value).
    def rgb_of(c: str) -> typing.Tuple[int, int, int]:
        return int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16)

    def scale_fill(v: float, lo: float, mid: float, hi: float) -> PatternFill:
        if v <= mid:
            t = min(1.0, max(0.0, (v - lo) / max(mid - lo, 1e-9)))
            c0, c1 = rgb_of(RED), rgb_of(WHITE)
        else:
            t = min(1.0, max(0.0, (v - mid) / max(hi - mid, 1e-9)))
            c0, c1 = rgb_of(WHITE), rgb_of(GREEN)
        rgb = f'FF{round(c0[0] + (c1[0] - c0[0]) * t):02X}' \
              f'{round(c0[1] + (c1[1] - c0[1]) * t):02X}' \
              f'{round(c0[2] + (c1[2] - c0[2]) * t):02X}'
        return PatternFill(start_color=rgb, end_color=rgb, fill_type='solid')

    i_vals = [
        true_v / max_v
        for _r, max_v, true_v, _p in row_scores
        if max_v not in (None, 0) and true_v is not None]
    i_lo, i_hi = (min(i_vals), max(i_vals)) if i_vals else (0.0, 1.0)
    for row_i, max_v, true_v, pred_v in row_scores:
        if max_v not in (None, 0) and true_v is not None:
            ws.cell(row=row_i, column=9).fill = scale_fill(
                true_v / max_v, i_lo, 0.5, i_hi)
        if true_v is not None and pred_v not in (None, 0):
            ws.cell(row=row_i, column=11).fill = scale_fill(
                true_v / pred_v, 0.5, 1.0, 1.5)

    wb.save(path)


def process_game(plan: GamePlan, args: Args, generals_events_repo: str) -> GameResult:
    """Dump the true map once, then evaluate every qualifying turn."""
    first_q = plan.qualifying[0]
    true_path, unverified, note = dump_true_map(plan, first_q, generals_events_repo)
    if true_path is None and len(plan.qualifying) > 1:
        # retry once from the last qualifying turn (some replays can't sim the first)
        true_path, unverified, note = dump_true_map(plan, plan.qualifying[-1], generals_events_repo)
    notes = [note]
    if true_path is None:
        return GameResult(plan.folder.name, plan.replay_id, plan.player_index,
                          plan.enemy_index, -1, -1, 0, [], plan.known_general_turns, 0,
                          notes + ['NO TRUE MAP — skipped'])
    true_xy = find_enemy_general_in_truemap(true_path, plan.enemy_index)
    if true_xy is None:
        return GameResult(plan.folder.name, plan.replay_id, plan.player_index,
                          plan.enemy_index, -1, -1, int(unverified), [],
                          plan.known_general_turns, 0,
                          notes + [f'no {plan.enemy_char}G cell in {true_path.name} — skipped'])

    rows: typing.List[MetricRow] = []
    error_turns = 0
    for tf in plan.qualifying:
        try:
            rows.extend(evaluate_turn(plan, tf, true_xy, unverified, args.skip_precontact))
        except Exception:
            error_turns += 1
            logbook.error(
                f'{plan.folder.name} t{tf.turn} reconstruction failed:\n{traceback.format_exc()}')
            if args.strict:
                raise
    if error_turns:
        notes.append(f'{error_turns} turns failed reconstruction (see scan.log)')
    return GameResult(
        plan.folder.name, plan.replay_id, plan.player_index, plan.enemy_index,
        true_xy[0], true_xy[1], int(unverified), rows,
        plan.known_general_turns, error_turns, notes)


def write_outputs(games: typing.List[GameResult], skipped: typing.List[typing.Tuple[str, str]],
                  args: Args, out_dir: Path) -> Path:
    """Write the per-turn CSV, per-game CSV and readable report."""
    csv_path = out_dir / 'general_prediction_metrics.csv'
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(CSV_FIELDS)
        for g in games:
            for r in g.rows:
                writer.writerow([
                    g.game, g.replay_id, r.turn, r.metric,
                    r.max_val, r.argmax_count, r.closest, r.furthest,
                    r.argmax_avg,
                    r.true_val, r.pred_val, r.true_in_argmax, r.true_rank,
                    r.candidates, r.valid_serialized, r.valid_loaded,
                    r.emg_sources, r.expected_dist,
                    r.pred_x, r.pred_y, r.pred_dist,
                    r.true_x, r.true_y, r.true_in_valid,
                    r.unverified, r.error])

    games_csv = out_dir / 'general_prediction_games.csv'
    with open(games_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'game', 'replay_id', 'player_index', 'enemy_index',
            'true_x', 'true_y', 'unverified', 'turns_evaluated',
            'avg_valid_loaded', 'avg_candidates', 'avg_emg_sources',
            'avg_pred_dist', 'known_general_turns', 'error_turns', 'notes'])
        for g in games:
            turns = {r.turn for r in g.rows}
            writer.writerow([
                g.game, g.replay_id, g.player_index, g.enemy_index,
                g.true_x, g.true_y, g.unverified, len(turns),
                fmt(mean_or_none(r.valid_loaded for r in g.rows)),
                fmt(mean_or_none(r.candidates for r in g.rows)),
                fmt(mean_or_none(r.emg_sources for r in g.rows)),
                fmt(mean_or_none(r.pred_dist for r in g.rows)),
                g.known_general_turns, g.error_turns, '; '.join(g.notes)])

    lines: typing.List[str] = [
        '=== PARAMETERS ===',
        f'scan_root={args.scan_root}  min_emergences={args.min_emergences}  '
        f'min_valid_positions>{args.min_valid_positions}  '
        f'second_half_after={args.second_half_after}  turn_stride={args.turn_stride}  '
        f'skip_precontact={args.skip_precontact}',
        f'games evaluated: {len(games)}   folders skipped: {len(skipped)}',
        '',
        '=== METRIC LEGEND ===',
    ]
    for metric in ALL_METRICS:
        lines.append(f'  {metric:<16} {METRIC_DESCRIPTIONS[metric]}')
    lines += [
        '',
        'columns: closest/furthest/avgD = manhattan distance of the '
        'nearest/furthest/mean-of-all argmax-tied tiles to the true general | '
        'maxVal = avg top score any '
        'candidate got | trueVal = score at the true general tile | '
        'trMx% = trueVal/maxVal as % (fraction of the best score truth '
        'captured) | predVal = score at the live pick tile (vs maxVal = how '
        'justified the pick was under that metric) | trPr% = trueVal/predVal '
        'as % | hit% = turns where truth ties the argmax | maxN = avg # tiles '
        'tied at max | maxPct = avg fraction of candidates tied at max | '
        'rank% = avg fraction of candidates outscoring truth | predD = '
        'distance of the serialized pick | cand = avg candidate tiles',
        '',
        '=== SKIPPED FOLDERS ===',
    ]
    for name, reason in skipped:
        lines.append(f'  {name}: {reason}')
    lines.append('')
    lines.append('=== PER-GAME ===')
    for g in games:
        turns = {r.turn for r in g.rows}
        lines.append(
            f'{g.game}  replay={g.replay_id}  enemy=p{g.enemy_index}  '
            f'trueGen=({g.true_x},{g.true_y})  turns={len(turns)}  '
            f'avgPredDist={fmt(mean_or_none(r.pred_dist for r in g.rows))}  '
            f'avgValid={fmt(mean_or_none(r.valid_loaded for r in g.rows))}  '
            f'avgEmg={fmt(mean_or_none(r.emg_sources for r in g.rows))}'
            + ('  [UNVERIFIED TRUMAP]' if g.unverified else '')
            + (f'  notes: {"; ".join(g.notes)}' if g.notes else ''))

    # By Turn: every qualifying turn pooled.
    all_rows = [r for g in games for r in g.rows]
    by_turn = []
    for metric in ALL_METRICS:
        mrows = [r for r in all_rows if r.metric == metric]
        if not mrows:
            continue
        by_turn.append((metric, len(games), len(mrows), summarize_rows(mrows)))
    lines += table_lines('BY TURN (every qualifying turn pooled equally)', by_turn)

    # By Game: mean within each game first, then across games equally.
    by_game = []
    for metric in ALL_METRICS:
        game_means = []
        game_turns = 0
        for g in games:
            mrows = [r for r in g.rows if r.metric == metric]
            if mrows:
                game_means.append(summarize_rows(mrows))
                game_turns += len(mrows)
        if not game_means:
            continue
        pooled = {k: mean_or_none(m[k] for m in game_means) for k in game_means[0]}
        by_game.append((metric, len(game_means), game_turns, pooled))
    lines += table_lines('BY GAME (per-game means averaged across games)', by_game)

    def csvnum(v: float | int | None) -> str:
        return '' if v is None else f'{v:.4g}'

    def pct100(v: float | None) -> str:
        return '' if v is None else f'{v * 100:.4g}'

    # Sheet-friendly flat table: one row per (aggregation, metric) with every
    # aggregate stat plus the metric's plain-language description.
    summary_csv = out_dir / 'general_prediction_summary.csv'
    with open(summary_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'aggregation', 'description', 'metric', 'avg_tiles_at_max',
            'closest_argmax_dist', 'furthest_argmax_dist', 'avg_argmax_dist',
            'avg_max_score', 'avg_score_at_true', 'pct_true_score_vs_max',
            'avg_score_at_pred', 'pct_true_score_vs_pred',
            'pct_true_ties_max', 'pct_cands_at_max',
            'pct_cands_above_true', 'pred_dist_to_true', 'avg_cands',
            'games', 'turns'])
        for agg_name, summaries in (('by_turn', by_turn), ('by_game', by_game)):
            for metric, games_n, turns_n, s in summaries:
                writer.writerow([
                    agg_name, METRIC_DESCRIPTIONS[metric], metric,
                    csvnum(s['argmax']),
                    csvnum(s['closest']), csvnum(s['furthest']),
                    csvnum(s['avg_dist']),
                    csvnum(s['max_val']), csvnum(s['true_val']),
                    csvnum(pct_ratio(s['true_val'], s['max_val'])),
                    csvnum(s['pred_val']),
                    csvnum(pct_ratio(s['true_val'], s['pred_val'])),
                    pct100(s['hit']), pct100(s['max_pct']),
                    pct100(s['rank']), csvnum(s['pred_dist']),
                    csvnum(s['candidates']), games_n, turns_n])

    xlsx_path = out_dir / 'general_prediction_summary.xlsx'
    write_summary_xlsx(xlsx_path, by_turn, by_game)

    report_path = out_dir / 'general_prediction_report.txt'
    report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    LOGGER.info(f'wrote {csv_path}')
    LOGGER.info(f'wrote {games_csv}')
    LOGGER.info(f'wrote {summary_csv}')
    LOGGER.info(f'wrote {xlsx_path}')
    LOGGER.info(f'wrote {report_path}')
    return report_path


def parse_args(argv: typing.Sequence[str] | None) -> Args:
    """CLI parsing."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scan-root', default='',
                   help='grouped game logs root (default: grouped_folder from run_config.txt)')
    p.add_argument('--out', default=str(DEFAULT_OUTPUT_ROOT), help='output directory')
    p.add_argument('--max-games', type=int, default=20, help='max recent games to scan')
    p.add_argument('--min-emergences', type=int, default=6,
                   help='minimum enemy emergence sources required to qualify a turn')
    p.add_argument('--min-valid-positions', type=int, default=15,
                   help='only evaluate turns where MORE than this many valid enemy-general tiles remain')
    p.add_argument('--second-half-after', type=float, default=0.5,
                   help='only evaluate turns after last_turn * this fraction')
    p.add_argument('--turn-stride', type=int, default=1, help='evaluate every Nth qualifying turn')
    p.add_argument('--game-filter', default='', help='substring filter on folder names')
    p.add_argument('--generals-events-repo', default='',
                   help='path to generals-events repo (default: run_config.txt value)')
    p.add_argument('--skip-precontact', action='store_true',
                   help='skip the expensive per-candidate-BFS precontact grid')
    p.add_argument('--strict', action='store_true',
                   help='re-raise per-turn reconstruction errors instead of logging+skipping')
    ns = p.parse_args(argv)
    return Args(
        scan_root=ns.scan_root, out=ns.out, max_games=ns.max_games,
        min_emergences=ns.min_emergences, min_valid_positions=ns.min_valid_positions,
        second_half_after=ns.second_half_after, turn_stride=ns.turn_stride,
        game_filter=ns.game_filter, generals_events_repo=ns.generals_events_repo,
        skip_precontact=ns.skip_precontact, strict=ns.strict)


def main(argv: typing.Sequence[str] | None = None) -> int:
    """Scan recent 1v1 folders, evaluate metrics, write CSV + report."""
    args = parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    logbook.FileHandler(
        str(out_dir / 'scan.log'), level=logbook.INFO, mode='w', bubble=True
    ).push_application()
    logbook.StreamHandler(
        sys.stdout, level=logbook.INFO,
        filter=lambda record, _h: record.channel == LOG_CHANNEL, bubble=True
    ).push_application()

    # Batch-mode safety: a stray debug assert must not kill a multi-game scan.
    EarlyExpandUtils.DEBUG_ASSERTS = False
    GatherDebug.USE_DEBUG_ASSERTS = False
    SearchUtils.BYPASS_TIMEOUTS_FOR_DEBUGGING = False
    base.client.map.ENABLE_DEBUG_ASSERTS = False

    removed = cleanup_replay_dump_cache()
    if removed:
        LOGGER.info(f'cleared {removed} replay-dump cache file(s) older than '
                    f'{REPLAY_DUMP_CACHE_MAX_AGE_DAYS} days')

    cfg = read_run_config()
    scan_root = Path(args.scan_root) if args.scan_root else Path(cfg.get('grouped_folder', '.'))
    args.scan_root = str(scan_root)
    generals_events_repo = args.generals_events_repo or cfg.get('generals_events_repo', '')
    if not scan_root.is_dir():
        LOGGER.error(f'scan root {scan_root} does not exist')
        return 2

    folders = list_game_folders(scan_root, args)
    LOGGER.info(f'scanning {len(folders)} recent folders under {scan_root}')

    games: typing.List[GameResult] = []
    skipped: typing.List[typing.Tuple[str, str]] = []
    for i, folder in enumerate(folders):
        plan = build_game_plan(folder, args)
        if plan.skip_reason:
            LOGGER.info(f'[{i + 1}/{len(folders)}] {folder.name}: skipped ({plan.skip_reason})')
            skipped.append((folder.name, plan.skip_reason))
            continue
        LOGGER.info(
            f'[{i + 1}/{len(folders)}] {folder.name}: {len(plan.qualifying)} qualifying turns '
            f'(launch~t{plan.launch_estimate}, last t{plan.last_turn})')
        result = process_game(plan, args, generals_events_repo)
        if result.rows:
            games.append(result)
        else:
            skipped.append((folder.name, '; '.join(result.notes) or 'no turns evaluated'))
            if result.notes:
                games.append(result)

    report_path = write_outputs(games, skipped, args, out_dir)
    turns_total = sum(len({r.turn for r in g.rows}) for g in games)
    LOGGER.info(f'done: {len(games)} games, {turns_total} turns evaluated. Report: {report_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
