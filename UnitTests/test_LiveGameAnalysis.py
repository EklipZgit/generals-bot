import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from LiveGameAnalysis.GameLogIndex import GameLogIndex
from LiveGameAnalysis.GameLogTool import (
    _decisions_report,
    _loops_report,
    _normalize_decision_label,
    _overview_report,
    _turn_report,
    find_move_loops)
from LiveGameAnalysis.GameStatsGenerator import generate_round_stats, load_snapshots


SAMPLE_GAME_FOLDER = Path(
    r"C:\KeptGeneralsLogs\Human.exe-1v1-2026-11-11_10-47-44---0ES5f2iai")
TEST_OUTPUT_ROOT = Path(r"C:\cascade-debug-output\generals-bot\tmp_tests")


class LiveGameAnalysisTests(unittest.TestCase):
    __slots__ = ("temp_dir", "temp_path")

    def setUp(self) -> None:
        """Prepare an isolated external directory for test inputs."""
        TEST_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=TEST_OUTPUT_ROOT)
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        """Remove temporary test inputs outside the repository."""
        self.temp_dir.cleanup()

    def test_index_splits_turns_and_parses_nested_decision_context(self) -> None:
        """Check turn boundaries, nested scopes, and decision metadata."""
        log_path = self.temp_path / "_synthetic.txt"
        log_path.write_text(
            "\n".join(_synthetic_log_lines((("1,1", "2,1"),))),
            encoding="utf-8")
        index = GameLogIndex.load(str(log_path))

        self.assertEqual(1, len(index.turns))
        self.assertEqual(0, index.pregame.turn)
        self.assertLess(index.pregame.end_line, index.turns[1].end_line)
        self.assertEqual(index.turns[1].end_line + 1, index.postgame.start_line)
        self.assertEqual("1,1 -> 2,1", index.turns[1].move_text)
        self.assertEqual("Root strategy", index.turns[1].decision_scope)
        self.assertEqual(
            "LEAF proactive flank vision defense 1,1 -> 2,1",
            index.turns[1].decision_hint)
        scopes = index.get_scopes(1)
        self.assertEqual(["Root strategy", "Child strategy", "Sending move 1,1 -> 2,1 to server"],
                         [scope.name for scope in scopes])
        self.assertEqual([0, 1, 1], [scope.depth for scope in scopes])
        self.assertEqual(0.01, scopes[0].duration)

    def test_compact_turn_report_drops_timing_noise_and_renders_scopes(self) -> None:
        """Check compact formatting removes timing output and retains scopes."""
        log_path = self.temp_path / "_compact.txt"
        log_path.write_text(
            "\n".join(_synthetic_log_lines((("1,1", "2,1"),))),
            encoding="utf-8")
        index = GameLogIndex.load(str(log_path))
        block = index.turns[1]
        report = _turn_report(index, [block], True)

        self.assertNotIn("MOVE 1 TIMINGS", report)
        self.assertNotIn("timing noise", report)
        self.assertNotIn("--------------------", report)
        self.assertNotIn("^^^~~~~~~~~~~~~~~^^^", report)
        self.assertNotIn("\n\n", report)
        self.assertIn("game_update score summary t1: a=5 (2 tiles)", report)
        self.assertNotIn("map_diff", report)
        self.assertNotIn("WS recv", report)
        self.assertIn("> Root strategy", report)
        self.assertIn("  > Child strategy", report)
        self.assertIn("< Root strategy (0.0100)", report)

    def test_move_loop_detection_finds_reversals_repeats_and_missing_moves(self) -> None:
        """Check reversal, repeat, and missing-move loop diagnostics."""
        moves = (
            ("1,1", "2,1"),
            ("2,1", "1,1"),
            ("1,1", "2,1"),
            ("1,1", "2,1"),
            None,
        )
        log_path = self.temp_path / "_loops.txt"
        log_path.write_text("\n".join(_synthetic_log_lines(moves)), encoding="utf-8")
        index = GameLogIndex.load(str(log_path))

        findings = find_move_loops(list(index.iter_turns(1, 5)))
        kinds = [finding.kind for finding in findings]
        self.assertIn("oscillation", kinds)
        self.assertIn("repeated move", kinds)
        self.assertIn("no move", kinds)

    def test_decisions_normalize_and_group_by_round(self) -> None:
        """Check normalized labels are counted and separated at turn 50."""
        moves = tuple(("1,1", "2,1") for _ in range(51))
        log_path = self.temp_path / "_decisions.txt"
        log_path.write_text("\n".join(_synthetic_log_lines(moves)), encoding="utf-8")
        index = GameLogIndex.load(str(log_path))
        turns = list(index.iter_turns(1, 51))
        turns[0].decision_scope = "capture city 12,7 target2"
        turns[0].decision_hint = "attack 12,7 enemy 4"
        turns[1].decision_scope = "capture city 8,3 target9"
        turns[1].decision_hint = "attack 8,3 enemy 5"

        self.assertEqual(
            "capture city # target# | attack # enemy",
            _normalize_decision_label(
                turns[0].decision_scope or "",
                turns[0].decision_hint or ""))
        report = _decisions_report(turns)

        self.assertIn("=== round 0 (turns 1-49) ===", report)
        self.assertIn("47  Root strategy | LEAF proactive flank", report)
        self.assertIn("2  capture city # target# | attack # enemy", report)
        self.assertIn("=== round 1 (turns 50-51) ===", report)
        self.assertIn("2  Root strategy | LEAF proactive flank", report)

    def test_overview_and_moves_loops_include_scores_and_postgame(self) -> None:
        """Check overview score headers and postgame outcome lines."""
        log_path = self.temp_path / "_postgame.txt"
        log_path.write_text(
            "\n".join(_synthetic_log_lines((("1,1", "2,1"),))),
            encoding="utf-8")
        index = GameLogIndex.load(str(log_path))
        turns = list(index.iter_turns(1, 1))

        overview = _overview_report(index, turns, [])
        loops = _loops_report(turns, index)

        self.assertTrue(overview.startswith("t1 [p0 5/2 p1 7/3] move="))
        self.assertTrue(overview.endswith("POSTGAME:\n  postgame bot gave up :("))
        self.assertTrue(loops.endswith("POSTGAME:\n  postgame bot gave up :("))

    def test_tick_fifty_generation_and_contested_city_are_in_round_stats(self) -> None:
        """Check tick-50 army income and contested city ownership changes."""
        self._write_txtmap(49, 10, 10, "bC1", 1, 2)
        self._write_txtmap(50, 15, 10, "aC1", 2, 1, b_city_lost_turn=50)

        snapshots = load_snapshots(str(self.temp_path))
        self.assertEqual(-2, snapshots[1].players["a"].army_spent_or_lost)
        round_stats = generate_round_stats(snapshots)

        self.assertEqual(1, len(round_stats))
        self.assertEqual("1,0", round_stats[0].players["a"].contested_cities)
        self.assertEqual("1,0", round_stats[0].players["b"].contested_cities)
        self.assertTrue(round_stats[0].players["a"].contesting)
        self.assertTrue(round_stats[0].players["b"].contesting)

    @unittest.skipUnless(SAMPLE_GAME_FOLDER.is_dir(), "sample game logs are unavailable")
    def test_real_sample_has_635_turns_and_expected_turn_101_context(self) -> None:
        """Check indexed count and known strategic context from the sample log."""
        index = GameLogIndex.load(GameLogIndex.find_log_file(str(SAMPLE_GAME_FOLDER)))

        self.assertEqual(635, len(index.turns))
        self.assertEqual(
            "Flank defense / Vision expansion low pri",
            index.turns[101].decision_scope)
        self.assertEqual(
            "LEAF proactive flank vision defense 6,6 -> 7,6",
            index.turns[101].decision_hint)

    def _write_txtmap(
        self,
        turn: int,
        a_score: int,
        b_score: int,
        city_tile: str,
        a_cities: int,
        b_cities: int,
        b_city_lost_turn: int = 0,
    ) -> None:
        """Write a tiny two-player map snapshot used by statistics tests."""
        contents = "\n".join((
            "|  |  |",
            f"aG5{city_tile}bG5",
            "a1    b1 ",
            "|  |  |",
            f"turn={turn}",
            "player_index=0",
            "mode=1v1",
            "aUsername=bot",
            "aTiles=2",
            f"aScore={a_score}",
            "aStandingArmy=5",
            f"aCityCount={a_cities}",
            "aCityLostTurn=0",
            "bUsername=enemy",
            "bTiles=2",
            f"bScore={b_score}",
            "bStandingArmy=5",
            f"bCityCount={b_cities}",
            f"bCityLostTurn={b_city_lost_turn}",
            "bot_is_all_in_losing=False",
            "bot_defend_economy=False"))
        (self.temp_path / f"{turn}.txtmap").write_text(contents, encoding="utf-8")


def _synthetic_log_lines(
    moves: Sequence[tuple[str, str] | None],
) -> list[str]:
    """Construct turn blocks with nested scopes, decisions, and timing noise."""
    lines = ["startup pregame"]
    for turn, move in enumerate(moves, 1):
        lines.extend((
            "00:00.0001: vvv--------------vvv",
            f"00:00.0002: Beginning t{turn}: Root strategy (0.001 in)",
            f"00:00.0003: Beginning t{turn}: Child strategy (0.002 in)",
            f"00:00.0004: Complete t{turn}: (0.003) Child strategy"))
        lines.extend((
            "00:00.0004: --------------------",
            "^^^~~~~~~~~~~~~~~^^^",
            ""))
        lines.append(
            "00:00.0005: WS recv: \"42[\\\"game_update\\\","
            "{\\\"scores\\\":[{\\\"total\\\":5,\\\"tiles\\\":2,\\\"i\\\":0},"
            "{\\\"total\\\":7,\\\"tiles\\\":3,\\\"i\\\":1}],"
            f"\\\"turn\\\":{turn},\\\"map_diff\\\":[1]}}]\"")
        if move is not None:
            source, destination = move
            lines.extend((
                f"00:00.0005: LEAF proactive flank vision defense {source} -> {destination}",
                f"00:00.0006: Beginning t{turn}: Sending move {source} -> {destination} to server (0.004 in)",
                f"00:00.0007: Placing move: {source} to {destination}",
                f"00:00.0008: Complete t{turn}: (0.005) Sending move {source} -> {destination} to server"))
        else:
            lines.append("00:00.0005: Chess clock: no move returned")
        lines.extend((
            f"00:00.0009: Complete t{turn}: (0.010) Root strategy",
            f"00:00.0010: MOVE {turn} TIMINGS:",
            "    timing noise",
            f"00:00.0011: MOVE Complete: {turn} (0.050 in, at game 0.050)"))
    lines.append("postgame bot gave up :(")
    return lines


if __name__ == "__main__":
    unittest.main()
