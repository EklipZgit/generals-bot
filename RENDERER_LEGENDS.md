# Renderer Legends

This document describes all the visual elements rendered by the viewer, their colors, and where in the codebase they are defined and used.

## Threat Blocking Tile Border Gradients

Border gradients are colored lines drawn along tile edges to indicate threat blocking tiles. These are rendered via `ViewInfo.border_gradients` and drawn by `viewer._draw_border_gradients()`.

| Color | RGB Value | Meaning | Code Location |
|-------|-----------|---------|---------------|
| Dark Gray | `(80, 80, 80)` | Main defense blocks - tiles that block movement from defensive tiles to prevent enemy threats | `BotDefense.py:set_defensive_blocks_against()` - lines 2700, 2733 |
| Dark Orange | `(180, 100, 20)` | Intercept split-hint blocks - tiles generated for intercepting threats using split hinting | `BotDefense.py:build_intercept_plans()` - line 590 |
| Dark Orange | `(180, 100, 20)` | Contested-city blocks - owned contested cities that must not move to defend | `BotDefense.py:build_intercept_plans()` - line 619 |
| Dark Purple | `(90, 0, 90)` | Flow expansion custom blocks - main defense blocks + general movement tweak passed to flow expansion | `BotExpansionOps.py:_get_expansion_options_v2()` - line 650 |

### Implementation Details
- **Data structure**: `ViewInfo.BorderGradient` dataclass in `ViewInfo.py` (lines 44-57)
- **Add method**: `ViewInfo.add_border_gradient(tileA, tileB, colorA, colorB=None)` in `ViewInfo.py` (lines 339-355)
- **Render method**: `viewer._draw_border_gradients()` and `viewer._draw_border_gradient()` in `base/viewer.py` (lines 1758-1822)
- **Line width**: 5px (configurable in `_draw_border_gradients()`)
- **Render order**: After tile colors and division borders, before paths and other overlays

---

## TargetStyle Colors

The `TargetStyle` enum in `ViewInfo.py` defines standard colors used for targeted tiles and other visual elements.

| TargetStyle | RGB Value | Common Uses |
|-------------|-----------|-------------|
| RED | `(255, 0, 0)` | Dropped fog tiles, unconnectable tiles, enemy fog attack tiles |
| GREEN | `(0, 200, 0)` | Decremented fog tiles, gathing tiles in flow expansion |
| BLUE | `(50, 50, 255)` | City pre-defense gather targets, incomplete source tiles in flow expansion |
| GOLD | `(185, 145, 0)` | Target player gather path |
| PURPLE | `(128, 0, 128)` | Defend cities, fake-connected flow expansion islands, incomplete target tiles |
| TEAL | `(0, 128, 128)` | Root tiles in gather capture plans |
| ORANGE | `(220, 150, 40)` | Defensive choke tiles, incomplete target tiles in flow expansion |
| WHITE | `(200, 200, 200)` | Defensive spanning tree |
| YELLOW | `(255, 255, 0)` | Alternate enemy general positions |
| GRAY | `(160, 160, 160)` | Duplicate flow option tiles, all-in targets |

**Definition**: `ViewInfo.py` lines 31-41
**Color mapping**: `ViewInfo.get_color_from_target_style()` lines 133-154

---

## Targeted Tile Legends

Targeted tiles are rendered with colored circles around them. Many use `add_targeted_tiles_with_legend()` which automatically adds a legend entry to the info panel.

| Legend | Color | Code Location |
|--------|-------|---------------|
| DefenseTree | WHITE | `bot_ek0x45.py` line 1239 |
| Unconnectable to defense span | PURPLE | `BotDefense.py` line 1871 |
| Defensive choke tiles | ORANGE | `BotCentralDefense.py` line 62 |
| city pre-def gath targets | BLUE | `BotCityOps.py` line 1846 |
| DEFEND CITIES | PURPLE | `BotRendering.py` line 161 |
| GRAY = DUPLICATE FLOW OPTION TILES | GRAY | `BotRendering.py` line 218 |
| ALLIN TARGS | GRAY | `BotCombatOps.py` line 620 |

**Method**: `ViewInfo.add_targeted_tiles_with_legend()` in `ViewInfo.py` (lines 198-201)

---

## Flow Expansion Rendering

Flow expansion uses multiple visual elements to debug and visualize the flow graph.

### Flow Graph Arrows
- **PURPLE/BLUE arrows**: YES neutral max flows (includes neutral tiles)
- **BLACK/PINK arrows**: NO neutral max flows (excludes neutral tiles)
- **Location**: `BehaviorAlgorithms/IterativeExpansion.py` lines 2248-2263

### Flow Option Tile Colors
- **GREEN**: Gathing tiles (tiles where gather is happening)
- **RED**: Capping tiles (tiles being captured)
- **ORANGE**: Incomplete target tiles (tiles that should be captured but aren't in the plan)
- **BLUE**: Incomplete source tiles (tiles with unused army that should flow)
- **GRAY**: Duplicate flow option tiles (tiles appearing in multiple options)
- **Location**: `BehaviorAlgorithms/IterativeExpansion.py` lines 2123-2154

### Fake-Connected Islands
- **RED circles**: Islands connected to fake nodes (disconnected components, repair sources/sinks, overflow dumps)
- **Location**: `BotRendering.py` lines 268-273

---

## Grid Text Overlays

The viewer supports multiple text overlay positions on each tile:

| Position | Variable Name | Common Uses |
|----------|---------------|-------------|
| Top Right | `topRightGridText` | Tile deltas, choke widths, island names, city scores |
| Mid Right | `midRightGridText` | Enemy vision seen status, city scores, delta old army |
| Bottom Mid Right | `bottomMidRightGridText` | Army emergence values, tile deltas, tile states, city scores |
| Bottom Right | `bottomRightGridText` | Tile deltas, city scores |
| Bottom Left | `bottomLeftGridText` | Tile deltas, centrality distances, pathway distances, city scores |
| Bottom Mid Left | `bottomMidLeftGridText` | Tile deltas, intercept plan metrics |
| Mid Left | `midLeftGridText` | Enemy vision visible status |

**Definition**: `ViewInfo.py` lines 116-122
**Rendering**: `base/viewer.py` lines 860-886

---

## Intercept Plan Rendering

Intercept plans display detailed metrics on choke tiles via grid text overlays:

| Metric | Position | Meaning |
|--------|----------|---------|
| cw | bottomMidRightGridText | Choke width |
| ic | bottomMidLeftGridText | Intercept choke distance (difference between worst/best case intercept pathing) |
| it | bottomLeftGridText | Intercept turn (turn tile must be reached to guarantee 2-move-intercept) |
| im | midRightGridText | Intercept moves (worst case moves to achieve intercept capture) |

**Location**: `BotRendering.py:render_intercept_plan()` lines 372-390
**Legend**: `Tests/TestBase.py` lines 989-998

---

## Division Borders and Zones

### Division Borders
Colored borders drawn around sets of tiles using `add_map_division()`.

| Color | Meaning | Code Location |
|-------|---------|---------------|
| `(10, 230, 0)` | Core play area | `BotRendering.py` line 96 |
| `(255, 230, 0)` | Extended play area | `BotRendering.py` line 97 |
| `(205, 80, 40)` | Flank danger play area | `BotRendering.py` line 98 |
| `(0, 0, 0)` | Flankable fog area borders | `BotRendering.py` line 99 |
| Scaled PLAYER_COLORS | Enemy connected tiles | `BotRendering.py` line 145 |
| WHITE | Defensive spanning tree | `BotRendering.py` line 157 |

### Zones
Colored tile overlays using `add_map_zone()`.

| Color | Alpha | Meaning | Code Location |
|-------|-------|---------|---------------|
| `(100, 100, 50)` | 35 | Non-core play area | `BotRendering.py` line 93 |
| `(255, 255, 255)` | 40 | Flankable fog area | `BotRendering.py` line 100 |
| `(50, 100, 50)` | 75 | Backwards tiles | `BotRendering.py` line 101 |
| Scaled PLAYER_COLORS | 65 | Enemy connected tiles | `BotRendering.py` line 146 |
| P_MAROON | 100 | Defensive spanning tree zone | `BotRendering.py` line 158 |
| GOLD | 50 | Friendly city spanning tree | `BotRendering.py` line 164 |

**Methods**: `ViewInfo.add_map_division()` and `ViewInfo.add_map_zone()`
**Rendering**: `viewer.draw_division_borders()` in `base/viewer.py` lines 1267-1396

---

## Path Colors

Paths are rendered with fading colors using the `PathColorer` class.

| Color | Meaning | Code Location |
|-------|---------|---------------|
| WHITE (254, 254, 254) | Current move path | `BotRendering.py` lines 49-56 |
| (60, 50, 0) | Target player gather path | `BotRendering.py` line 86 |
| (255, 185, 75) | Enemy attack path | `BotRendering.py` lines 120-126 |
| (0, 200, 50) | Current path (if set) | `BotRendering.py` line 33 |
| Varies by threat type | Danger analyzer threat paths | `base/viewer.py` lines 722-743 |

**Class**: `ViewInfo.PathColorer` in `ViewInfo.py` lines 60-66
**Rendering**: `viewer.draw_path()` in `base/viewer.py`

---

## Gather Rendering

| Element | Color | Meaning | Code Location |
|---------|-------|---------|---------------|
| lineArrow | Normal gather nodes | `BotRendering.py` line 80 |
| redLineArrow | Red gather nodes (pruned) | `BotRendering.py` line 79 |

**Rendering**: `viewer.drawGathers()` in `base/viewer.py`

---

## Army Tracker Rendering

| Element | Color | Meaning | Code Location |
|---------|-------|---------|---------------|
| RED circles | Dropped fog tiles this turn | `BotRendering.py` line 67 |
| GREEN circles | Decremented fog tiles this turn | `BotRendering.py` line 70 |
| RED circles (radius -5) | Unconnectable tiles | `BotRendering.py` line 141 |

---

## Tile Delta Rendering

When `info_render_tile_deltas` is enabled, tile deltas are shown via grid text overlays:

| Position | Metric | Meaning |
|----------|--------|---------|
| bottomRightGridText | M/L/G/D | MovedHere/LostSight/GainedSight/Discovered |
| bottomLeftGridText | d+/-N | Army delta |
| bottomMidLeftGridText | u+/-N | Unexplained delta |
| topRightGridText | from->to | Move source/destination |
| midRightGridText | N | Old army count |
| bottomMidRightGridText | old-new | Owner change |

**Method**: `BotRendering.render_tile_deltas_in_view_info()` lines 282-326

---

## Tile State Rendering

When `info_render_tile_states` is enabled, tile state flags are shown:

| Flag | Meaning |
|------|---------|
| - | Not pathable |
| - | Not in reachable tiles |
| C | Costly neutral city |
| X | Not in reachable tiles |
| O | Obstacle |
| M | Mountain |
| p/z | Override pathable (true/false) |

**Method**: `BotRendering.render_tile_state_in_view_info()` lines 329-354

---

## City Score Rendering

When city scores are rendered, multiple metrics are displayed per tile:

| Position | Metric | Meaning |
|----------|--------|---------|
| topRightGridText | rN.N | City relevance score |
| midRightGridText | eN.N | City expandability score |
| bottomMidRightGridText | dN.N | City defensability score |
| bottomRightGridText | gN.N | City general defense score |
| bottomLeftGridText | eN.N | Weighted enemy capture value (if owned) |
| bottomLeftGridText | nN.N | Weighted neutral value (if neutral) |

**Method**: `BotRendering.add_city_score_to_view_info()` lines 357-369

---

## Arrows

Arrows are rendered with labels and bidirectional support via `ViewInfo.arrows`.

| Structure | (fromX, fromY, toX, toY, label, color, alpha, isBidirectional, labelAlpha) |
|-----------|-----------------------------------------------------------------------------------|

**Definition**: `ViewInfo.py` line 126
**Rendering**: `viewer._draw_arrows()` in `base/viewer.py` lines 1730-1756

---

## Render Order

The viewer renders elements in the following order (from `base/viewer.py` _drawGrid method):

1. Tile player colors and special tile shapes (lines 558-660)
2. Territory markers (lines 660-668)
3. Board chokes (line 670)
4. Division borders (line 672)
5. **Border gradients (threat blocks)** (line 674) ← **New feature**
6. Targeting army square (lines 676-677)
7. Gather nodes (lines 679-682)
8. Paths (lines 704-743)
9. Targets (line 745)
10. General approximations (lines 747-758)
11. Evaluated grid red X (lines 766-773)
12. Deltas (lines 775-780)
13. Grid text overlays (lines 782-886)
14. Armies (line 888)
15. Emergences (line 890)
16. Arrows (line 892)
17. Army value text (lines 894-923)

---

## Adding New Rendering Elements

To add a new visual element:

1. **For simple targeted tiles**: Use `ViewInfo.add_targeted_tile()` or `ViewInfo.add_targeted_tiles_with_legend()`
2. **For border gradients**: Use `ViewInfo.add_border_gradient()` with tile pairs and colors
3. **For paths**: Create a `PathColorer` object and call `ViewInfo.color_path()`
4. **For zones/divisions**: Use `ViewInfo.add_map_zone()` or `ViewInfo.add_map_division()`
5. **For arrows**: Append to `ViewInfo.arrows` list
6. **For text overlays**: Set values in the appropriate `*GridText` MapMatrix

All rendering data is cleared via `ViewInfo.clear_for_next_turn()` (lines 156-193).
