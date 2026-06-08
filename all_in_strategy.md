# All-In Kill Timing Strategy Plan

## Goal

Create `BotModules/BotKillTiming.py` with `BotKillTiming.find_all_in_option(...)` to detect when the bot is projected to lose the current army-growth round by more than 10%, but can still win by immediately rallying a large army directly into the opponent general.

The immediate target is `Tests/test_BotBehavior.py::BotBehaviorTests.test_should_detect_lost_round_and_detect_all_in_opportunity_and_set_up_all_in_instead`.

## Current test scenario understanding

- The test starts on turn `137`.
- The enemy general is moved to `(18,8)` and assigned `army = 11`.
- The known proof move sequence attacks from our general/path toward the enemy general immediately:
  - `14,19->14,18->16,18->16,10->18,10`
  - nearby friendly support also moves toward/onto the line.
  - final all-in reaches `18,8`.
- The key timing is that the attack path reaches the enemy general at the end of the current army-bonus round.
- The long line of friendly `1`s becomes `2`s after the army bonus, and nearby friendly `2`s become `3`s, giving enough attack power to beat the tracked enemy-general estimate of about `10`.

## Proposed module/API

Add `BotModules/BotKillTiming.py` containing a `BotKillTiming` class with static methods, matching the style of existing modules.

Initial public API:

```python
class BotKillTiming:
    @staticmethod
    def find_all_in_option(bot: EklipZBot) -> Path | None:
        ...
```

Return value:

- Return a `Path` directly to the target player's expected general location when an immediate or pre-round-end all-in is viable.
- Return `None` when no all-in kill is currently viable.

No ad-hoc nested dicts will be used. If the implementation needs to return or internally carry more structured data than a `Path`, add a small `@dataclass(slots=True)` model with typed fields.

## Integration plan

### 1. Add module export

Update `BotModules/__init__.py` to export `BotKillTiming`, so other modules can lazy-import it consistently:

- Add `'BotKillTiming': 'BotKillTiming'` to `_EXPORTS`.

### 2. Call after projected lost-round detection

The actual comparison of our expected expansion plan vs enemy expected expansion plan is explicitly out of scope for this first implementation.

When that future logic determines that we end the round `>10%` behind, it should call:

```python
all_in_path = BotKillTiming.find_all_in_option(bot)
```

Do not add a caller in the first implementation. This is likely to be called from `WinConditionAnalyzer` after the projected expansion comparison exists.

### 3. Force all-in path recalculation

Use existing pathing tools rather than writing a custom pathfinder.

Primary path hook:

- `BotTargeting.get_path_to_target_player(bot, isAllIn=True, cutLength=None, fromTile=bot.general)`

This currently routes through:

- `BotPathingUtils.get_path_to_target(...)`
- `skipEnemyCities=isAllIn`
- `preferNeutral=False`
- `preferEnemy=False`

For the all-in kill path, the current priority behavior may not be enough because we specifically want the path with highest attack value, preferring large friendly tiles and avoiding costly enemy tiles.

The existing lower-level utility `BotPathingUtils.get_path_to_targets(...)` already scores friendly tiles with `negArmySum -= nextTile.army` and enemy/non-friendly tiles with `negArmySum += nextTile.army`, while also respecting `preferEnemy`/`preferNeutral`. I will verify `get_path_to_target(...)` has equivalent knobs before implementation. If it does not, the plan is to extend the existing path utility signature with explicit all-in-friendly-army preference flags, rather than introducing a parallel path algorithm.

### 4. Extra-turn gathering behavior

If:

```python
extra_turns = bot._map.remainingCycleTurns - bot.board_analysis.intergeneral_analysis.inter_general_distance
```

is positive, the method should prefer spending those extra turns gathering onto the selected attack path before launching.

Planned behavior:

- Recalculate the target-player path in all-in mode first.
- Treat path tiles as the rally spine.
- Let existing gather/rally machinery move nearby armies toward that path for `extra_turns` turns.
- After the launch window opens, return/use the direct path to the enemy general.

For the immediate target test, `extra_turns` appears to be `0`, so `find_all_in_option` should return the direct attack path immediately.

## Viability calculation plan

`find_all_in_option` should only return a path if the predicted attacking force can kill the tracked enemy general army.

Inputs:

- `bot.targetPlayerExpectedGeneralLocation`
- `bot.opponent_tracker.get_fog_city_risk_in_turns_by_cycle_behavior(...)` with `cityLimit=1` as the initial tracked enemy-general risk/army estimate source
- `bot._map.remainingCycleTurns`
- `bot.board_analysis.intergeneral_analysis.inter_general_distance`
- Friendly tile ownership/army along and near the selected path

Algorithm sketch:

1. Validate prerequisites:
   - Target player exists.
   - Expected enemy general location exists.
   - Intergeneral analysis exists or can be rebuilt through existing targeting/pathing calls.
   - A path to the expected enemy general can be found.
   - Opponent tracker can provide a general-risk estimate through `get_fog_city_risk_in_turns_by_cycle_behavior(...)` with `cityLimit=1`.

2. Build/rebuild all-in path:
   - Use existing target-player pathing with all-in behavior.
   - Prefer a route that maximizes friendly army contribution and minimizes enemy tile drain.
   - Avoid large enemy blockers where existing path flags support it.

3. Estimate attack value at impact:
   - Walk the path from our launch tile to enemy general.
   - Account for leaving `1` behind on each origin tile as the attack barrels forward.
   - Account for army bonus before impact when impact lands after the round increment.
   - Assume the post-launch attack line is ours and becomes a line of `2`s after the army bonus.
   - Count near-path friendly support tiles currently at `2` that will become `3`s if they can join in time.
   - Subtract enemy/non-friendly tile costs encountered before the general.

4. Compare to enemy general defense:
   - Use tracked enemy-general risk/army estimate from `bot.opponent_tracker.get_fog_city_risk_in_turns_by_cycle_behavior(...)` with `cityLimit=1`.
   - Add any known/predicted growth that applies before impact.
   - Use an exact comparison for now; tune the margin later depending on whether the bot fails too many all-ins or misses too many all-in opportunities.

5. Return:
   - Return the selected direct `Path` if estimated attack value exactly beats the estimated defense threshold selected above.
   - Otherwise return `None`.

## Testing plan before implementation

Per your workflow rules, I will reproduce with a test first if possible.

1. Run the target test before changes using unittest/PyCharm runner from repo root with `bypass_ui=True` because it has `debugMode = not TestBase.GLOBAL_BYPASS_REAL_TIME_TEST and True`.
2. Capture raw output outside the repo under `D:\2019_reformat_Backup\cascade-debug-output\generals-bot` if needed.
3. Add targeted logging with `logbook.info` around:
   - selected all-in path,
   - remaining-cycle timing,
   - estimated attack value,
   - tracked enemy general defense.
4. Implement the smallest path/viability change needed.
5. Re-run the target test and verify it passes or at least progresses to the expected all-in behavior.
6. If a change does not alter/fix behavior after testing, revert that change before trying another approach.

## Implementation order after plan approval

1. Inspect `OpponentTracker.get_fog_city_risk_in_turns_by_cycle_behavior(...)` and related return types to use it correctly with `cityLimit=1`.
2. Inspect `BotPathingUtils.get_path_to_target(...)` to confirm available flags for max-army/friendly-tile path preference.
3. Add `BotModules/BotKillTiming.py` with typed helper dataclasses if needed.
4. Add lazy module export in `BotModules/__init__.py`.
5. Add logging and run focused unit coverage for `find_all_in_option`.
6. Defer wiring into runtime behavior until the `WinConditionAnalyzer` caller is ready.

## Decisions from plan review

1. Do not wire a caller yet; likely future caller is `WinConditionAnalyzer`.
2. Use `bot.opponent_tracker.get_fog_city_risk_in_turns_by_cycle_behavior(...)` with `cityLimit=1` for the initial enemy-general estimate.
3. Friendly fog does not exist; all friendly tiles are always visible. For the second rally calculation, assume we own the attack line of `2`s all the way to the enemy general after army bonus.
4. Use exact viability for now and tune later if needed.
