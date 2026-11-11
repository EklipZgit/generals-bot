"""Generate turn and round statistics from live txtmap snapshots.

Enemy city and player values may be fog estimates because the bot's txtmaps
contain its observed map state rather than an omniscient server snapshot.
"""

from __future__ import annotations

import argparse
import csv
import logbook
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from Sim.TextMapLoader import TextMapLoader

from LiveGameAnalysis.GameLogIndex import GameLogIndex, TurnBlock


DEFAULT_OUTPUT_ROOT = Path(r"C:\cascade-debug-output\generals-bot\game_analysis")
BOT_FLAG_FIELDS = (
    "bot_is_all_in_losing",
    "bot_all_in_losing_counter",
    "bot_is_all_in_army_advantage",
    "bot_defend_economy",
    "bot_is_winning_gather_cyclic",
    "bot_all_in_city_behind",
    "bot_is_rapid_capturing_neut_cities",
    "bot_finishing_exploration",
    "bot_target_player",
    "bot_cur_path",
)
_PLAYER_NAME_PATTERN = re.compile(r"^([a-z])Username$")


@dataclass(slots=True)
class PlayerTurnStats:
    """Per-player counters parsed from one txtmap snapshot."""

    char: str
    name: str | None
    tiles: int | None
    score: int | None
    standing_army: int | None
    cities: int | None
    econ: int | None
    army_spent_or_lost: int | None
    visible_cities: int
    city_lost_turn: int | None


@dataclass(slots=True)
class TurnSnapshot:
    """All parsed statistics and city ownership for one txtmap."""

    turn: int
    round_number: int
    bot_player: str | None
    players: dict[str, PlayerTurnStats]
    city_owners: dict[tuple[int, int], int]
    team_ids: tuple[int, ...]
    bot_is_all_in_losing: str | None
    bot_all_in_losing_counter: str | None
    bot_is_all_in_army_advantage: str | None
    bot_defend_economy: str | None
    bot_is_winning_gather_cyclic: str | None
    bot_all_in_city_behind: str | None
    bot_is_rapid_capturing_neut_cities: str | None
    bot_finishing_exploration: str | None
    bot_target_player: str | None
    bot_cur_path: str | None
    bot_move: str | None
    decision_scope: str | None
    decision_hint: str | None
    turn_duration: float | None
    problems: str


@dataclass(slots=True)
class RoundPlayerStats:
    """Round deltas and contested-city diagnostics for one player."""

    tiles_delta: int | None
    score_delta: int | None
    army_spent_or_lost: int
    cities_gained: int
    cities_lost: int
    last_new_city_turn: int | None
    contested_cities: str
    contesting: bool


@dataclass(slots=True)
class RoundStats:
    """One selected round-end snapshot and its per-player changes."""

    turn: int
    round_number: int
    snapshot: TurnSnapshot
    players: dict[str, RoundPlayerStats]
    bot_econ_diff: int | None
    bot_score_diff: int | None
    bot_tiles_diff: int | None
    bot_cities_diff: int | None


def load_snapshots(folder: str, log_index: GameLogIndex | None = None) -> list[TurnSnapshot]:
    """Parse numerically sorted txtmaps, optionally joining their log turns."""
    map_files = sorted(
        Path(folder).glob("*.txtmap"),
        key=lambda path: int(path.stem))
    if not map_files:
        raise ValueError(f"No numeric txtmap snapshots found in {folder}")
    raw_maps: list[tuple[int, dict[str, str], dict[tuple[int, int], int]]] = []
    for map_file in map_files:
        raw = map_file.read_text(encoding="utf-8", errors="replace")
        data = TextMapLoader.load_data_from_string(raw)
        turn = int(data.get("turn", map_file.stem))
        grid = TextMapLoader.load_map_from_string(raw)
        city_owners: dict[tuple[int, int], int] = {}
        visible_cities: dict[str, int] = {}
        for row in grid:
            for tile in row:
                if tile.isCity or tile.isGeneral:
                    city_owners[(tile.x, tile.y)] = tile.player
                    if tile.player >= 0:
                        player_char = chr(ord("a") + tile.player)
                        visible_cities[player_char] = visible_cities.get(player_char, 0) + 1
        raw_maps.append((turn, data, city_owners))

    snapshots: list[TurnSnapshot] = []
    previous_turn: TurnSnapshot | None = None
    previous_data: dict[str, str] | None = None
    for turn, data, city_owners in raw_maps:
        snapshot = _build_turn_snapshot(
            turn,
            data,
            city_owners,
            previous_turn,
            previous_data,
            log_index)
        snapshots.append(snapshot)
        previous_turn = snapshot
        previous_data = data
    return snapshots


def generate_round_stats(snapshots: list[TurnSnapshot]) -> list[RoundStats]:
    """Build summary rows at 50-tick boundaries and at the final snapshot."""
    by_turn = {snapshot.turn: snapshot for snapshot in snapshots}
    all_turns = [snapshot.turn for snapshot in snapshots]
    final_turn = all_turns[-1]
    checkpoints: list[TurnSnapshot] = []
    for target in range(50, final_turn + 1, 50):
        closest_turn = min(all_turns, key=lambda turn: (abs(turn - target), turn))
        checkpoint = by_turn[closest_turn]
        if checkpoint not in checkpoints:
            checkpoints.append(checkpoint)
    if not checkpoints or checkpoints[-1].turn != final_turn:
        checkpoints.append(snapshots[-1])

    result: list[RoundStats] = []
    previous_checkpoint: TurnSnapshot | None = None
    for checkpoint in checkpoints:
        result.append(_build_round_stats(
            snapshots,
            checkpoint,
            previous_checkpoint))
        previous_checkpoint = checkpoint
    return result


def write_stats(
    folder: str,
    out_dir: str | None = None,
) -> tuple[Path, Path]:
    """Generate wide per-turn and round CSV files and return their paths."""
    folder_path = Path(folder)
    log_files = sorted(folder_path.glob("_*.txt"))
    log_index = GameLogIndex.load(GameLogIndex.find_log_file(folder)) if log_files else None
    snapshots = load_snapshots(folder, log_index)
    round_stats = generate_round_stats(snapshots)
    destination = Path(out_dir) if out_dir else DEFAULT_OUTPUT_ROOT / folder_path.name
    destination.mkdir(parents=True, exist_ok=True)
    turns_path = destination / f"{folder_path.name}_turns.csv"
    rounds_path = destination / f"{folder_path.name}_rounds.csv"
    _write_turn_csv(turns_path, snapshots)
    _write_round_csv(rounds_path, round_stats)
    return turns_path, rounds_path


def main(argv: Sequence[str] | None = None) -> int:
    """Run the stats generator CLI and log the resulting CSV paths."""
    logbook.StreamHandler(sys.stdout, level=logbook.INFO).push_application()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    parser.add_argument("--out-dir")
    arguments = parser.parse_args(argv)
    turns_path, rounds_path = write_stats(arguments.folder, arguments.out_dir)
    logbook.info("Wrote turn statistics to {}", turns_path)
    logbook.info("Wrote round statistics to {}", rounds_path)
    return 0


def _build_turn_snapshot(
    turn: int,
    data: dict[str, str],
    city_owners: dict[tuple[int, int], int],
    previous: TurnSnapshot | None,
    previous_data: dict[str, str] | None,
    log_index: GameLogIndex | None,
) -> TurnSnapshot:
    """Parse player fields and compute tick-based expected army generation."""
    chars = sorted(
        match.group(1)
        for key in data
        for match in [_PLAYER_NAME_PATTERN.match(key)]
        if match is not None)
    bot_index = int(data["player_index"]) if "player_index" in data else -1
    bot_char = chr(ord("a") + bot_index) if bot_index >= 0 else None
    players: dict[str, PlayerTurnStats] = {}
    for char in chars:
        tiles = _optional_int(data, f"{char}Tiles")
        score = _optional_int(data, f"{char}Score")
        standing_army = _optional_int(data, f"{char}StandingArmy")
        cities = _optional_int(data, f"{char}CityCount")
        econ = tiles + 25 * cities if tiles is not None and cities is not None else None
        spent_or_lost: int | None = None
        if previous is not None and previous_data is not None:
            previous_player = previous.players[char]
            if score is not None and previous_player.score is not None:
                previous_turn = previous.turn
                previous_tiles = previous_player.tiles or 0
                previous_cities = previous_player.cities or 0
                expected_generation = (
                    previous_cities * (turn // 2 - previous_turn // 2)
                    + previous_tiles * (turn // 50 - previous_turn // 50))
                spent_or_lost = expected_generation - (score - previous_player.score)
        visible_cities = sum(
            1 for owner in city_owners.values() if owner == ord(char) - ord("a"))
        players[char] = PlayerTurnStats(
            char,
            data.get(f"{char}Username"),
            tiles,
            score,
            standing_army,
            cities,
            econ,
            spent_or_lost,
            visible_cities,
            _optional_int(data, f"{char}CityLostTurn"))

    log_turn: TurnBlock | None = log_index.turns.get(turn) if log_index is not None else None
    team_values = tuple(int(team) for team in data["teams"].split(",")) if "teams" in data else ()
    return TurnSnapshot(
        turn,
        turn // 50,
        bot_char,
        players,
        city_owners,
        team_values,
        data.get("bot_is_all_in_losing"),
        data.get("bot_all_in_losing_counter"),
        data.get("bot_is_all_in_army_advantage"),
        data.get("bot_defend_economy"),
        data.get("bot_is_winning_gather_cyclic"),
        data.get("bot_all_in_city_behind"),
        data.get("bot_is_rapid_capturing_neut_cities"),
        data.get("bot_finishing_exploration"),
        data.get("bot_target_player"),
        data.get("bot_cur_path"),
        log_turn.move_text if log_turn is not None else None,
        log_turn.decision_scope if log_turn is not None else None,
        log_turn.decision_hint if log_turn is not None else None,
        log_turn.turn_duration if log_turn is not None else None,
        ";".join(log_turn.problems) if log_turn is not None else "")


def _build_round_stats(
    snapshots: list[TurnSnapshot],
    checkpoint: TurnSnapshot,
    previous_checkpoint: TurnSnapshot | None,
) -> RoundStats:
    """Accumulate player deltas, city changes, and enemy comparisons."""
    checkpoint_index = snapshots.index(checkpoint)
    previous_index = snapshots.index(previous_checkpoint) if previous_checkpoint is not None else -1
    interval = snapshots[previous_index + 1:checkpoint_index + 1]
    baseline = previous_checkpoint or interval[0]
    last_new_city_turn: dict[str, int] = {}
    city_gains: dict[str, int] = {char: 0 for char in checkpoint.players}
    city_losses: dict[str, int] = {char: 0 for char in checkpoint.players}
    contested_coords: dict[str, set[tuple[int, int]]] = {
        char: set() for char in checkpoint.players}
    contested_flags: dict[str, bool] = {char: False for char in checkpoint.players}
    army_spent: dict[str, int] = {char: 0 for char in checkpoint.players}

    prior_snapshot = snapshots[previous_index] if previous_index >= 0 else interval[0]
    for snapshot in interval:
        for char, player in snapshot.players.items():
            prior_cities = prior_snapshot.players[char].cities or 0
            current_cities = player.cities or 0
            if current_cities > prior_cities:
                city_gains[char] += current_cities - prior_cities
                last_new_city_turn[char] = snapshot.turn
            elif current_cities < prior_cities:
                city_losses[char] += prior_cities - current_cities
            if player.army_spent_or_lost is not None:
                army_spent[char] += player.army_spent_or_lost
            lost_turn = snapshot.players[char].city_lost_turn
            if lost_turn is not None and prior_snapshot.turn < lost_turn <= checkpoint.turn:
                contested_flags[char] = True
        _add_contested_city_changes(prior_snapshot, snapshot, contested_coords)
        prior_snapshot = snapshot
    # last_new_city_turn must carry across rounds (last city gain at or before this checkpoint), not reset per round.
    for earlier, later in zip(snapshots[:checkpoint_index], snapshots[1:checkpoint_index + 1]):
        for char, player in later.players.items():
            if char in earlier.players and (player.cities or 0) > (earlier.players[char].cities or 0):
                last_new_city_turn[char] = later.turn
    round_players: dict[str, RoundPlayerStats] = {}
    for char, current in checkpoint.players.items():
        prior = baseline.players[char]
        coords = sorted(contested_coords[char])
        round_players[char] = RoundPlayerStats(
            _difference(current.tiles, prior.tiles),
            _difference(current.score, prior.score),
            army_spent[char],
            city_gains[char],
            city_losses[char],
            last_new_city_turn.get(char),
            ";".join(f"{x},{y}" for x, y in coords),
            contested_flags[char] or bool(coords))
    enemy = _strongest_enemy(checkpoint)
    bot = checkpoint.players.get(checkpoint.bot_player or "")
    enemy_stats = checkpoint.players.get(enemy) if enemy is not None else None
    return RoundStats(
        checkpoint.turn,
        checkpoint.round_number,
        checkpoint,
        round_players,
        _difference(bot.econ, enemy_stats.econ) if bot is not None and enemy_stats is not None else None,
        _difference(bot.score, enemy_stats.score) if bot is not None and enemy_stats is not None else None,
        _difference(bot.tiles, enemy_stats.tiles) if bot is not None and enemy_stats is not None else None,
        _difference(bot.cities, enemy_stats.cities) if bot is not None and enemy_stats is not None else None)


def _add_contested_city_changes(
    previous: TurnSnapshot,
    current: TurnSnapshot,
    contested_coords: dict[str, set[tuple[int, int]]],
) -> None:
    """Record city tiles captured directly between non-neutral players."""
    for coordinate, owner in current.city_owners.items():
        previous_owner = previous.city_owners.get(coordinate, -1)
        if owner < 0 or previous_owner < 0 or owner == previous_owner:
            continue
        old_char = chr(ord("a") + previous_owner)
        new_char = chr(ord("a") + owner)
        if old_char in contested_coords:
            contested_coords[old_char].add(coordinate)
        if new_char in contested_coords:
            contested_coords[new_char].add(coordinate)


def _strongest_enemy(snapshot: TurnSnapshot) -> str | None:
    """Choose the non-teammate player with highest estimated economy."""
    bot_char = snapshot.bot_player
    if bot_char is None or bot_char not in snapshot.players:
        return None
    bot_index = ord(bot_char) - ord("a")
    bot_team = snapshot.team_ids[bot_index] if bot_index < len(snapshot.team_ids) else None
    candidates: list[PlayerTurnStats] = []
    for char, player in snapshot.players.items():
        if char == bot_char:
            continue
        player_index = ord(char) - ord("a")
        player_team = snapshot.team_ids[player_index] if player_index < len(snapshot.team_ids) else None
        if bot_team is not None and player_team == bot_team:
            continue
        candidates.append(player)
    if not candidates:
        return None
    strongest = max(candidates, key=lambda player: (player.econ or 0, player.char))
    return strongest.char


def _write_turn_csv(path: Path, snapshots: list[TurnSnapshot]) -> None:
    """Serialize all per-turn snapshots into a wide CSV."""
    chars = sorted(snapshots[0].players)
    fields = ["turn", "round", "bot_player"]
    for char in chars:
        fields.extend((
            f"{char}_name",
            f"{char}_tiles",
            f"{char}_score",
            f"{char}_standing_army",
            f"{char}_cities",
            f"{char}_econ",
            f"{char}_army_spent_or_lost",
            f"{char}_visible_cities"))
    fields.extend(BOT_FLAG_FIELDS)
    fields.extend(("bot_move", "decision_scope", "decision_hint", "turn_duration", "problems"))
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        for snapshot in snapshots:
            row: dict[str, object] = {
                "turn": snapshot.turn,
                "round": snapshot.round_number,
                "bot_player": snapshot.bot_player or ""}
            for char, player in snapshot.players.items():
                row.update({
                    f"{char}_name": player.name,
                    f"{char}_tiles": player.tiles,
                    f"{char}_score": player.score,
                    f"{char}_standing_army": player.standing_army,
                    f"{char}_cities": player.cities,
                    f"{char}_econ": player.econ,
                    f"{char}_army_spent_or_lost": player.army_spent_or_lost,
                    f"{char}_visible_cities": player.visible_cities})
            for field in BOT_FLAG_FIELDS:
                row[field] = _snapshot_flag(snapshot, field)
            row.update({
                "bot_move": snapshot.bot_move,
                "decision_scope": snapshot.decision_scope,
                "decision_hint": snapshot.decision_hint[:120] if snapshot.decision_hint else None,
                "turn_duration": snapshot.turn_duration,
                "problems": snapshot.problems})
            writer.writerow(row)


def _write_round_csv(path: Path, rows: list[RoundStats]) -> None:
    """Serialize round-end snapshots and calculated changes into a wide CSV."""
    chars = sorted(rows[0].players)
    fields = ["turn", "round"]
    for char in chars:
        fields.extend((
            f"{char}_tiles",
            f"{char}_score",
            f"{char}_cities",
            f"{char}_econ",
            f"{char}_tiles_delta_round",
            f"{char}_score_delta_round",
            f"{char}_army_spent_or_lost_round",
            f"{char}_cities_gained_round",
            f"{char}_cities_lost_round",
            f"{char}_last_new_city_turn",
            f"{char}_contested_cities_round",
            f"{char}_contesting"))
    fields.extend((
        "bot_econ_diff",
        "bot_score_diff",
        "bot_tiles_diff",
        "bot_cities_diff"))
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields)
        writer.writeheader()
        for round_stats in rows:
            row: dict[str, object] = {
                "turn": round_stats.turn,
                "round": round_stats.round_number,
                "bot_econ_diff": round_stats.bot_econ_diff,
                "bot_score_diff": round_stats.bot_score_diff,
                "bot_tiles_diff": round_stats.bot_tiles_diff,
                "bot_cities_diff": round_stats.bot_cities_diff}
            snapshot = round_stats.snapshot
            for char, player in snapshot.players.items():
                round_player = round_stats.players[char]
                row.update({
                    f"{char}_tiles": player.tiles,
                    f"{char}_score": player.score,
                    f"{char}_cities": player.cities,
                    f"{char}_econ": player.econ,
                    f"{char}_tiles_delta_round": round_player.tiles_delta,
                    f"{char}_score_delta_round": round_player.score_delta,
                    f"{char}_army_spent_or_lost_round": round_player.army_spent_or_lost,
                    f"{char}_cities_gained_round": round_player.cities_gained,
                    f"{char}_cities_lost_round": round_player.cities_lost,
                    f"{char}_last_new_city_turn": round_player.last_new_city_turn,
                    f"{char}_contested_cities_round": round_player.contested_cities,
                    f"{char}_contesting": round_player.contesting})
            writer.writerow(row)


def _optional_int(data: dict[str, str], key: str) -> int | None:
    """Return an optional integer txtmap field."""
    value = data.get(key)
    return int(value) if value is not None and value != "" else None


def _difference(current: int | None, previous: int | None) -> int | None:
    """Subtract optional counters when both snapshots have a value."""
    return current - previous if current is not None and previous is not None else None


def _snapshot_flag(snapshot: TurnSnapshot, field: str) -> str | None:
    """Return a known bot-state field without dynamic attribute access."""
    match field:
        case "bot_is_all_in_losing":
            return snapshot.bot_is_all_in_losing
        case "bot_all_in_losing_counter":
            return snapshot.bot_all_in_losing_counter
        case "bot_is_all_in_army_advantage":
            return snapshot.bot_is_all_in_army_advantage
        case "bot_defend_economy":
            return snapshot.bot_defend_economy
        case "bot_is_winning_gather_cyclic":
            return snapshot.bot_is_winning_gather_cyclic
        case "bot_all_in_city_behind":
            return snapshot.bot_all_in_city_behind
        case "bot_is_rapid_capturing_neut_cities":
            return snapshot.bot_is_rapid_capturing_neut_cities
        case "bot_finishing_exploration":
            return snapshot.bot_finishing_exploration
        case "bot_target_player":
            return snapshot.bot_target_player
        case "bot_cur_path":
            return snapshot.bot_cur_path
        case _:
            raise ValueError(f"Unknown bot flag: {field}")


if __name__ == "__main__":
    raise SystemExit(main())
