"""
    @ Harris Christiansen (Harris@HarrisChristiansen.com)
    January 2016
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Game Viewer
"""
import gc
import os
import pathlib
import queue
import sys
import traceback
from multiprocessing import Queue

from Interfaces import TilePlanInterface
from base.Colors import *

import pygame
from pygame import *

import BotLogging
from ArmyAnalyzer import *

from ViewInfo import ViewInfo
from base.client.map import MapBase, Score

MIN_WINDOW_WIDTH = 16

# Color Definitions


# P_BRIGHT_GREEN = (10,225,90)
PLAYER_COLORS = [
    P_RED,
    P_BLUE,
    P_GREEN,
    P_PURPLE,
    P_TEAL,
    P_DARK_GREEN,
    P_YELLOW,
    P_DARK_RED,
    ORANGE,
    LIGHT_BLUE,
    LIGHT_PINK,
    P_LIGHT_PURPLE,
]
FOG_COLOR_OFFSET = 25
KING_COLOR_OFFSET = 35

UP_ARROW = "^"
DOWN_ARROW = "v"
LEFT_ARROW = "<"
RIGHT_ARROW = ">"

CELL_MARGIN = 1

"""
LEGEND
Player information card readout:
{Name} ([Stars])
{Army} on {TileCount} ({CityCount}) [{TargetPriority*}]

    *Target Priority is used to select which player to consider the current main opponent during an FFA
    
Information area:
Top line
    -> The THING the bot is currently doing, basically the evaluation that led to a move selection.
C{CycleInterval} Q{QuickExpandTurns} g{Gather/AttackSplitTurn} L{LaunchTiming} Off{Offset} ({CurrentCycleTurn})

black arrows 
    -> intended gather lines
red arrows 
    -> considered gather lines that were trimmed
green chevrons
    -> the AI'p current army movement path (used when launching timing attacks or attacks against cities etc).
yellow chevrons
    -> indicate a calculated kill-path against an enemy general that was found during other operations and took priority.
pink chevrons 
    -> intended tile-expansion path
blue chevrons 
    -> intended general hunt heuristic exploration path
red chevrons 
    -> enemy threat path against general
little colored square in tile top right 
    -> AI evaluates that this tile is probably enemy territory. Uses knowledge that it has about historical empty tiles
        to eliminate tiles bridged by current-or-previous neutral tiles. This is used when predicting enemy general location
        based on armies appearing from fog of war.
red Xs 
    -> tiles evaluated in a specific search that happened that turn. The more often a tile is evaluated, the darker the red X.
little green lines between tiles 
    ->
purple outline inside tiles
    -> Indicates this tile is calculated to be a 'choke' tile on the set of tiles in the shortest path between generals.
        This means that an attacking army from the enemy general must cross this tile, or take a less optimal path at least
        two tiles longer. This lets the AI optimize defense 1-2 turns later than it would otherwise need to 
        when attempting to intercept attacks.



"""


class DirectionalShape(object):
    def __init__(self, downShape, rotateInitial: int = 0):
        if rotateInitial != 0:
            downShape = pygame.transform.rotate(downShape, rotateInitial)

        self.downShape = downShape
        self.leftShape = pygame.transform.rotate(downShape, -90)
        self.rightShape = pygame.transform.rotate(downShape, 90)
        self.upShape = pygame.transform.rotate(downShape, 180)


def clean_up_possible_float(value_to_render):
    if isinstance(value_to_render, float):
        return '{0:.0f}'.format(value_to_render)
    return str(value_to_render)


class GeneralsViewer(object):
    def __init__(
            self,
            update_queue: "Queue[typing.Tuple[ViewInfo | None, MapBase | None, bool]]",
            pygame_event_queue: "Queue[typing.Tuple[str, typing.Any]]",
            name=None,
            cell_width: int | None = None,
            cell_height: int | None = None,
            no_log: bool = False,
    ):
        self._killed = False
        self._inbound_update_queue: "Queue[typing.Tuple[ViewInfo | None, MapBase | None, bool]]" = update_queue
        self._event_queue: "Queue[typing.Tuple[str, typing.Any]]" = pygame_event_queue
        self._scores: typing.List[Score] = []
        self._map: MapBase = None
        self._real_width = 0
        self._name = name
        self.last_update_received: float = time.perf_counter()
        self._receivedUpdate = False
        self.Arrow = None
        self.lineArrow: DirectionalShape = None
        self.redLineArrow: DirectionalShape = None
        self.line = None
        self.noLog: bool = no_log
        # Table Properies
        self.cellWidth: int = cell_width
        self.cellHeight: int = cell_height

        self.infoLineHeight = 0
        self.infoRowHeight = 0
        self.statsWidth = 0
        self.board_width_px = 0
        self.window_width_px = 0
        self.last_render_time: float = time.perf_counter()

        self.plusDepth = 9
        self.scoreRowHeight: int = 0
        self.square: Rect = None
        self.square_inner_1: Rect = None
        self.square_inner_2: Rect = None
        self.square_inner_3: Rect = None
        self.square_inner_4: Rect = None
        self.square_inner_5: Rect = None
        self._red_x: Surface = None

    def updateGrid(self, viewInfo: ViewInfo, map: MapBase):
        if viewInfo is not None:
            self._viewInfo = viewInfo
        if map is not None:
            self._map = map
            # self._real_width = self._map.cols
            # if self._map.cols < 11:
            #     for y, row in enumerate(self._map.grid):
            #         for x in range(self._map.cols, 11):
            #             row.append(Tile(x, y, TILE_MOUNTAIN, 0))
            #     self._map.cols = 11
            self._map.init_grid_movable()
            if self._map.is_2v2:
                self._scores = map.scores
            else:
                self._scores = sorted(map.scores, key=lambda score: score.total, reverse=True)  # Sort Scores

    def get_line_arrow(self, r, g, b, width=3):
        s = pygame.Surface((self.cellWidth + 2 * CELL_MARGIN, self.cellHeight + 2 * CELL_MARGIN))
        # first, "erase" the surface by filling it with a color and
        # setting this color as colorkey, so the surface is empty
        s.fill(WHITE)
        s.set_colorkey(WHITE)
        pygame.draw.line(s, (r, g, b), (self.cellWidth // 2 + CELL_MARGIN, 0),
                         (self.cellWidth // 2 + CELL_MARGIN, self.cellHeight), width)
        pygame.draw.line(s, (r, g, b), (self.cellWidth // 2 + CELL_MARGIN, self.cellHeight),
                         (self.cellWidth * 2.5 / 8 + CELL_MARGIN, self.cellHeight * 5 / 8), width)
        pygame.draw.line(s, (r, g, b), (self.cellWidth // 2 + CELL_MARGIN, self.cellHeight),
                         (self.cellWidth * 5.5 / 8 + CELL_MARGIN, self.cellHeight * 5 / 8), width)
        return s

    def get_line(self, r, g, b, width=1):
        s = pygame.Surface((self.cellWidth + 2 * CELL_MARGIN, self.cellHeight + 2 * CELL_MARGIN))
        # first, "erase" the surface by filling it with a color and
        # setting this color as colorkey, so the surface is empty
        s.fill(WHITE)
        s.set_colorkey(WHITE)
        # pygame.draw.line(p, (r, g, b), ((CELL_MARGIN + self.cellWidth) // 2, 0), ((CELL_MARGIN + self.cellWidth) // 2, self.cellHeight + 1), width)
        pygame.draw.line(s, (r, g, b), (self.cellWidth // 2 + CELL_MARGIN, 0),
                         (self.cellWidth // 2 + CELL_MARGIN, self.cellHeight), width)
        return s

    def _initViewier(self, alignTop: bool, alignLeft: bool):
        bottomPos, leftPos, rightPos, topPos = self.get_config_positions()

        self.infoLineHeight = 17
        self.infoRowHeight = 350
        self.statsWidth = 650

        if self.cellHeight is None:
            self.cellHeight = min(85, (1080 - self.infoRowHeight - self.scoreRowHeight) // (self._map.rows + 1))
            self.cellHeight = max(29, self.cellHeight)
            self.cellWidth = self.cellHeight

        self.board_width_px = self._map.cols * (self.cellWidth + CELL_MARGIN) + CELL_MARGIN

        self.window_width_px = self.board_width_px + self.statsWidth

        self.scoreRowHeight = int((self.cellHeight + 2) * 3.5)

        self.tile_surface = pygame.Surface((self.cellWidth, self.cellHeight))
        self.player_fight_indicator_width = 2 * self.cellWidth

        x = leftPos  # + 3
        if not alignLeft:
            x = rightPos - self.window_width_px  # - 3

        y = topPos + 3  # space to click the top
        if not alignTop:
            y = bottomPos  # bottom monitor

        position = (x, y)

        os.environ['SDL_VIDEO_WINDOW_POS'] = "%d,%d" % position
        os.environ['SDL_VIDEO_ALLOW_SCREENSAVER'] = "1"
        os.environ['SDL_HINT_VIDEO_ALLOW_SCREENSAVER'] = "1"
        pygame.init()

        self.square = Rect(0, 0, self.cellWidth, self.cellHeight)
        self.square_inner_1 = Rect(1, 1, self.cellWidth - 2, self.cellHeight - 2)
        self.square_inner_2 = Rect(2, 2, self.cellWidth - 4, self.cellHeight - 4)
        self.square_inner_3 = Rect(3, 3, self.cellWidth - 6, self.cellHeight - 6)
        self.square_inner_4 = Rect(4, 4, self.cellWidth - 8, self.cellHeight - 8)
        self.square_inner_5 = Rect(5, 5, self.cellWidth - 10, self.cellHeight - 10)
        self.plusDepth = self.cellWidth // 3 - 1  # bigger number = bigger squares in the corners. Idk why, the math on this doesnt make sense lol but it draws a plus i guess. // 4 (no -1) was pretty good sized.

        # Set Window Size
        window_height = self._map.rows * (
                    self.cellHeight + CELL_MARGIN) + CELL_MARGIN + self.scoreRowHeight + self.infoRowHeight
        self._window_size = [self.window_width_px, window_height]
        self._screen = pygame.display.set_mode(self._window_size)
        self._transparent = pygame.Surface(self._window_size, pygame.SRCALPHA)

        window_title = str(self._name)
        pygame.display.set_caption(window_title)
        self._medFontHeight = min(2 * self.cellHeight // 5, 30)
        self._smallFontHeight = min(self.cellHeight // 4, 17)
        self._lrgFontHeight = 3 * self.cellHeight // 5 + 1
        self._medFont = pygame.font.SysFont('Arial', self._medFontHeight)
        self._infoFont = pygame.font.SysFont('Arial', self.infoLineHeight)
        self._smallFont = pygame.font.SysFont('Arial', self._smallFontHeight)
        self._lrgFont = pygame.font.SysFont('Arial', self._lrgFontHeight)
        self._smallFontWidth = self._smallFontHeight / 2.27
        self._medFontWidth = self._medFontHeight / 2.27
        self._lrgFontWidth = self._lrgFontHeight / 2.27
        # self.statsSpaceFromLeft = self.get_large_text_offset_from_right("Turn: 1000, (.50) ")
        samplePerfText = ".004 Rebuilding intergeneral_analysis "
        self.perfWidthCutoff = len(samplePerfText)
        self.statsSpaceFromLeft = self.get_any_text_width(samplePerfText, self.infoLineHeight / 2.27) + 1

        self._clock = pygame.time.Clock()

        self._red_x = pygame.Surface((self.cellWidth, self.cellHeight))
        self._red_x.fill(WHITE)
        self._red_x.set_colorkey(WHITE)
        pygame.draw.line(self._red_x, BLACK, (0, 0), (self.cellWidth, self.cellHeight), 4)
        pygame.draw.line(self._red_x, RED, (0, 0), (self.cellWidth, self.cellHeight), 2)
        pygame.draw.line(self._red_x, BLACK, (0, self.cellHeight), (self.cellWidth, 0), 4)
        pygame.draw.line(self._red_x, RED, (0, self.cellHeight), (self.cellWidth, 0), 2)

        self.pathAlphas = []
        self.Arrow = [(self.cellWidth / 2, 0), (self.cellWidth / 8, self.cellHeight / 2),
                      (self.cellWidth / 2, self.cellHeight / 4),
                      (7 * self.cellWidth / 8, self.cellHeight / 2)]
        # self.Arrow = [(self.cellWidth / 2, 0), (self.cellWidth / 8, self.cellHeight / 2), (self.cellWidth / 2, self.cellHeight / 4), (7 * self.cellWidth / 8, self.cellHeight / 2)]

        self.lineArrow = DirectionalShape(self.get_line_arrow(0, 0, 0))
        self.redLineArrow = DirectionalShape(self.get_line_arrow(255, 0, 0, width=1))
        self.line = DirectionalShape(self.get_line(0, 0, 0))
        self.delta_arrow = DirectionalShape(self.get_delta_arrow())
        self.green_line = DirectionalShape(self.get_line(0, 185, 35))
        self.yellow_line = DirectionalShape(self.get_line(185, 181, 35))
        self.red_line = DirectionalShape(self.get_line(225, 15, 15))
        self.repId = self._map.replay_url.split("/").pop()

        self.logDirectory = BotLogging.get_file_logging_directory(self._map.usernames[self._map.player_index], self.repId)

    def get_config_positions(self):
        cfgPath = pathlib.Path(__file__).parent / "../../run_config.txt"
        with open(cfgPath, 'r') as file:
            data = file.read()
        cfgContents = data.splitlines()
        topPos = 3
        bottomPos = 1080
        rightPos = 1920
        leftPos = 0
        for line in cfgContents:
            if "=" not in line:
                continue

            key, value = line.split('=')

            if key == "left_pos":
                leftPos = int(value)
            if key == "right_pos":
                rightPos = int(value)
            if key == "bottom_pos":
                bottomPos = int(value)
            if key == "top_pos":
                topPos = int(value)

        return bottomPos, leftPos, rightPos, topPos

    def run_main_viewer_loop(self, alignTop=True, alignLeft=True, loggingQueue = None):
        MapBase.DO_NOT_RANDOMIZE = True
        termSec = 600
        if not self.noLog:
            import logging
            BotLogging.set_up_logger(logbook.INFO, mainProcess=False, queue=loggingQueue)
        while not self._receivedUpdate:  # Wait for first update
            try:
                viewInfo, map, isComplete = self._inbound_update_queue.get(block=True, timeout=15.0)
                if viewInfo is not None:
                    self._receivedUpdate = True
                    self.updateGrid(viewInfo, map)
                else:
                    self.last_update_received = time.perf_counter()
            except queue.Empty:
                elapsed = time.perf_counter() - self.last_update_received
                if not self.noLog:
                    logbook.info(f'waiting for update...... {elapsed:.3f} / {termSec} sec')
                # TODO add a server ping callback here so while we're waiting in a lobby for a while we can keep the viewer thread alive
                if elapsed > termSec:
                    logbook.info(f'GeneralsViewer zombied with no game start, self-terminating after {termSec} seconds')
                    time.sleep(1.0)

                    self.send_closed_event(killedByUserClose=False)  # this causes the bot itself to die when it finally starts a game after being in queue for a long time.
                    self._killed = True
                    self._receivedUpdate = True
                    time.sleep(1.0)
                    return

        self._initViewier(alignTop=alignTop, alignLeft=alignLeft)
        self.last_update_received = time.perf_counter()

        done = False

        closedByUser = False

        viewInfo: ViewInfo | None = None
        map: MapBase | None = None
        isComplete: bool = False

        renderIntervalAvgWindow = 20
        rollingUpdateWindow = queue.Queue()
        for i in range(renderIntervalAvgWindow):
            rollingUpdateWindow.put(0.15)
        lastWindowUpdateSum = 0.15 * renderIntervalAvgWindow
        self.last_render_time = time.perf_counter() - 0.5

        while not done:
            if self._killed:
                done = True  # Flag done
                self._map.complete = True
                break

            try:
                if not self.noLog:
                    logbook.info("GeneralsViewer waiting for queue event:")
                viewInfo, map, isComplete = self._inbound_update_queue.get(block=True, timeout=1.0)
                self._map = map
                thisUpdateTime = time.perf_counter()
                diff = thisUpdateTime - self.last_update_received
                medianUpdateTime = lastWindowUpdateSum / renderIntervalAvgWindow

                medianUpdateTime = min(0.5, medianUpdateTime)

                expectedRenderTime = self.last_render_time + medianUpdateTime

                self.last_update_received = thisUpdateTime

                if isComplete:
                    logbook.info("GeneralsViewer received done event!")
                    done = True

                if not self.noLog:
                    logbook.info(f"GeneralsViewer received an event after {diff:.3f}! Updating _grid")

                if diff < medianUpdateTime * 4:
                    # ignore massively delayed updates
                    lastWindowUpdateSum = lastWindowUpdateSum + diff - rollingUpdateWindow.get()
                    rollingUpdateWindow.put(diff)

                self.updateGrid(viewInfo, map)

                sleepFor = expectedRenderTime - thisUpdateTime - 0.05
                if sleepFor > 0:
                    logbook.info(f"GeneralsViewer sleeping for {sleepFor:.3f} calculated expected render {expectedRenderTime:.3f} from medianUpdateTime {medianUpdateTime:.3f} based on lastWindowUpdateSum {lastWindowUpdateSum:.3f}")
                    time.sleep(sleepFor)

                start = time.perf_counter()
                if not self.noLog:
                    logbook.info("GeneralsViewer drawing _grid:")
                try:
                    self._drawGrid()
                except Exception as ex:
                    logbook.error(f'VIEWER ERROR {traceback.format_exc()}')
                    print(traceback.format_exc())

                self.last_render_time = start

                if not self.noLog:
                    logbook.info(f"GeneralsViewer drawing _grid took {time.perf_counter() - start:.3f}")

                if not self.noLog:
                    start = time.perf_counter()
                    logbook.info("GeneralsViewer saving image:")
                    self.save_image()

                    logbook.info(f"GeneralsViewer saving image took {time.perf_counter() - start:.3f}")

                    gc.collect()
            except queue.Empty:
                elapsed = time.perf_counter() - self.last_update_received
                if not self.noLog:
                    logbook.info(f'No GeneralsViewer update received in {elapsed:.2f} seconds')
                if elapsed > 600.0:
                    logbook.info(f'GeneralsViewer zombied, self-terminating after 10 seconds')
                    done = True
                    self.send_closed_event(killedByUserClose=False)
                pass
            except EOFError:
                logbook.info('GeneralsViewer pipe died (EOFError)')
                done = True
            except BrokenPipeError:
                logbook.info('GeneralsViewer pipe died (BrokenPipeError)')
                done = True

            for event in pygame.event.get():  # User did something
                if event.type == pygame.QUIT:  # User clicked quit
                    done = True  # Flag done
                    logbook.info('GeneralsViewer pygame exited by user, setting done and exiting')
                    closedByUser = True
                    break

                elif event.type == pygame.MOUSEBUTTONDOWN:  # Mouse Click
                    pos = pygame.mouse.get_pos()
                    # Convert screen to _grid coordinates
                    column = pos[0] // (self.cellWidth + CELL_MARGIN)
                    row = pos[1] // (self.cellHeight + CELL_MARGIN)

                    print(f"CLICK {column},{row}")

                    clickedTile = self._map.GetTile(column, row)
                    if event.button == 1:
                        self._event_queue.put(('LEFT_CLICK', clickedTile))
                    elif event.button == 2:
                        self._event_queue.put(('MIDDLE_CLICK', clickedTile))
                    elif event.button == 3:
                        self._event_queue.put(('RIGHT_CLICK', clickedTile))
                    elif event.button == 4:
                        self._event_queue.put(('SCROLL_UP', clickedTile))
                    elif event.button == 5:
                        self._event_queue.put(('SCROLL_DOWN', clickedTile))
                    else:
                        self._event_queue.put(('UNKNOWN', clickedTile))
        mapComplete = None
        if map is not None:
            mapComplete = map.complete
        logbook.info(f'Pygame closed in GeneralsViewer, sending closedByUser {closedByUser} | map.complete {mapComplete} back to main threads')
        #
        # if map.complete:
        #     closedByUser = True

        self.send_closed_event(closedByUser)
        logbook.info('GeneralsViewer, exiting pygame w/ pygame.quit() in 1 second:')
        time.sleep(1.0)
        pygame.quit()  # Done.  Quit pygame.


    def _drawGrid(self):
        try:
            self.include_viable_general_spawns()

            self._screen.fill(BLACK)  # Set BG Color
            self._transparent.fill((0, 0, 0, 0))  # transparent

            # Draw Bottom Info Text
            self._screen.blit(self._lrgFont.render(
                f"Turn: {self._map.turn}, ({('%.2f' % self._viewInfo.lastMoveDuration).lstrip('0')})",
                True, WHITE), (10, self._window_size[1] - self.infoRowHeight + 4))

            self.draw_stat_text()

            self.draw_info_text()

            self.draw_perf_stats()

            # Draw Scores
            self.draw_player_scores()

            # for i, score in enumerate(self._scores):
            #    score_color = PLAYER_COLORS[int(score['i'])]
            #    if (score['dead'] == True):
            #        score_color = GRAY_DARK
            #    pygame.draw.rect(self._screen, score_color, [score_width * i, pos_top, score_width, SCORES_ROW_HEIGHT])
            #    userString = self._map.usernames[int(score['i'])]
            #    if (self._map.stars):
            #        userString = userString + " (" + str(self._map.stars[int(score['i'])]) + ")"
            #    self._screen.blit(self._font.render(userString, True, WHITE), (score_width * i + 3, pos_top + 1))
            #    self._screen.blit(self._font.render(str(score['total']) + " on " + str(score['tiles']), True, WHITE), (score_width * i + 3, pos_top + 1 + self._font.get_height()))

            # Draw Grid
            for row in range(self._map.rows):
                for column in range(self._map.cols):
                    tile = self._map.grid[row][column]
                    # Determine BG Color
                    color = self.get_tile_color(tile)

                    pos_left = (CELL_MARGIN + self.cellWidth) * column + CELL_MARGIN
                    pos_top = (CELL_MARGIN + self.cellHeight) * row + CELL_MARGIN

                    if tile in self._map.generals:  # General
                        # Draw Plus
                        pygame.draw.rect(self._screen, color,
                                         [pos_left + self.plusDepth, pos_top, self.cellWidth - self.plusDepth * 2,
                                          self.cellHeight])
                        pygame.draw.rect(self._screen, color,
                                         [pos_left, pos_top + self.plusDepth, self.cellWidth,
                                          self.cellHeight - self.plusDepth * 2])
                    elif tile.isCity:  # City
                        # Draw Circle
                        pos_left_circle = int(pos_left + (self.cellWidth / 2))
                        pos_top_circle = int(pos_top + (self.cellHeight / 2))
                        pygame.draw.circle(self._screen, color, [pos_left_circle, pos_top_circle],
                                           int(self.cellWidth / 2))
                    else:
                        # Draw Rect
                        pygame.draw.rect(self._screen, color, [pos_left, pos_top, self.cellWidth, self.cellHeight])

                    # mark tile territories
                    if self._viewInfo.territories is not None:
                        territoryMarkerSize = 5
                        tileTerritoryPlayer = self._viewInfo.territories.territoryMap[tile]
                        if tile.player != tileTerritoryPlayer:
                            territoryColor = None
                            if tileTerritoryPlayer != -1:
                                territoryColor = PLAYER_COLORS[tileTerritoryPlayer]
                                pygame.draw.rect(self._screen, territoryColor,
                                                 [pos_left + self.cellWidth - territoryMarkerSize, pos_top,
                                                  territoryMarkerSize,
                                                  territoryMarkerSize])

            self.draw_board_chokes()

            self.draw_division_borders()

            if self._viewInfo.targetingArmy is not None:
                self.draw_square(self._viewInfo.targetingArmy.tile, 2, 25, 25, 25, 200, self.square_inner_3)

            if self._viewInfo.redGatherNodes is not None:
                self.drawGathers(self._viewInfo.redGatherNodes, self.redLineArrow, self.redLineArrow, alpha=150, pruneAlpha=150)
            if self._viewInfo.gatherNodes is not None:
                self.drawGathers(self._viewInfo.gatherNodes, self.lineArrow, self.redLineArrow)

            # if self._viewInfo.board_analysis and self._viewInfo.board_analysis.intergeneral_analysis:
            #     chokeColor = CHOKE_PURPLE # purple
            #     self.draw_army_analysis(self._viewInfo.board_analysis.intergeneral_analysis, chokeColor, draw_pathways = True)

            # LINE TESTING CODE
            # gen = self._viewInfo.general
            # left = self._map.grid[gen.y][gen.x - 1]
            # leftDown = self._map.grid[gen.y + 1][gen.x - 1]
            # down = self._map.grid[gen.y + 1][gen.x]

            # self.draw_between_tiles(self.green_line, gen, left)
            # self.draw_between_tiles(self.green_line, left, leftDown)
            # self.draw_between_tiles(self.green_line, leftDown, down)
            # self.draw_between_tiles(self.green_line, down, gen)

            # p(self._map.grid[1][1],

            # while len(self._viewInfo.paths) > 0:
            #     pColorer = self._viewInfo.paths.pop()
            #     self.draw_path(pColorer.path, pColorer.color[0], pColorer.color[1], pColorer.color[2], pColorer.alpha,
            #                    pColorer.alphaDecreaseRate, pColorer.alphaMinimum)

            for pColorer in self._viewInfo.paths:
                self.draw_path(
                    pColorer.path,
                    pColorer.color[0],
                    pColorer.color[1],
                    pColorer.color[2],
                    pColorer.alpha,
                    pColorer.alphaDecreaseRate,
                    pColorer.alphaMinimum)

            alpha = 250
            alphaDec = 4
            alphaMin = 135
            path = None
            if self._viewInfo.currentPath is not None:
                path = self._viewInfo.currentPath
            self.draw_path(path, 0, 200, 50, alpha, alphaDec, alphaMin)

            if self._viewInfo.dangerAnalyzer is not None and self._viewInfo.dangerAnalyzer.anyThreat:
                b = 0
                r = 200
                for threat in [
                    self._viewInfo.dangerAnalyzer.fastestThreat,
                    self._viewInfo.dangerAnalyzer.fastestAllyThreat,
                    self._viewInfo.dangerAnalyzer.highestThreat,
                    self._viewInfo.dangerAnalyzer.fastestCityThreat,
                    None,
                    self._viewInfo.dangerAnalyzer.fastestVisionThreat,
                ]:
                    if threat is None:
                        r -= 30
                        b += 30
                        continue
                    # Draw danger path
                    alpha = 200
                    alphaDec = 6
                    alphaMin = 145
                    self.draw_path(threat.path, r, 0, b, alpha, alphaDec, alphaMin)
                    r -= 30
                    b += 30

            self.draw_targets()

            for i, approx in enumerate(self._viewInfo.generalApproximations):
                if approx[2] > 0:
                    pColor = PLAYER_COLORS[i]
                    pos_left = (CELL_MARGIN + self.cellWidth) * approx[0] + CELL_MARGIN
                    pos_top = (CELL_MARGIN + self.cellHeight) * approx[1] + CELL_MARGIN
                    pos_left_circle = int(pos_left + (self.cellWidth / 2))
                    pos_top_circle = int(pos_top + (self.cellHeight / 2))
                    pygame.draw.circle(self._screen, BLACK, [pos_left_circle, pos_top_circle],
                                       self.cellWidth / 2 - 2,
                                       7)
                    pygame.draw.circle(self._screen, pColor, [pos_left_circle, pos_top_circle],
                                       self.cellWidth / 2 - 5, 1)
            s = pygame.Surface((self.cellWidth, self.cellHeight))
            s.fill(WHITE)
            s.set_colorkey(WHITE)

            pygame.draw.circle(s, BLACK, [int(self.cellWidth / 2), int(self.cellHeight / 2)],
                               int(self.cellWidth / 2 - 2), 7)

            if (self._map is not None and self._viewInfo is not None and self._viewInfo.evaluatedGrid is not None and len(
                    self._viewInfo.evaluatedGrid) > 0):
                for row in range(self._map.rows):
                    for column in range(self._map.cols):
                        countEvaluated = int(self._viewInfo.evaluatedGrid[column][row])
                        if countEvaluated > 0:
                            alpha = 75 + countEvaluated * 3
                            self.draw_red_x(self._map.GetTile(column, row), alpha=alpha)
            # Draw deltas
            for row in range(self._map.rows):
                for column in range(self._map.cols):
                    tile = self._map.grid[row][column]

                    if tile.delta.toTile:
                        self.draw_between_tiles(self.delta_arrow, tile, tile.delta.toTile)

            # draw text
            for row in range(self._map.rows):
                for column in range(self._map.cols):
                    tile = self._map.grid[row][column]
                    pos_left = (CELL_MARGIN + self.cellWidth) * column + CELL_MARGIN
                    pos_top = (CELL_MARGIN + self.cellHeight) * row + CELL_MARGIN

                    color_font = self.get_font_color(tile)
                    color_small_font = self.get_small_font_color(tile)

                    if not tile in self._map.pathableTiles and not tile.isNotPathable and not tile.isCity and not tile.isMountain:
                        textVal = "   X"
                        self._screen.blit(self._medFont.render(textVal, True, color_font),
                                          (pos_left + 2, pos_top + self.cellHeight / 4))
                    # Draw coords
                    textVal = f"{tile.x},{tile.y}"
                    self._screen.blit(self.small_font(textVal, color_font),
                                      (pos_left, pos_top - 2))

                    # bottom mid
                    # if (self._viewInfo.leafValueGrid != None):
                    #     leafVal = self._viewInfo.leafValueGrid[column][row]
                    #     if (leafVal != None):
                    #         textVal = clean_up_possible_float(leafVal)
                    #         if (leafVal == -1000000):  # then was skipped
                    #             textVal = "x"
                    #         self._screen.blit(self.small_font(textVal, color_font),
                    #                           (pos_left + self.cellWidth / 3, pos_top + 2.2 * self.cellHeight / 3))

                    if self._viewInfo.topRightGridText is not None:
                        text = self._viewInfo.topRightGridText[self._map.GetTile(column, row)]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            text = self.small_font(textVal, color_small_font)
                            r = text.get_rect()
                            r.right = pos_left + self.cellWidth - 1
                            r.top = pos_top - 2
                            self._screen.blit(text, r)

                    if self._viewInfo.midRightGridText is not None:
                        text = self._viewInfo.midRightGridText[self._map.GetTile(column, row)]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            text = self.small_font(textVal, color_small_font)
                            r = text.get_rect()
                            r.right = pos_left + self.cellWidth - 1
                            r.top = pos_top + self.cellHeight / 3
                            self._screen.blit(text, r)

                    if self._viewInfo.bottomMidRightGridText is not None:
                        text = self._viewInfo.bottomMidRightGridText[self._map.GetTile(column, row)]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            text = self.small_font(textVal, color_small_font)
                            r = text.get_rect()
                            r.right = pos_left + self.cellWidth - 1
                            r.top = pos_top + 1.6 * self.cellHeight / 3
                            self._screen.blit(text, r)

                    if self._viewInfo.bottomRightGridText is not None:
                        text = self._viewInfo.bottomRightGridText[self._map.GetTile(column, row)]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            text = self.small_font(textVal, color_small_font)
                            r = text.get_rect()
                            r.right = pos_left + self.cellWidth - 1
                            r.top = pos_top + 2.2 * self.cellHeight / 3
                            self._screen.blit(text, r)

                    if self._viewInfo.bottomLeftGridText is not None:
                        text = self._viewInfo.bottomLeftGridText[self._map.GetTile(column, row)]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + 2, pos_top + 2.2 * self.cellHeight / 3))

                    if self._viewInfo.bottomMidLeftGridText is not None:
                        text = self._viewInfo.bottomMidLeftGridText[self._map.GetTile(column, row)]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + 2, pos_top + 1.6 * self.cellHeight / 3))

                    if self._viewInfo.midLeftGridText is not None:
                        text = self._viewInfo.midLeftGridText[self._map.GetTile(column, row)]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + 2, pos_top + self.cellHeight / 3))

            self.draw_armies()

            self.draw_emergences()

            # draw text
            for row in range(self._map.rows):
                for column in range(self._map.cols):
                    tile = self._map.grid[row][column]
                    pos_left = (CELL_MARGIN + self.cellWidth) * column + CELL_MARGIN
                    pos_top = (CELL_MARGIN + self.cellHeight) * row + CELL_MARGIN

                    color_font = self.get_font_color(tile)
                    color_small_font = self.get_small_font_color(tile)

                    if not tile in self._map.pathableTiles and not tile.isNotPathable and not tile.isCity and not tile.isMountain:
                        textVal = "   X"
                        self._screen.blit(self._medFont.render(textVal, True, color_font),
                                          (pos_left + 2, pos_top + self.cellHeight / 4))

                    # Draw Text Value
                    if (
                        tile.army != 0
                        # and (
                        #     tile.discovered
                        #     or tile in self._viewInfo.armyTracker.armies
                        # )
                    ):  # Don't draw on empty tiles
                        textVal = str(tile.army)
                        textWidth = self._medFontWidth * len(textVal)
                        self._screen.blit(self._medFont.render(textVal, True, color_font),
                                          (pos_left + (self.cellWidth - textWidth) / 2, pos_top + self.cellHeight / 4))
                        self._screen.blit(self._medFont.render(textVal, True, color_font),
                                          (pos_left + (self.cellWidth - textWidth) / 2, pos_top + self.cellHeight / 4))

            # Go ahead and update the screen with what we've drawn.
            pygame.display.flip()

            # Limit to 60 frames per second
            self._clock.tick(15)
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            # logbook.info("inf")  # Log it or whatever here
            # logbook.info(''.join('!! ' + line for line in lines))  # Log it or whatever here
            # logbook.info("warn")  # Log it or whatever here
            # logbook.warn(''.join('!! ' + line for line in lines))  # Log it or whatever here
            logbook.info("err")  # Log it or whatever here
            logbook.error(''.join('!! ' + line for line in lines))  # Log it or whatever here
            raise

    def draw_red_x(self, tile: Tile, alpha: int):
        pos_left = (CELL_MARGIN + self.cellWidth) * tile.x + CELL_MARGIN
        pos_top = (CELL_MARGIN + self.cellHeight) * tile.y + CELL_MARGIN
        alpha = alpha
        self._red_x.set_alpha(alpha if alpha < 255 else 255)
        self._screen.blit(self._red_x, (pos_left, pos_top))

    def draw_info_text(self):
        curInfoTextHeight = 0

        for addlInfo in self._viewInfo.addlInfoLines:
            if addlInfo == self._viewInfo.infoText:
                continue
            self._screen.blit(
                self._infoFont.render(
                    addlInfo,
                    True,
                    WHITE),
                (self.board_width_px, curInfoTextHeight))
            curInfoTextHeight += self.infoLineHeight

        self._screen.blit(self._infoFont.render(self._viewInfo.infoText, True, WHITE),
                          (self.board_width_px, curInfoTextHeight))

    def draw_stat_text(self):
        allInText = " "
        if self._viewInfo.allIn:
            allInText = "+"

        curInfoTextHeight = 0

        if self._viewInfo.timings:
            timings = self._viewInfo.timings
            timingTurn = (self._map.turn + timings.offsetTurns) % timings.cycleTurns
            timingsText = f"{str(timings)} ({timingTurn}) - {allInText}{self._viewInfo.allInCounter}/{self._viewInfo.givingUpCounter}  {self._viewInfo.addlTimingsLineText}"
            self._screen.blit(
                self._infoFont.render(
                    timingsText,
                    True,
                    WHITE),
                (self.statsSpaceFromLeft, self._window_size[1] - self.infoRowHeight + curInfoTextHeight))
            curInfoTextHeight += self.infoLineHeight

        for statInfo in self._viewInfo.statsLines:
            if statInfo == self._viewInfo.infoText:
                continue
            self._screen.blit(
                self._infoFont.render(
                    statInfo,
                    True,
                    WHITE),
                (self.statsSpaceFromLeft, self._window_size[1] - self.infoRowHeight + curInfoTextHeight))
            curInfoTextHeight += self.infoLineHeight


    def draw_perf_stats(self):
        perfEventHeight = self._lrgFontHeight
        for perfEvent in self._viewInfo.perfEvents:
            if perfEvent == self._viewInfo.infoText:
                continue
            self._screen.blit(
                self._infoFont.render(
                    perfEvent[:self.perfWidthCutoff],
                    True,
                    WHITE),
                (0, self._window_size[1] - self.infoRowHeight + perfEventHeight))
            perfEventHeight += self.infoLineHeight

    def draw_targets(self):
        # draw the black circles, THEN the colored circles so we can end up with bands of color.
        for (tile, targetStyle, radReduction) in self._viewInfo.targetedTiles:
            if tile is None:
                continue
            pos_left = (CELL_MARGIN + self.cellWidth) * tile.x + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * tile.y + CELL_MARGIN
            pos_left_circle = pos_left + (self.cellWidth / 2)
            pos_top_circle = pos_top + (self.cellHeight / 2)
            pygame.draw.circle(
                self._screen,
                BLACK,
                center=[pos_left_circle, pos_top_circle],
                radius=self.cellWidth / 2 - radReduction,
                width=4)

        for (tile, targetStyle, radReduction) in self._viewInfo.targetedTiles:
            if tile is None:
                continue
            pos_left = (CELL_MARGIN + self.cellWidth) * tile.x + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * tile.y + CELL_MARGIN
            pos_left_circle = pos_left + (self.cellWidth / 2)
            pos_top_circle = pos_top + (self.cellHeight / 2)
            targetColor = ViewInfo.get_color_from_target_style(targetStyle)
            pygame.draw.circle(
                self._screen,
                targetColor,
                center=[pos_left_circle, pos_top_circle],
                radius=self.cellWidth / 2 - radReduction - 1,
                width=2)

    def tile_text_colorer(self, tile) -> typing.Tuple[int, int, int]:
        if tile.player == -1 and tile.visible:
            return BLACK
        return WHITE

    def draw_square(self, tile, width, R, G, B, alpha, shape=None):
        if shape is None:
            shape = self.square
        key = BLACK

        pos_left = (CELL_MARGIN + self.cellWidth) * tile.x + CELL_MARGIN
        pos_top = (CELL_MARGIN + self.cellHeight) * tile.y + CELL_MARGIN

        color = (min(255, R), min(255, G), min(255, B))

        # first, "erase" the surface by filling it with a color and
        # setting this color as colorkey, so the surface is empty
        self.tile_surface.fill(key)
        self.tile_surface.set_colorkey(key)

        pygame.draw.rect(self.tile_surface, color, shape, width)

        self.tile_surface.set_alpha(alpha)
        self._screen.blit(self.tile_surface, (pos_left, pos_top))

    def draw_army(self, army, R, G, B, alphaStart):
        # after drawing the circle, we can set the
        # alpha value (transparency) of the surface
        tile = army.tile
        (playerR, playerG, playerB) = R, G, B
        if army.player != army.tile.player:
            (playerR, playerG, playerB) = PLAYER_COLORS[army.player]
            playerR += 50
            playerG += 50
            playerB += 50
        # playerR = (playerR + 256) // 2
        # playerG = (playerG + 256) // 2
        # playerB = (playerB + 256) // 2
        self.draw_square(tile, 1, playerR, playerG, playerB, min(255, int(alphaStart * 1.3)))

        # self.draw_path(army.path, R, g, B, alphaStart, 0, 0)

        for path in army.expectedPaths:
            self.draw_path(path, 255, 0, 0, 150, 10, 100)

        pos_left = (CELL_MARGIN + self.cellWidth) * tile.x + CELL_MARGIN
        pos_top = (CELL_MARGIN + self.cellHeight) * tile.y + CELL_MARGIN
        armyStr = army.name
        if army.last_moved_turn > 0:
            armyStr = f'{army.name}-{self._map.turn - army.last_moved_turn}'
        self._screen.blit(self._medFont.render(armyStr, True, WHITE), (pos_left + self.cellWidth - 10, pos_top))

    def draw_armies(self):
        if self._viewInfo.armyTracker is None:
            return

        for army in list(self._viewInfo.armyTracker.armies.values()):
            if army.scrapped:
                self.draw_army(army, 230, 180, 50, 130)
            else:
                self.draw_army(army, 255, 255, 255, 150)

    def include_viable_general_spawns(self):
        if self._viewInfo.armyTracker is None:
            return

        included = []

        for player in self._map.players:
            if self._map.is_player_on_team_with(self._map.player_index, player.index):
                continue
            if player.dead:
                continue

            if len(player.tiles) == 0 and self._map.remainingPlayers > 3:
                continue

            included.append(player)

        alphaScale = 180 // (len(included) + 1)

        for player in included:
            self._viewInfo.add_map_division(self._viewInfo.armyTracker.valid_general_positions_by_player[player.index], PLAYER_COLORS[player.index], alpha=190)

            whitenedPlayerColor = rescale_color(
                valToScale=0.2,
                valueMin=0.0,
                valueMax=1.0,
                colorMin=PLAYER_COLORS[player.index],
                colorMax=GRAY,
            )

            self._viewInfo.add_map_zone(self._viewInfo.armyTracker.valid_general_positions_by_player[player.index], whitenedPlayerColor, alpha=alphaScale)

    def draw_emergences(self):
        alphaMin = 100
        for tile, emergenceTuple in self._map.army_emergences.items():
            emergenceValue, emergencePlayer = emergenceTuple
            (playerR, playerG, playerB) = PLAYER_COLORS[emergencePlayer]
            playerR = int(playerR * 1.25 + 20)
            playerG = int(playerG * 1.25 + 20)
            playerB = int(playerB * 1.25 + 20)

            if tile.player != emergencePlayer:
                (playerR, playerG, playerB) = PLAYER_COLORS[emergencePlayer]

            alpha = min(alphaMin, max(255, rescale_value(abs(emergenceValue), 0, 50, alphaMin, 255)))
            # playerR = (playerR + 256) // 2
            # playerG = (playerG + 256) // 2
            # playerB = (playerB + 256) // 2
            self.draw_square(tile, 2, playerR, playerG, playerB, alpha=alpha)

    def draw_army_analysis(
            self,
            analysis: ArmyAnalyzer,
            chokeColor=None,
            draw_pathways=True,
            outerChokeColor=None,
            innerChokeColor=None):
        if chokeColor:
            for choke in self._map.get_all_tiles():
                if not analysis.is_choke(choke):
                    continue
                # Poiple
                self.draw_square(choke, 1, chokeColor[0], chokeColor[1], chokeColor[2], 230, self.square_inner_1)

        if draw_pathways:
            self.draw_path_ways(analysis.pathWays, (20, 150, 150), (255, 50, 50))

    def draw_line_between_tiles(self, sourceTile: Tile, destTile: Tile, color: typing.Tuple[int, int, int], alpha=255):
        pos_left = 0
        pos_top = 0

        xDiff = destTile.x - sourceTile.x
        yDiff = destTile.y - sourceTile.y

        (r, g, b) = color
        line = self.get_line(r, g, b)

        if xDiff > 0:
            pos_left = (CELL_MARGIN + self.cellWidth) * sourceTile.x + self.cellWidth // 2 + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * sourceTile.y + CELL_MARGIN
            line = pygame.transform.rotate(line, -90)
        if xDiff < 0:
            pos_left = (CELL_MARGIN + self.cellWidth) * sourceTile.x - self.cellWidth // 2 + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * sourceTile.y + CELL_MARGIN
            line = pygame.transform.rotate(line, 90)
        if yDiff > 0:
            pos_left = (CELL_MARGIN + self.cellWidth) * sourceTile.x + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * sourceTile.y + self.cellHeight // 2 + CELL_MARGIN
            line = pygame.transform.rotate(line, 180)
        if yDiff < 0:
            pos_left = (CELL_MARGIN + self.cellWidth) * sourceTile.x + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * sourceTile.y - self.cellHeight // 2 + CELL_MARGIN

        line.set_alpha(alpha)
        self._screen.blit(line, (pos_left - 1, pos_top - 1))

    def draw_path_ways(
            self,
            pathWays: typing.List[PathWay],
            shortestColor: typing.Tuple[int, int, int],
            longestColor: typing.Tuple[int, int, int]):
        minLength = 100000000
        maxLength = -100000000
        for pathWay in pathWays:
            if minLength > pathWay.distance:
                minLength = pathWay.distance
            if maxLength < pathWay.distance and len(pathWay.tiles) > 1:
                maxLength = pathWay.distance

        for pathWay in pathWays:
            drawnFrom = set()
            drawingFrontier = deque()
            drawingFrontier.appendleft(pathWay.seed_tile)
            if pathWay.seed_tile is None:
                logbook.info('WTF, pathway seed tile was none...?')
                continue
            while drawingFrontier:
                tile = drawingFrontier.pop()
                tile = self._map.GetTile(tile.x, tile.y)
                if tile is None:
                    logbook.info('WTF, none tile in pathway draw frontier??')
                    continue
                if tile not in drawnFrom:
                    drawnFrom.add(tile)
                    for adj in tile.movable:
                        if adj is None:
                            logbook.info(f'WTF, moveable tile was none in tile {str(tile)}...?')
                            continue
                        if adj not in drawnFrom:
                            if adj in pathWay.tiles:
                                (r, g, b) = rescale_color(pathWay.distance, minLength, maxLength, shortestColor, longestColor)
                                self.draw_line_between_tiles(tile, adj, (r, g, b), 210)
                                drawingFrontier.appendleft(adj)
                        # elif adj in pathways: # then check for closer path merge
                        #    otherPath = pathways[adj]
                        #    if otherPath.distance < pathway.distance:
                        #        self.draw_between_tiles(self.yellow_line, tile, adj)

    def draw_board_chokes(self, interChokeColor=None, innerChokeColor=None, outerChokeColor=None):
        if self._viewInfo.board_analysis is None:
            return

        if interChokeColor is None:
            interChokeColor = CHOKE_PURPLE

        if innerChokeColor is None:
            innerChokeColor = P_DARK_GREEN

        if outerChokeColor is None:
            outerChokeColor = P_TEAL

        if self._viewInfo.board_analysis.intergeneral_analysis is not None:
            self.draw_army_analysis(self._viewInfo.board_analysis.intergeneral_analysis,
                                    chokeColor=interChokeColor,
                                    draw_pathways=True)

        for tile in self._map.pathableTiles:
            if self._viewInfo.board_analysis.innerChokes[tile]:
                (r, g, b) = innerChokeColor
                self.draw_square(tile, 1, r, g, b, 255, self.square_inner_2)

            if self._viewInfo.board_analysis.outerChokes[tile]:
                (r, g, b) = outerChokeColor
                self.draw_square(tile, 1, r, g, b, 255, self.square_inner_3)

    def draw_division_borders(self):
        for (divisionMatrix, (r, g, b), alpha) in self._viewInfo._divisions:
            divisionLine = DirectionalShape(self.get_line(r, g, b, width=2), rotateInitial=90)

            def draw_border_func(tile):
                for move in tile.movable:
                    if move.isNotPathable:
                        continue

                    if (tile in divisionMatrix) != (move in divisionMatrix):
                        self.draw_between_tiles(divisionLine, tile, move, alpha=alpha)

            startTiles = [self._map.generals[self._map.player_index]]

            if (
                    self._viewInfo.board_analysis is not None
                    and self._viewInfo.board_analysis.intergeneral_analysis is not None
                    and self._viewInfo.board_analysis.intergeneral_analysis.shortestPathWay is not None
                    and len(self._viewInfo.board_analysis.intergeneral_analysis.shortestPathWay.tiles) > 0
            ):
                startTiles = self._viewInfo.board_analysis.intergeneral_analysis.shortestPathWay.tiles

            SearchUtils.breadth_first_foreach(self._map, startTiles, 1000, draw_border_func, noLog=True)

    def draw_path(self, tilePlanObj: TilePlanInterface, R, G, B, alphaStart, alphaDec, alphaMin):
        if tilePlanObj is None:
            return
        alpha = alphaStart
        key = WHITE
        color = (R, G, B)
        for move in tilePlanObj.get_move_list():
            if move:
                s = pygame.Surface((self.cellWidth, self.cellHeight))
                s.set_colorkey(key)
                # first, "erase" the surface by filling it with a color and
                # setting this color as colorkey, so the surface is empty
                s.fill(key)

                tile = move.source
                toTile = move.dest
                pygame.draw.polygon(s, color, self.Arrow)
                pygame.draw.polygon(s, BLACK, self.Arrow, 2)
                self.draw_between_tiles(DirectionalShape(s), tile, toTile, alpha)
            alpha -= alphaDec
            if alpha < alphaMin:
                alpha = alphaMin

    def get_delta_arrow(self):
        key = WHITE
        s = pygame.Surface((self.cellWidth, self.cellHeight))
        s.set_colorkey(key)
        # first, "erase" the surface by filling it with a color and
        # setting this color as colorkey, so the surface is empty
        s.fill(key)

        # after drawing the circle, we can set the
        # alpha value (transparency) of the surface
        triangle = [
            (5, 2 * self.cellHeight // 3 + 1),
            (self.cellWidth // 2, self.cellHeight // 3 - 3),
            (self.cellWidth - 5, 2 * self.cellHeight // 3 + 1)
        ]
        pygame.draw.polygon(s, GRAY_DARK, triangle)

        return s

    def drawGathers(self, nodes, shape, prunedShape, alpha=255, pruneAlpha=150):
        # pruneArrow = self.get_line_arrow(190, 30, 0)
        q = deque()
        for node in nodes:
            q.appendleft((node, True))
        while q:
            node, unpruned = q.pop()
            for child in node.children:
                q.appendleft((child, unpruned))
            for prunedChild in node.pruned:
                q.appendleft((prunedChild, False))

            if node.toTile is not None:
                if unpruned:
                    self.draw_between_tiles(shape, node.toTile, node.tile, alpha)
                else:
                    self.draw_between_tiles(prunedShape, node.toTile, node.tile, pruneAlpha)

    def draw_between_tiles(self, shape: DirectionalShape, sourceTile, destTile, alpha=255):
        xDiff = destTile.x - sourceTile.x
        yDiff = destTile.y - sourceTile.y
        pos_left = 0
        pos_top = 0
        s = None
        if xDiff > 0:
            pos_left = (CELL_MARGIN + self.cellWidth) * sourceTile.x + self.cellWidth // 2 + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * sourceTile.y + CELL_MARGIN
            s = shape.leftShape
        if xDiff < 0:
            pos_left = (CELL_MARGIN + self.cellWidth) * sourceTile.x - self.cellWidth // 2 + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * sourceTile.y + CELL_MARGIN
            s = shape.rightShape
        if yDiff > 0:
            pos_left = (CELL_MARGIN + self.cellWidth) * sourceTile.x + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * sourceTile.y + self.cellHeight // 2 + CELL_MARGIN
            s = shape.upShape
        if yDiff < 0:
            pos_left = (CELL_MARGIN + self.cellWidth) * sourceTile.x + CELL_MARGIN
            pos_top = (CELL_MARGIN + self.cellHeight) * sourceTile.y - self.cellHeight // 2 + CELL_MARGIN
            s = shape.downShape
        if s is None:
            logbook.error(f'tried drawing shape between {sourceTile} and {destTile} but they dont appear adjacent...?')
        else:
            s.set_alpha(alpha)
            self._screen.blit(s, (pos_left - 1, pos_top - 1))

    def getCenter(self, tile):
        left, top = self.getTopLeft(tile)
        return left + self.cellWidth / 2, top + self.cellHeight / 2

    def getTopLeft(self, tile):
        pos_left = (CELL_MARGIN + self.cellWidth) * tile.x + CELL_MARGIN
        pos_top = (CELL_MARGIN + self.cellHeight) * tile.y + CELL_MARGIN
        return pos_left, pos_top

    def get_font_color(self, tile) -> typing.Tuple[int, int, int]:
        color_font = WHITE
        if tile.visible and tile.player == -1 and not tile.isCity:
            color_font = BLACK
        elif tile.player >= 0 or tile.isNotPathable or not tile.discovered or (tile.isCity and tile.player == -1):
            color_font = WHITE
        elif tile.visible:
            color_font = BLACK
        return color_font

    def get_small_font_color(self, tile) -> typing.Tuple[int, int, int]:
        color_font = WHITE_PURPLE
        if tile.visible and tile.player == -1 and not tile.isCity:
            color_font = OFF_BLACK
        elif tile.player >= 0 or tile.isNotPathable or not tile.discovered or (tile.isCity and tile.player == -1):
            color_font = WHITE_PURPLE
        elif tile.visible:
            color_font = OFF_BLACK
        return color_font

    def get_tile_color(self, tile) -> typing.Tuple[int, int, int]:
        pColor = WHITE

        if tile.isMountain:  # Mountain
            pColor = BLACK
        elif tile.player >= 0:
            playercolor = PLAYER_COLORS[tile.player]
            colorR = playercolor[0]
            colorG = playercolor[1]
            colorB = playercolor[2]
            if tile.isCity or tile.isGeneral:
                colorR = colorR + KING_COLOR_OFFSET if colorR <= 255 - KING_COLOR_OFFSET else 255
                colorG = colorG + KING_COLOR_OFFSET if colorG <= 255 - KING_COLOR_OFFSET else 255
                colorB = colorB + KING_COLOR_OFFSET if colorB <= 255 - KING_COLOR_OFFSET else 255
            if not tile.visible:
                colorR = colorR // 2 + 40
                colorG = colorG // 2 + 40
                colorB = colorB // 2 + 40
                if not tile.discovered:
                    colorR = 2 * colorR // 5 + 30
                    colorG = 2 * colorG // 5 + 30
                    colorB = 2 * colorB // 5 + 30
            pColor = (colorR, colorG, colorB)
        elif tile.isNotPathable:  # Obstacle
            pColor = GRAY_DARK
        elif not tile.discovered:
            pColor = UNDISCOVERED_GRAY
        elif tile.player == -1 and tile.isCity:
            pColor = NEUT_CITY_GRAY
            if not tile.visible:
                colorR = pColor[0] // 2 + 40
                colorG = pColor[1] // 2 + 40
                colorB = pColor[2] // 2 + 40
                pColor = (colorR, colorB, colorG)
        elif tile.player == -1 and tile.army != 0:
            pColor = LIGHT_GRAY
            if not tile.visible:
                colorR = pColor[0] // 2 + 40
                colorG = pColor[1] // 2 + 40
                colorB = pColor[2] // 2 + 40
                if not tile.discovered:
                    colorR = 2 * pColor[0] // 5 + 30
                    colorG = 2 * pColor[1] // 5 + 30
                    colorB = 2 * pColor[2] // 5 + 30
                pColor = (colorR, colorB, colorG)
        elif not tile.visible:
            pColor = GRAY

        # adjust color by map divisions:
        for (divisionMatrix, (r, g, b), alpha) in self._viewInfo._zones:
            if tile in divisionMatrix:
                pColor = rescale_color(alpha, 0, 255, pColor, (r, g, b))

        return pColor

    def small_font(self, text_val: str, color_font: typing.Tuple[int, int, int]):
        return self._smallFont.render(text_val, True, color_font)

    def kill(self):
        self._killed = True

    def get_text_offset_from_right(self, text: str) -> int:
        return self.get_any_text_width(text, self._smallFontWidth) + 1

    def get_med_text_offset_from_right(self, text: str) -> int:
        return self.get_any_text_width(text, self._medFontWidth) + 2

    def get_large_text_offset_from_right(self, text: str) -> int:
        return self.get_any_text_width(text, self._lrgFontWidth) + 3

    def get_text_center_offset(self, text: str) -> int:
        return self.get_any_text_width(text, self._smallFontWidth) // 2

    def get_med_text_center_offset(self, text: str) -> int:
        return self.get_any_text_width(text, self._medFontWidth) // 2

    def get_large_text_center_offset(self, text: str) -> int:
        return self.get_any_text_width(text, self._lrgFontWidth) // 2

    def get_any_text_width(self, text: str, estFontWidthPx: float) -> int:
        return int(len(text) * estFontWidthPx)

    def save_image(self):
        try:
            pygame.image.save(self._screen, f"{self.logDirectory}\\{self._map.turn}.png")
        except:
            logbook.error(traceback.format_exc())

    def send_closed_event(self, killedByUserClose: bool):
        try:
            self._event_queue.put(('CLOSED', killedByUserClose))
        except EOFError:
            pass
        except BrokenPipeError:
            pass

    def draw_player_scores(self):
        pos_top = self._window_size[1] - self.infoRowHeight - self.scoreRowHeight
        # self._scores = sorted(update.scores, key=lambda general: general['total'], reverse=True)
        if self._map is None:
            return

        numAlive = 0
        numDead = 0
        for p in self._map.players:
            if p.dead:
                numDead += 1
            else:
                numAlive += 1

        # alive players get double the space of dead players.
        totalCapacity = numAlive * 2 + numDead

        alive_score_width = 2 * self._window_size[0] / totalCapacity
        dead_score_width = self._window_size[0] / totalCapacity

        # Sort Scores by score then by the turn they left the game if they are dead.

        statsSorted = []
        for team in self._viewInfo.team_cycle_stats.keys():
            statsSorted.append((self._map.get_team_stats_by_team_id(team), self._viewInfo.team_cycle_stats[team]))

        statsSorted = sorted(statsSorted, key=lambda s: (s[0].score, self._map.players[s[1].players[0]].leftGameTurn if s[1] is not None else False), reverse=True)

        pos_left = 0

        for teamScore, teamCycleData in statsSorted:
            if teamCycleData is None:
                continue
            players = []

            for p in teamCycleData.players:
                player = self._map.players[p]
                players.append(player)

            team_pos_left = pos_left

            players = sorted(players, key=lambda p: (p.score, p.leftGameTurn), reverse=True)
            for i, player in enumerate(players):
                if player is None:
                    continue

                score_color = PLAYER_COLORS[player.index]
                if player.leftGame:
                    # make them 70% black after leaving game
                    score_color = rescale_color(0.6, 0, 1.0, score_color, GRAY)

                curScoreWidth = alive_score_width
                if player.dead:
                    score_color = GRAY_DARK
                    curScoreWidth = dead_score_width

                pygame.draw.rect(self._screen, score_color, [pos_left, pos_top, curScoreWidth, self.scoreRowHeight])

                if player.fighting_with_player >= 0:
                    otherPlayerColor = PLAYER_COLORS[player.fighting_with_player]
                    desiredHeight = self.cellHeight // 5
                    pygame.draw.rect(self._screen, otherPlayerColor,[pos_left, pos_top + self.scoreRowHeight - desiredHeight, curScoreWidth, desiredHeight])

                if self._viewInfo.targetPlayer == player.index:
                    pygame.draw.rect(self._screen, GRAY,
                                     [pos_left, pos_top, curScoreWidth, self.scoreRowHeight], 1)
                userName = self._map.usernames[player.index]
                userString = f"({player.stars}) {userName}"
                try:
                    self._screen.blit(self._medFont.render(userString, True, WHITE),
                                      (pos_left + 3, pos_top + 1))
                except:
                    userString = f"({player.stars}) INVALID_NAME"
                    self._screen.blit(self._medFont.render(userString, True, WHITE),
                                      (pos_left + 3, pos_top + 1))

                playerSubtext = f"{player.score} {player.tileCount}t {player.cityCount}c ({player.tileCount + player.cityCount * 25})"
                if player.index != self._map.player_index and len(self._viewInfo.playerTargetScores) > 0:
                    playerSubtext += f"   {player.aggression_factor}a"
                if self._map.remainingPlayers > 2 and player.index != self._map.player_index and len(
                        self._viewInfo.playerTargetScores) > 0:
                    playerSubtext += f" {int(self._viewInfo.playerTargetScores[player.index])}ts"
                self._screen.blit(self._medFont.render(playerSubtext, True, WHITE),
                                  (pos_left + 3, pos_top + 1 + self._medFont.get_height()))

                if not self._map.is_player_on_team_with(player.index, self._map.player_index):
                    playerFogTiles = self._viewInfo.player_fog_tile_counts.get(player.index, None)
                    if playerFogTiles is not None:
                        playerFogSubtext = " | ".join([f'{n}x{tileSize}s'.ljust(5) for tileSize, n in sorted(playerFogTiles.items(), reverse=True)])
                        self._screen.blit(self._medFont.render(playerFogSubtext, True, WHITE),
                                          (pos_left + 3, pos_top + 2 + 2 * self._medFont.get_height()))

                playerSubSubtext = f"eΔ{player.expectedScoreDelta:+d}".ljust(8) + f"Δ{player.actualScoreDelta:+d}"
                self._screen.blit(self._medFont.render(playerSubSubtext, True, WHITE),
                                  (pos_left + 3, pos_top + 2 + 3 * self._medFont.get_height()))

                pos_left = pos_left + curScoreWidth

            for i, player in enumerate(players):
                if player is None:
                    continue

                if i == 0:
                    approxArmy = teamCycleData.approximate_fog_city_army + teamCycleData.approximate_fog_army_available_total
                    gathMoves = teamCycleData.moves_spent_gathering_fog_tiles + teamCycleData.moves_spent_gathering_visible_tiles
                    capMoves = teamCycleData.moves_spent_capturing_fog_tiles + teamCycleData.moves_spent_capturing_visible_tiles

                    # only draw team score data once
                    playerCycleSubtext = f"{str(approxArmy).ljust(3)}  g:{teamCycleData.approximate_army_gathered_this_cycle:3d}  Δt:{teamCycleData.tiles_gained:2d}  Δc:{teamCycleData.cities_gained:d}   a:{teamCycleData.approximate_fog_army_available_total:3d}/c:{teamCycleData.approximate_fog_city_army:2d}"
                    self._screen.blit(self._medFont.render(playerCycleSubtext, True, WHITE),
                                      (team_pos_left + 3, pos_top + 2 + 3.9 * self._medFont.get_height()))
                    playerCycleSubtext = f"MV: g{gathMoves}/c{capMoves}  fcap:{teamCycleData.moves_spent_capturing_fog_tiles:2d}  vcap:{teamCycleData.moves_spent_capturing_visible_tiles:2d}  fg:{teamCycleData.moves_spent_gathering_fog_tiles:2d}  vg:{teamCycleData.moves_spent_gathering_visible_tiles:2d}"
                    self._screen.blit(self._medFont.render(playerCycleSubtext, True, WHITE),
                                      (team_pos_left + 3, pos_top + 2 + 4.8 * self._medFont.get_height()))

                    teamLastCycleData = self._viewInfo.team_last_cycle_stats[teamCycleData.team]

                    if teamLastCycleData is not None:
                        approxArmy = teamLastCycleData.approximate_fog_city_army + teamLastCycleData.approximate_fog_army_available_total
                        gathMoves = teamLastCycleData.moves_spent_gathering_fog_tiles + teamLastCycleData.moves_spent_gathering_visible_tiles
                        capMoves = teamLastCycleData.moves_spent_capturing_fog_tiles + teamLastCycleData.moves_spent_capturing_visible_tiles
                        # only draw team score data once
                        playerCycleSubtext = f"LAST {str(approxArmy).ljust(3)}  g:{teamLastCycleData.approximate_army_gathered_this_cycle:3d}  Δt:{teamLastCycleData.tiles_gained:2d}  Δc:{teamLastCycleData.cities_gained:d}   a:{teamLastCycleData.approximate_fog_army_available_total:3d}/c:{teamLastCycleData.approximate_fog_city_army:2d}"
                        self._screen.blit(self._medFont.render(playerCycleSubtext, True, WHITE),
                                          (team_pos_left + 3, pos_top + 2 + 5.7 * self._medFont.get_height()))

                        playerCycleSubtext = f"LAST MV: g{gathMoves}/c{capMoves}  fcap:{teamLastCycleData.moves_spent_capturing_fog_tiles:2d}  vcap:{teamLastCycleData.moves_spent_capturing_visible_tiles:2d}  fg:{teamLastCycleData.moves_spent_gathering_fog_tiles:2d}  vg:{teamLastCycleData.moves_spent_gathering_visible_tiles:2d}"
                        self._screen.blit(self._medFont.render(playerCycleSubtext, True, WHITE),
                                          (team_pos_left + 3, pos_top + 2 + 6.6 * self._medFont.get_height()))



def rescale_color(
        valToScale,
        valueMin,
        valueMax,
        colorMin: typing.Tuple[int, int, int],
        colorMax: typing.Tuple[int, int, int]
) -> typing.Tuple[int, int, int]:
    rMin, gMin, bMin = colorMin
    rMax, gMax, bMax = colorMax

    r = int(rescale_value(valToScale, valueMin, valueMax, rMin, rMax))
    g = int(rescale_value(valToScale, valueMin, valueMax, gMin, gMax))
    b = int(rescale_value(valToScale, valueMin, valueMax, bMin, bMax))

    return r, g, b


def rescale_value(valToScale, valueMin, valueMax, newScaleMin, newScaleMax):
    # Figure out how 'wide' each range is
    leftSpan = valueMax - valueMin
    rightSpan = newScaleMax - newScaleMin

    if leftSpan == 0:
        leftSpan = 1

    # Convert the left range into a 0-1 range (float)
    valueScaled = float(valToScale - valueMin) / float(leftSpan)

    # Convert the 0-1 range into a value in the right range.
    return newScaleMin + (valueScaled * rightSpan)
