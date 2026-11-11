"""Fast indexing and turn/scope extraction for bot game logs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


_TIMESTAMP_PATTERN = re.compile(r"^\s*\d{2}:\d{2}\.\d+:\s*(.*)$")
_MOVE_COMPLETE_PATTERN = re.compile(
    r"^\s*(?:\d{2}:\d{2}\.\d+:\s*)?MOVE Complete:\s*(\d+)\s*"
    r"\(\s*([\d.]+)\s+in\b",
    re.IGNORECASE)
_SCOPE_BEGIN_PATTERN = re.compile(
    r"^\s*(?:\d{2}:\d{2}\.\d+:\s*)?Beginning\s+t\d+:\s*"
    r"(.*?)\s+\(([\d.]+)(?:\s+in)?\)\s*$")
_SCOPE_COMPLETE_PATTERN = re.compile(
    r"^\s*(?:\d{2}:\d{2}\.\d+:\s*)?Complete\s+t\d+:\s*"
    r"\(([\d.]+)\)\s*(.*?)\s*$")
_MOVE_COORDINATES_PATTERN = re.compile(
    r"([\w-]+,[\w-]+z?)\s*->\s*([\w-]+,[\w-]+z?)")
_SENDING_MOVE_PATTERN = re.compile(r"\bSending move\b", re.IGNORECASE)
_SEPARATOR_PATTERN = re.compile(r"^\s*(?:vvv-+vvv|\^{3}-+\^{3}|-{8,})\s*$")


@dataclass(slots=True)
class ScopeEvent:
    """A single scope invocation and its source-line range."""

    name: str
    depth: int
    start_line: int
    end_line: int
    duration: float | None


@dataclass(slots=True)
class TurnBlock:
    """One completed move's inclusive source-line range and summary metadata."""

    turn: int
    start_line: int
    end_line: int
    move_text: str | None
    decision_scope: str | None
    decision_hint: str | None
    turn_duration: float | None
    problems: list[str]


class GameLogIndex:
    """Index a game log once, then expose fast turn and scope lookups."""

    __slots__ = (
        "lines",
        "turns",
        "pregame",
        "postgame",
        "source_size_bytes",
        "line_byte_sizes",
        "_scope_cache")

    def __init__(
        self,
        lines: list[str],
        source_size_bytes: int | None = None,
        line_byte_sizes: list[int] | None = None,
    ) -> None:
        """Build turn blocks from already-loaded, right-stripped log lines."""
        self.lines = lines
        self.turns: dict[int, TurnBlock] = {}
        self.pregame = TurnBlock(0, 0, -1, None, None, None, None, [])
        self.postgame = TurnBlock(-1, len(lines), len(lines) - 1, None, None, None, None, [])
        self.source_size_bytes = source_size_bytes or sum(
            len(line.encode("utf-8", errors="replace")) + 1 for line in lines)
        self.line_byte_sizes = line_byte_sizes or [
            len(line.encode("utf-8", errors="replace")) + 1 for line in lines]
        self._scope_cache: dict[int, list[ScopeEvent]] = {}
        self._index_turns()

    @classmethod
    def load(cls, log_path: str) -> GameLogIndex:
        """Read a UTF-8 log once and return its turn index."""
        with open(log_path, "r", encoding="utf-8", errors="replace", newline="") as log_file:
            source_lines = list(log_file)
        lines = [line.rstrip() for line in source_lines]
        line_byte_sizes = [
            len(line.encode("utf-8", errors="replace")) for line in source_lines]
        return cls(lines, Path(log_path).stat().st_size, line_byte_sizes)

    @staticmethod
    def find_log_file(folder: str) -> str:
        """Return the sole `_*.txt` log file in a game folder."""
        files = sorted(Path(folder).glob("_*.txt"))
        if len(files) != 1:
            raise ValueError(f"Expected exactly one _*.txt file in {folder}, found {len(files)}")
        return str(files[0])

    def get_turn_lines(self, turn: int) -> list[str]:
        """Return a copy of the inclusive source lines for a completed turn."""
        block = self.turns[turn]
        return self.lines[block.start_line:block.end_line + 1]

    def get_scopes(self, turn: int) -> list[ScopeEvent]:
        """Parse and cache all scope events belonging to a completed turn."""
        if turn not in self._scope_cache:
            block = self.turns[turn]
            self._scope_cache[turn] = self._parse_scopes(block)
        return self._scope_cache[turn]

    def iter_turns(self, start: int, end: int) -> Iterator[TurnBlock]:
        """Yield indexed turns within an inclusive range in numeric order."""
        for turn in sorted(self.turns):
            if start <= turn <= end:
                yield self.turns[turn]

    def _index_turns(self) -> None:
        """Split the source log at each MOVE Complete record."""
        block_start = 0
        first_completion = -1
        for line_index, line in enumerate(self.lines):
            match = _MOVE_COMPLETE_PATTERN.match(line)
            if match is None:
                continue
            if first_completion < 0:
                first_completion = line_index
            turn = int(match.group(1))
            duration = float(match.group(2))
            block = self._build_turn_block(block_start, line_index, turn, duration)
            self.turns[turn] = block
            block_start = line_index + 1
        self.pregame = self._build_turn_block(
            0,
            first_completion - 1 if first_completion >= 0 else len(self.lines) - 1,
            0,
            None)
        self.postgame = TurnBlock(
            -1,
            block_start,
            len(self.lines) - 1,
            None,
            None,
            None,
            None,
            self._find_problems(block_start, len(self.lines) - 1))

    def _build_turn_block(
        self,
        start_line: int,
        end_line: int,
        turn: int,
        duration: float | None,
    ) -> TurnBlock:
        """Extract move, decision context, and problem flags for one line range."""
        block = TurnBlock(
            turn,
            start_line,
            end_line,
            None,
            None,
            None,
            duration,
            self._find_problems(start_line, end_line))
        sending_line = -1
        for line_index in range(start_line, end_line + 1):
            line = self.lines[line_index]
            if _SENDING_MOVE_PATTERN.search(line):
                sending_line = line_index
                coordinates = _MOVE_COORDINATES_PATTERN.search(line)
                if coordinates is not None:
                    block.move_text = f"{coordinates.group(1)} -> {coordinates.group(2)}"
                break
        if block.move_text is None:
            for line_index in range(start_line, end_line + 1):
                placing = re.search(r"\bPlacing move:\s*(.+?)\s*$", self.lines[line_index])
                if placing is not None:
                    coordinates = _MOVE_COORDINATES_PATTERN.search(placing.group(1))
                    if coordinates is not None:
                        block.move_text = f"{coordinates.group(1)} -> {coordinates.group(2)}"
                    break
        if sending_line < 0:
            return block

        scopes = self._parse_scopes(block)
        for scope in scopes:
            if scope.depth == 0 and scope.start_line < sending_line:
                block.decision_scope = scope.name
        for line_index in range(start_line, sending_line):
            timestamp = _TIMESTAMP_PATTERN.match(self.lines[line_index])
            if timestamp is None:
                continue
            content = timestamp.group(1).strip()
            if (not content or _SEPARATOR_PATTERN.match(content) is not None
                    or content.startswith(("Beginning t", "Complete t", "~~~", "Turn "))):
                continue
            block.decision_hint = content
        return block

    def _parse_scopes(self, block: TurnBlock) -> list[ScopeEvent]:
        """Parse nested Beginning/Complete pairs within a turn block."""
        scopes: list[ScopeEvent] = []
        open_scopes: list[int] = []
        for line_index in range(block.start_line, block.end_line + 1):
            line = self.lines[line_index]
            beginning = _SCOPE_BEGIN_PATTERN.match(line)
            if beginning is not None:
                event = ScopeEvent(
                    beginning.group(1).strip(),
                    len(open_scopes),
                    line_index,
                    -1,
                    None)
                scopes.append(event)
                open_scopes.append(len(scopes) - 1)
                continue
            complete = _SCOPE_COMPLETE_PATTERN.match(line)
            if complete is None:
                continue
            completed_name = complete.group(2).strip()
            for stack_index in range(len(open_scopes) - 1, -1, -1):
                scope_index = open_scopes[stack_index]
                event = scopes[scope_index]
                if _scope_names_match(event.name, completed_name):
                    event.end_line = line_index
                    event.duration = float(complete.group(1))
                    del open_scopes[stack_index:]
                    break
        return scopes

    def _find_problems(self, start_line: int, end_line: int) -> list[str]:
        """Collect deterministic problem markers from an inclusive source range."""
        problems: list[str] = []
        for line_index in range(start_line, end_line + 1):
            line = self.lines[line_index]
            lowered = line.lower()
            if "lag gap" in lowered and "lag gap" not in " ".join(problems).lower():
                problems.append("lag gap")
            if "chess clock: no move returned" in lowered and "no move" not in problems:
                problems.append("no move")
            if "was a bad move from enemy" in lowered and "bad move" not in problems:
                problems.append("bad move")
            if ("error:" in lowered or "traceback (most recent call last)" in lowered):
                problem = "error" if "error:" in lowered else "traceback"
                if problem not in problems:
                    problems.append(problem)
        return problems


# UnitTests.test_LiveGameAnalysis.LiveGameAnalysisTests.test_real_sample_has_635_turns_and_expected_turn_101_context:
# ignore diagnostic suffixes so a completed wrapper does not leave later scopes incorrectly nested.
def _scope_names_match(begin_name: str, complete_name: str) -> bool:
    """Match scopes whose completion adds a runtime summary in parentheses."""
    if begin_name == complete_name:
        return True
    begin_prefix = begin_name.split(" (", 1)[0]
    complete_prefix = complete_name.split(" (", 1)[0]
    return begin_prefix == complete_prefix
