"""Command-line analysis tools for live generals.io bot logs."""

from __future__ import annotations

import argparse
import csv
from io import StringIO
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import logbook

from LiveGameAnalysis.GameLogIndex import GameLogIndex, ScopeEvent, TurnBlock


DEFAULT_OUTPUT_ROOT = Path(r"C:\cascade-debug-output\generals-bot\game_analysis")
DEFAULT_OVERVIEW_PATTERNS = (
    r"WCA_PROJECTED_ROUND_LOSS",
    r"get_danger_paths:",
    r"LKP=",
    r"NOT DEFENDING ECONOMY|DEFENDING ECONOMY",
    r"EH: Tile captured! .*(?:oldOwner [0-9]|C)",
    r"\ball.?in\b",
    r"INTERCEPT",
    r"bot gave up",
    r"\bkill(?:ed|ing|s)?\b",
    r"CITY_ROUND_OPPORTUNITY_COST",
    r"ERROR|Traceback",
    r"LAG GAP",
)
_TIMESTAMP_PREFIX = re.compile(r"^\s*\d{2}:\d{2}\.\d+:\s*")
_TIMINGS_LINE = re.compile(r"\bMOVE\s+\d+\s+TIMINGS:")
_MOVE_PAIR = re.compile(r"([\w-]+,[\w-]+z?)\s*->\s*([\w-]+,[\w-]+z?)")
_SEPARATOR_LINE = re.compile(
    r"^\s*(?:v{3}[-~]+v{3}|\^{3}[-~]+\^{3}|[-~]{8,})\s*$",
    re.IGNORECASE)
_WS_LINE = re.compile(r"\bWS\s+(?:recv|Sending)\b", re.IGNORECASE)
_GAME_UPDATE = re.compile(r"game_update", re.IGNORECASE)
_SCORE_WORD = re.compile(r"\bscores?\b", re.IGNORECASE)
_SCORES_ARRAY = re.compile(r'\\?"scores\\?"\s*:\s*\[(.*?)\]')
_SCORE_OBJECT = re.compile(r"\{([^{}]*)\}")
_TOTAL_FIELD = re.compile(r'\\?"total\\?"\s*:\s*(\d+)')
_TILES_FIELD = re.compile(r'\\?"tiles\\?"\s*:\s*(\d+)')
_PLAYER_INDEX_FIELD = re.compile(r'\\?"i\\?"\s*:\s*(\d+)')
_TURN_FIELD = re.compile(r'\\?"turn\\?"\s*:\s*(\d+)')
_COORDINATE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])-?\d+\s*,\s*-?\d+z?(?![A-Za-z0-9_])")
_DIGIT_RUN = re.compile(r"\d+")
_POSTGAME_PATTERN = re.compile(
    r"won\?|gave up|surrender|IN TERMINATE",
    re.IGNORECASE)


@dataclass(slots=True)
class MoveLoopFinding:
    """One deterministic move-loop diagnostic."""

    kind: str
    first_turn: int
    last_turn: int
    move_text: str


@dataclass(slots=True)
class NoiseTemplate:
    """Accumulated size and frequency for a normalized log template."""

    template: str
    byte_count: int
    count: int


@dataclass(slots=True)
class ScopeAggregate:
    """Aggregate duration information for one scope name."""

    name: str
    turn_count: int
    total_duration: float
    max_duration: float


@dataclass(slots=True)
class GameUpdateScore:
    """One player's score fields from a game_update transport message."""

    player_index: int
    total: int
    tiles: int


@dataclass(slots=True)
class DecisionRoundAggregate:
    """One round's selected turn span and normalized decision counts."""

    round_number: int
    first_turn: int
    last_turn: int
    label_counts: dict[str, int]


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI parser and all command-specific options."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    turn_parser = _add_common_arguments(commands, "turn", "Dump raw or compact turn logs.")
    turn_parser.add_argument("--compact", action="store_true")
    scope_parser = _add_common_arguments(commands, "scope", "Extract matching scope occurrences.")
    scope_parser.add_argument("--scope", required=True)
    grep_parser = _add_common_arguments(commands, "grep", "Search log lines with optional context.")
    grep_parser.add_argument("--pattern", required=True)
    grep_parser.add_argument("--context", type=int, default=0)
    grep_parser.add_argument("--max-per-turn", type=int)
    grep_parser.add_argument("--ignore-case", action="store_true")
    moves_parser = _add_common_arguments(commands, "moves", "Export the move timeline and loop findings.")
    scopes_parser = _add_common_arguments(commands, "scopes", "Aggregate scope durations.")
    noise_parser = _add_common_arguments(commands, "noise", "Rank normalized log-line templates.")
    noise_parser.add_argument("--top", type=int, default=60)
    overview_parser = _add_common_arguments(commands, "overview", "Summarize decision context and key events.")
    overview_parser.add_argument("--patterns", nargs="*")
    _add_common_arguments(commands, "decisions", "Group normalized decision labels by round.")
    return parser


def _add_common_arguments(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
) -> argparse.ArgumentParser:
    """Add shared game-folder and inclusive-range options to one command."""
    command_parser = commands.add_parser(name, help=help_text)
    command_parser.add_argument("folder")
    command_parser.add_argument("--from", dest="from_turn", type=int)
    command_parser.add_argument("--to", dest="to_turn", type=int)
    command_parser.add_argument("--out", type=Path)
    return command_parser


def find_move_loops(turns: list[TurnBlock]) -> list[MoveLoopFinding]:
    """Find move reversals, repeated move pairs, and turns without moves."""
    findings: list[MoveLoopFinding] = []
    records: list[tuple[TurnBlock, str, str]] = []
    for turn in turns:
        if turn.move_text is None:
            findings.append(MoveLoopFinding("no move", turn.turn, turn.turn, ""))
            continue
        match = _MOVE_PAIR.search(turn.move_text)
        if match is not None:
            records.append((turn, match.group(1), match.group(2)))

    emitted: set[tuple[str, int, int, str]] = set()
    for index, (first, source, destination) in enumerate(records):
        for later, later_source, later_destination in records[index + 1:]:
            if later.turn - first.turn > 4:
                break
            if source == later_destination and destination == later_source:
                key = ("oscillation", first.turn, later.turn, f"{source} -> {destination}")
                if key not in emitted:
                    findings.append(MoveLoopFinding(*key))
                    emitted.add(key)

    for end_index, (last, source, destination) in enumerate(records):
        window = [
            record for record in records[:end_index + 1]
            if last.turn - record[0].turn < 10
            and record[1] == source
            and record[2] == destination
        ]
        if len(window) >= 3:
            first_turn = window[0][0].turn
            key = ("repeated move", first_turn, last.turn, f"{source} -> {destination}")
            if key not in emitted:
                findings.append(MoveLoopFinding(*key))
                emitted.add(key)
    return sorted(findings, key=lambda finding: (finding.first_turn, finding.kind, finding.last_turn))


def main(argv: Sequence[str] | None = None) -> int:
    """Run one requested log-analysis subcommand and write its report."""
    logbook.StreamHandler(sys.stdout, level=logbook.INFO).push_application()
    arguments = create_parser().parse_args(argv)
    index = GameLogIndex.load(GameLogIndex.find_log_file(arguments.folder))
    selected_turns = list(index.turns.values())
    if not selected_turns:
        raise ValueError(f"No completed turns found in {arguments.folder}")
    minimum_turn = min(index.turns)
    maximum_turn = max(index.turns)
    start_turn = arguments.from_turn if arguments.from_turn is not None else minimum_turn
    end_turn = arguments.to_turn if arguments.to_turn is not None else maximum_turn
    turns = list(index.iter_turns(start_turn, end_turn))
    output_path = _resolve_output_path(arguments, start_turn, end_turn)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if arguments.command == "turn":
        report = _turn_report(index, turns, arguments.compact)
    elif arguments.command == "scope":
        report = _scope_report(index, turns, arguments.scope.split("|"))
    elif arguments.command == "grep":
        report = _grep_report(index, turns, arguments.pattern, arguments.context,
                              arguments.max_per_turn, arguments.ignore_case)
    elif arguments.command == "moves":
        report = _moves_report(turns)
        _write_report(output_path, report)
        loops_path = output_path.with_name(
            f"moves_loops_{start_turn}_{end_turn}.txt")
        _write_report(loops_path, _loops_report(turns, index))
        logbook.info("Wrote {} lines to {}; loop findings: {}",
                     len(report.splitlines()), output_path, loops_path)
        return 0
    elif arguments.command == "scopes":
        report = _scopes_report(index, turns)
    elif arguments.command == "noise":
        report = _noise_report(index, turns, arguments.top, start_turn, end_turn,
                               start_turn == minimum_turn and end_turn == maximum_turn)
    elif arguments.command == "decisions":
        report = _decisions_report(turns)
    else:
        patterns = arguments.patterns or list(DEFAULT_OVERVIEW_PATTERNS)
        report = _overview_report(index, turns, patterns)

    _write_report(output_path, report)
    logbook.info("Wrote {} lines to {}", len(report.splitlines()), output_path)
    if arguments.command == "turn" and arguments.compact:
        raw_line_count = sum(
            turn.end_line - turn.start_line + 1 for turn in turns)
        compact_line_count = len(report.splitlines())
        reduction = (
            100.0 * (raw_line_count - compact_line_count) / raw_line_count
            if raw_line_count else 0.0)
        logbook.info(
            "Compact reduction: {} to {} lines ({:.1f}% fewer)",
            raw_line_count,
            compact_line_count,
            reduction)
    return 0


def _resolve_output_path(arguments: argparse.Namespace, start: int, end: int) -> Path:
    """Resolve explicit or standard output paths for a command."""
    explicit_path = arguments.out
    if explicit_path is not None:
        return explicit_path
    folder_name = Path(arguments.folder).name
    suffix = ".csv" if arguments.command == "moves" else ".txt"
    extra = "_compact" if arguments.command == "turn" and arguments.compact else ""
    return DEFAULT_OUTPUT_ROOT / folder_name / (
        f"{arguments.command}_{start}_{end}{extra}{suffix}")


def _write_report(path: Path, report: str) -> None:
    """Write a report using UTF-8 and normalized newline handling."""
    with path.open("w", encoding="utf-8", newline="") as output_file:
        output_file.write(report)
        if report and not report.endswith("\n"):
            output_file.write("\n")


def _turn_report(index: GameLogIndex, turns: list[TurnBlock], compact: bool) -> str:
    """Render the selected turns in raw or compact form."""
    output: list[str] = []
    for turn in turns:
        lines = index.get_turn_lines(turn.turn)
        if compact:
            output.extend(_compact_lines(index, turn, lines))
        else:
            output.extend(lines)
    return "\n".join(output)


def _scope_report(
    index: GameLogIndex,
    turns: list[TurnBlock],
    substrings: list[str],
) -> str:
    """Render each matching scope occurrence and its enclosed source lines."""
    output: list[str] = []
    for turn in turns:
        turn_lines = index.get_turn_lines(turn.turn)
        for scope in index.get_scopes(turn.turn):
            if not any(part in scope.name for part in substrings):
                continue
            output.append(
                f"=== t{turn.turn} {scope.name} ({_duration_text(scope.duration)}) ===")
            local_start = scope.start_line - turn.start_line
            local_end = scope.end_line - turn.start_line if scope.end_line >= 0 else len(turn_lines) - 1
            scope_turn = TurnBlock(
                turn.turn,
                scope.start_line,
                scope.end_line,
                None,
                None,
                None,
                turn.turn_duration,
                [])
            output.extend(_compact_lines(index, scope_turn, turn_lines[local_start:local_end + 1]))
    return "\n".join(output)


def _grep_report(
    index: GameLogIndex,
    turns: list[TurnBlock],
    pattern: str,
    context: int,
    max_per_turn: int | None,
    ignore_case: bool,
) -> str:
    """Search selected lines and include up to K surrounding lines per match."""
    flags = re.IGNORECASE if ignore_case else 0
    matcher = re.compile(pattern, flags)
    output: list[str] = []
    for turn in turns:
        lines = index.get_turn_lines(turn.turn)
        matching_indexes = [
            line_index for line_index, line in enumerate(lines) if matcher.search(line)
        ]
        if max_per_turn is not None:
            matching_indexes = matching_indexes[:max_per_turn]
        included: set[int] = set()
        for line_index in matching_indexes:
            included.update(range(max(0, line_index - context),
                                  min(len(lines), line_index + context + 1)))
        previous_index = -2
        for line_index in sorted(included):
            if line_index > previous_index + 1:
                output.append(f"--- t{turn.turn} ---")
            output.append(f"t{turn.turn}: {lines[line_index]}")
            previous_index = line_index
    return "\n".join(output)


def _moves_report(turns: list[TurnBlock]) -> str:
    """Serialize the move timeline as a CSV report."""
    rows = [
        "turn,move,decision_scope,decision_hint,duration,problems"
    ]
    for turn in turns:
        rows.append(_csv_row((
            turn.turn,
            turn.move_text or "",
            turn.decision_scope or "",
            _truncate(turn.decision_hint or "", 160),
            _duration_text(turn.turn_duration),
            ";".join(turn.problems))))
    return "\n".join(rows)


def _loops_report(turns: list[TurnBlock], index: GameLogIndex) -> str:
    """Render move-loop findings followed by matching postgame status lines."""
    findings = find_move_loops(turns)
    if not findings:
        report_lines = ["No move loops or missing moves found."]
    else:
        report_lines = [
            f"{finding.kind}: t{finding.first_turn}-t{finding.last_turn} "
            f"{finding.move_text}".rstrip()
            for finding in findings
        ]
    report_lines.extend(_postgame_section(_postgame_lines(index)))
    return "\n".join(report_lines)


def _decisions_report(turns: list[TurnBlock]) -> str:
    """Count normalized decision labels for each round in the selected range."""
    rounds: dict[int, DecisionRoundAggregate] = {}
    for turn in turns:
        round_number = turn.turn // 50
        aggregate = rounds.get(round_number)
        if aggregate is None:
            aggregate = DecisionRoundAggregate(
                round_number,
                turn.turn,
                turn.turn,
                {})
            rounds[round_number] = aggregate
        aggregate.first_turn = min(aggregate.first_turn, turn.turn)
        aggregate.last_turn = max(aggregate.last_turn, turn.turn)
        label = _normalize_decision_label(
            turn.decision_scope or "None",
            turn.decision_hint or "")
        aggregate.label_counts[label] = aggregate.label_counts.get(label, 0) + 1

    output: list[str] = []
    for round_number in sorted(rounds):
        aggregate = rounds[round_number]
        output.append(
            f"=== round {round_number} "
            f"(turns {aggregate.first_turn}-{aggregate.last_turn}) ===")
        ranked_labels = sorted(
            aggregate.label_counts.items(),
            key=lambda entry: (-entry[1], entry[0]))
        output.extend(
            f"{count}  {label}" for label, count in ranked_labels[:10])
    return "\n".join(output)


def _normalize_decision_label(decision_scope: str, decision_hint: str) -> str:
    """Normalize scope digits and append the first three normalized hint words."""
    normalized_scope = _normalize_decision_text(decision_scope)[:60]
    first_words = " ".join(decision_hint.split()[:3])
    normalized_hint = _normalize_decision_text(first_words)
    return f"{normalized_scope} | {normalized_hint}"


def _normalize_decision_text(text: str) -> str:
    """Replace coordinate-like tokens and remaining digit runs with `#`."""
    without_coordinates = _COORDINATE_TOKEN.sub("#", text)
    return _DIGIT_RUN.sub("#", without_coordinates)


def _postgame_lines(index: GameLogIndex) -> list[str]:
    """Return timestamp-stripped postgame lines containing outcome markers."""
    postgame = index.postgame
    return [
        _strip_timestamp(index.lines[line_index]).strip()
        for line_index in range(postgame.start_line, postgame.end_line + 1)
        if _POSTGAME_PATTERN.search(index.lines[line_index])
    ]


def _postgame_section(lines: list[str]) -> list[str]:
    """Format matching outcome lines under a consistent POSTGAME heading."""
    section = ["POSTGAME:"]
    if lines:
        section.extend(f"  {line}" for line in lines)
    else:
        section.append("  (no matching lines)")
    return section


def _scopes_report(index: GameLogIndex, turns: list[TurnBlock]) -> str:
    """Aggregate occurrence counts and durations by scope name."""
    aggregates: dict[str, ScopeAggregate] = {}
    for turn in turns:
        names_this_turn: set[str] = set()
        for scope in index.get_scopes(turn.turn):
            aggregate = aggregates.get(scope.name)
            duration = scope.duration or 0.0
            if aggregate is None:
                aggregate = ScopeAggregate(scope.name, 0, 0.0, 0.0)
                aggregates[scope.name] = aggregate
            aggregate.total_duration += duration
            aggregate.max_duration = max(aggregate.max_duration, duration)
            names_this_turn.add(scope.name)
        for name in names_this_turn:
            aggregates[name].turn_count += 1
    rows = ["scope,turn_count,total_duration,max_duration"]
    for aggregate in sorted(
        aggregates.values(),
        key=lambda item: (-item.total_duration, item.name)):
        rows.append(_csv_row((
            aggregate.name,
            aggregate.turn_count,
            f"{aggregate.total_duration:.6f}",
            f"{aggregate.max_duration:.6f}")))
    return "\n".join(rows)


def _noise_report(
    index: GameLogIndex,
    turns: list[TurnBlock],
    top: int,
    start: int,
    end: int,
    whole_log: bool,
) -> str:
    """Rank normalized templates by aggregate byte size and occurrence count."""
    if whole_log:
        source_lines = list(enumerate(index.lines))
        denominator = index.source_size_bytes
    else:
        source_lines = [
            (line_index, index.lines[line_index])
            for turn in turns
            for line_index in range(turn.start_line, turn.end_line + 1)
        ]
        denominator = sum(
            index.line_byte_sizes[line_index] for line_index, _ in source_lines)
    templates: dict[str, NoiseTemplate] = {}
    timing_bytes = 0
    timing_blocks = 0
    in_timings = False
    for line_index, line in source_lines:
        if _TIMINGS_LINE.search(line):
            in_timings = True
            timing_blocks += 1
        if in_timings:
            timing_bytes += index.line_byte_sizes[line_index]
            if re.search(r"\bMOVE Complete:", line):
                in_timings = False
            continue
        normalized = _normalize_template(line)
        template = templates.get(normalized)
        if template is None:
            template = NoiseTemplate(normalized, 0, 0)
            templates[normalized] = template
        template.byte_count += index.line_byte_sizes[line_index]
        template.count += 1
    templates["[TIMINGS blocks]"] = NoiseTemplate(
        "[TIMINGS blocks]", timing_bytes, timing_blocks)
    output = [
        f"range={start}-{end} bytes={denominator}",
        "TOP BY BYTES: rank,bytes,percent,count,template",
    ]
    by_bytes = sorted(
        templates.values(),
        key=lambda item: (-item.byte_count, item.template))
    output.extend(_noise_row(rank, item, denominator)
                  for rank, item in enumerate(by_bytes[:top], 1))
    output.append("TOP BY COUNT: rank,count,bytes,percent,template")
    by_count = sorted(
        templates.values(),
        key=lambda item: (-item.count, -item.byte_count, item.template))
    output.extend(_noise_count_row(rank, item, denominator)
                  for rank, item in enumerate(by_count[:top], 1))
    return "\n".join(output)


def _overview_report(
    index: GameLogIndex,
    turns: list[TurnBlock],
    patterns: list[str],
) -> str:
    """Render scores, decision context, capped events, and postgame status."""
    matchers = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    output: list[str] = []
    for turn in turns:
        score_summary = _game_update_score_header(index, turn)
        score_text = f" {score_summary}" if score_summary else ""
        output.append(
            f"t{turn.turn}{score_text} move={turn.move_text or 'None'} "
            f"via={turn.decision_scope or 'None'} | {turn.decision_hint or ''}")
        matches = 0
        for line in index.get_turn_lines(turn.turn):
            if any(matcher.search(line) for matcher in matchers):
                output.append(f"  {_truncate(_strip_timestamp(line), 220)}")
                matches += 1
                if matches >= 12:
                    break
    output.extend(_postgame_section(_postgame_lines(index)))
    return "\n".join(output)


def _compact_lines(
    index: GameLogIndex,
    block: TurnBlock,
    lines: list[str],
) -> list[str]:
    """Remove high-volume timing and transport noise and indent scopes."""
    events = index.get_scopes(block.turn) if block.turn in index.turns else []
    begin_events = {event.start_line: event for event in events}
    end_events = {event.end_line: event for event in events if event.end_line >= 0}
    output: list[str] = []
    in_timings = False
    for local_index, line in enumerate(lines):
        absolute_index = block.start_line + local_index
        if _TIMINGS_LINE.search(line):
            in_timings = True
        if in_timings:
            if re.search(r"\bMOVE Complete:", line):
                in_timings = False
            continue
        timestamp_stripped = _strip_timestamp(line)
        if (not timestamp_stripped.strip()
                or _SEPARATOR_LINE.match(timestamp_stripped)):
            continue
        if _WS_LINE.search(line):
            if _GAME_UPDATE.search(line) and _SCORE_WORD.search(line):
                output.append(_game_update_score_summary(line))
            continue
        begin_event = begin_events.get(absolute_index)
        if begin_event is not None:
            output.append(
                f"{' ' * (2 * begin_event.depth)}> {begin_event.name}")
            continue
        end_event = end_events.get(absolute_index)
        if end_event is not None:
            output.append(
                f"{' ' * (2 * end_event.depth)}< {end_event.name} "
                f"({_duration_text(end_event.duration)})")
            continue
        output.append(timestamp_stripped)
    return output


def _normalize_template(line: str) -> str:
    """Normalize timestamp, numeric runs, and whitespace for noise ranking."""
    normalized = _strip_timestamp(line)
    normalized = re.sub(r"\d+", "#", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:120]


def _game_update_score_summary(line: str) -> str:
    """Extract only turn, player total, and tile counts from game_update WS text."""
    scores = _parse_game_update_scores(line)
    turn_match = _TURN_FIELD.search(line)
    turn_text = f"t{turn_match.group(1)}" if turn_match is not None else "turn unknown"
    if not scores:
        return f"game_update score summary {turn_text}: unavailable"
    score_text = "; ".join(
        f"{chr(ord('a') + score.player_index)}={score.total} "
        f"({score.tiles} tiles)"
        for score in scores)
    return f"game_update score summary {turn_text}: {score_text}"


def _parse_game_update_scores(line: str) -> list[GameUpdateScore]:
    """Parse player score and tile fields from one game_update WebSocket line."""
    score_array = _SCORES_ARRAY.search(line)
    scores: list[GameUpdateScore] = []
    if score_array is None:
        return scores
    for object_match in _SCORE_OBJECT.finditer(score_array.group(1)):
        total = _TOTAL_FIELD.search(object_match.group(1))
        tiles = _TILES_FIELD.search(object_match.group(1))
        player_index = _PLAYER_INDEX_FIELD.search(object_match.group(1))
        if total is not None and tiles is not None and player_index is not None:
            scores.append(GameUpdateScore(
                int(player_index.group(1)),
                int(total.group(1)),
                int(tiles.group(1))))
    return scores


def _game_update_score_header(index: GameLogIndex, turn: TurnBlock) -> str:
    """Format game_update scores as `[pN total/tiles]` for an overview header."""
    for line in index.get_turn_lines(turn.turn):
        if not _WS_LINE.search(line):
            continue
        if not _GAME_UPDATE.search(line) or not _SCORE_WORD.search(line):
            continue
        scores = _parse_game_update_scores(line)
        if scores:
            formatted_scores = " ".join(
                f"p{score.player_index} {score.total}/{score.tiles}"
                for score in sorted(scores, key=lambda item: item.player_index))
            return f"[{formatted_scores}]"
    return ""


def _strip_timestamp(line: str) -> str:
    """Remove a leading MM:SS.ffff timestamp when one is present."""
    return _TIMESTAMP_PREFIX.sub("", line, count=1)


def _duration_text(duration: float | None) -> str:
    """Format optional seconds as compact text."""
    return "" if duration is None else f"{duration:.4f}"


def _truncate(text: str, limit: int) -> str:
    """Trim a string to a maximum length without adding extra markers."""
    return text[:limit]


def _csv_row(values: tuple[object, ...]) -> str:
    """Serialize a row with the CSV quoting rules."""
    buffer = StringIO()
    csv.writer(buffer, lineterminator="").writerow(values)
    return buffer.getvalue()


def _noise_row(rank: int, template: NoiseTemplate, denominator: int) -> str:
    """Format one byte-ranked noise template."""
    percentage = 100.0 * template.byte_count / denominator if denominator else 0.0
    return _csv_row((
        rank,
        template.byte_count,
        f"{percentage:.3f}",
        template.count,
        template.template))


def _noise_count_row(rank: int, template: NoiseTemplate, denominator: int) -> str:
    """Format one frequency-ranked noise template."""
    percentage = 100.0 * template.byte_count / denominator if denominator else 0.0
    return _csv_row((
        rank,
        template.count,
        template.byte_count,
        f"{percentage:.3f}",
        template.template))


if __name__ == "__main__":
    raise SystemExit(main())
