"""
    @ Harris Christiansen (Harris@HarrisChristiansen.com)
    January 2016
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Game Viewer
"""
import os
import queue
import sys
import time
import traceback
import typing
from multiprocessing import Queue

import pygame
from pygame import *

import BotLogging
import SearchUtils
from ArmyAnalyzer import *

from ViewInfo import TargetStyle, ViewInfo
from base.client.map import MapBase, Score, TILE_MOUNTAIN

MIN_WINDOW_WIDTH = 14

# Color Definitions
BLACK = (0, 0, 0)
GRAY_DARK = (52, 52, 52)
UNDISCOVERED_GRAY = (110, 110, 110)
NEUT_CITY_GRAY = (90, 90, 90)
GRAY = (160, 160, 160)
LIGHT_GRAY = (220, 220, 210)
WHITE = (255, 255, 255)
RED = (200, 40, 40)
ORANGE = (220, 110, 40)
LIGHT_BLUE = (4, 160, 200)
LIGHT_PINK = (170, 138, 141)
PURPLE = (190, 30, 210)
DARK_PURPLE = (140, 0, 180)
CHOKE_PURPLE = (93, 0, 111)

OFF_BLACK = (40, 40, 40)
WHITE_PURPLE = (255, 230, 240)

P_RED = (245, 65, 50)
P_BLUE = (30, 30, 230)
P_GREEN = (60, 160, 10)
P_PURPLE = (128, 30, 128)
P_TEAL = (30, 128, 128)
P_DARK_GREEN = (5, 75, 45)
P_DARK_RED = (100, 5, 35)
P_YELLOW = (160, 150, 20)
P_LIGHT_PURPLE = (190, 150, 230)

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
C{CycleInterval} Q{QuickExpandTurns} G{Gather/AttackSplitTurn} L{LaunchTiming} Off{Offset} ({CurrentCycleTurn})

black arrows 
    -> intended gather lines
red arrows 
    -> considered gather lines that were trimmed
green chevrons
    -> the AI's current army movement path (used when launching timing attacks or attacks against cities etc).
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
            pygame_event_queue: "Queue[bool]",
            name=None,
            cell_width: int | None = None,
            cell_height: int | None = None,
            no_log: bool = False,
    ):
        self._killed = False
        self._update_queue: "Queue[typing.Tuple[ViewInfo | None, MapBase | None, bool]]" = update_queue
        self._event_queue: "Queue[bool]" = pygame_event_queue
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

        self.plusDepth = 9
        self.offset1080Above1440p = 276  # 320 was too far right...?
        self.scoreRowHeight: int = 0
        self.square: Rect = None
        self.square_inner_1: Rect = None
        self.square_inner_2: Rect = None
        self.square_inner_3: Rect = None
        self.square_inner_4: Rect = None
        self.square_inner_5: Rect = None

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
        # pygame.draw.line(s, (r, g, b), ((CELL_MARGIN + self.cellWidth) // 2, 0), ((CELL_MARGIN + self.cellWidth) // 2, self.cellHeight + 1), width)
        pygame.draw.line(s, (r, g, b), (self.cellWidth // 2 + CELL_MARGIN, 0),
                         (self.cellWidth // 2 + CELL_MARGIN, self.cellHeight), width)
        return s

    def _initViewier(self, alignTop: bool, alignLeft: bool):
        self.infoLineHeight = 17
        self.infoRowHeight = 250

        if self.cellHeight is None:
            self.cellHeight = min(85, (1080 - self.infoRowHeight - self.scoreRowHeight) // (self._map.rows + 1))
            self.cellHeight = max(29, self.cellHeight)
            self.cellWidth = self.cellHeight

        self.scoreRowHeight = int((self.cellHeight + 2) * 1.5)

        self.tile_surface = pygame.Surface((self.cellWidth, self.cellHeight))
        self.player_fight_indicator_width = 2 * self.cellWidth

        x = 3 + self.offset1080Above1440p
        if not alignLeft:
            x = self.offset1080Above1440p + 1920 - 3 - (self.cellWidth + CELL_MARGIN) * self._map.cols

        y = 3 - 1080
        if not alignTop:
            y = 20 # bottom monitor

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
        window_width = max(MIN_WINDOW_WIDTH, self._map.cols) * (self.cellWidth + CELL_MARGIN) + CELL_MARGIN
        self._window_size = [window_width, window_height]
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
        # self.infoSpaceFromLeft = self.get_large_text_offset_from_right("Turn: 1000, (.50) ")
        samplePerfText = ".004 Rebuilding intergeneral_analysis "
        self.perfWidthCutoff = len(samplePerfText)
        self.infoSpaceFromLeft = self.get_any_text_width(samplePerfText, self.infoLineHeight / 2.27) + 1

        self._clock = pygame.time.Clock()

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

    def run_main_viewer_loop(self, alignTop=True, alignLeft=True):
        termSec = 600
        # if not self.noLog:
        #     BotLogging.set_up_logger(logging.INFO)
        while not self._receivedUpdate:  # Wait for first update
            try:
                viewInfo, map, isComplete = self._update_queue.get(block=True, timeout=15.0)
                if viewInfo is not None:
                    self._receivedUpdate = True
                    self.updateGrid(viewInfo, map)
                else:
                    self.last_update_received = time.perf_counter()
            except queue.Empty:
                elapsed = time.perf_counter() - self.last_update_received
                if not self.noLog:
                    logging.info(f'waiting for update...... {elapsed:.3f} / {termSec} sec')
                # TODO add a server ping callback here so while we're waiting in a lobby for a while we can keep the viewer thread alive
                if elapsed > termSec:
                    logging.info(f'GeneralsViewer zombied with no game start, self-terminating after {termSec} seconds')
                    time.sleep(1.0)
                    self.send_killed_event()
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

        while not done:
            if self._killed:
                done = True  # Flag done
                self._map.complete = True
                break

            try:
                if not self.noLog:
                    logging.info("GeneralsViewer waiting for queue event:")
                viewInfo, map, isComplete = self._update_queue.get(block=True, timeout=1.0)
                self.last_update_received = time.perf_counter()
                if isComplete:
                    logging.info("GeneralsViewer received done event!")
                    done = True

                if not self.noLog:
                    logging.info("GeneralsViewer received an event! Updating grid")

                self.updateGrid(viewInfo, map)

                start = time.perf_counter()
                if not self.noLog:
                    logging.info("GeneralsViewer drawing grid:")
                self._drawGrid()
                if not self.noLog:
                    logging.info(f"GeneralsViewer drawing grid took {time.perf_counter() - start:.3f}")

                if not self.noLog:
                    start = time.perf_counter()
                    logging.info("GeneralsViewer saving image:")
                    self.save_image()
                    logging.info(f"GeneralsViewer saving image took {time.perf_counter() - start:.3f}")
            except queue.Empty:
                elapsed = time.perf_counter() - self.last_update_received
                if not self.noLog:
                    logging.info(f'No GeneralsViewer update received in {elapsed:.2f} seconds')
                if elapsed > 180.0:
                    logging.info(f'GeneralsViewer zombied, self-terminating after 10 seconds')
                    done = True
                    self.send_killed_event()
                pass
            except BrokenPipeError:
                logging.info('GeneralsViewer pipe died')
                done = True
                break

            for event in pygame.event.get():  # User did something
                if event.type == pygame.QUIT:  # User clicked quit
                    done = True  # Flag done
                    logging.info('GeneralsViewer pygame exited by user, setting done and exiting')
                    closedByUser = True
                    break

                elif event.type == pygame.MOUSEBUTTONDOWN:  # Mouse Click
                    pos = pygame.mouse.get_pos()

                    # Convert screen to grid coordinates
                    column = pos[0] // (self.cellWidth + CELL_MARGIN)
                    row = pos[1] // (self.cellHeight + CELL_MARGIN)

                    print("Click ", pos, "Grid coordinates: ", row, column)

        logging.info(f'Pygame closed in GeneralsViewer, sending closedByUser {closedByUser} back to main threads')
        self.send_closed_event(closedByUser)
        logging.info('GeneralsViewer, exiting pygame w/ pygame.quit() in 1 second:')
        time.sleep(1.0)
        pygame.quit()  # Done.  Quit pygame.

    def _drawGrid(self):
        try:
            self._screen.fill(BLACK)  # Set BG Color
            self._transparent.fill((0, 0, 0, 0))  # transparent
            allInText = " "
            if self._viewInfo.allIn:
                allInText = "+"

            # Draw Bottom Info Text
            self._screen.blit(self._lrgFont.render(
                f"Turn: {self._map.turn}, ({('%.2f' % self._viewInfo.lastMoveDuration).lstrip('0')})",
                True, WHITE), (10, self._window_size[1] - self.infoRowHeight + 4))
            curInfoTextHeight = 0
            self._screen.blit(self._infoFont.render(self._viewInfo.infoText, True, WHITE),
                              (self.infoSpaceFromLeft, self._window_size[1] - self.infoRowHeight))
            curInfoTextHeight += self.infoLineHeight
            if self._viewInfo.timings:
                timings = self._viewInfo.timings
                timingTurn = (self._map.turn + timings.offsetTurns) % timings.cycleTurns
                timingsText = f"{str(timings)} ({timingTurn}) - {allInText}{self._viewInfo.allInCounter}  {self._viewInfo.addlTimingsLineText}"
                self._screen.blit(
                    self._infoFont.render(
                        timingsText,
                        True,
                        WHITE),
                    (self.infoSpaceFromLeft, self._window_size[1] - self.infoRowHeight + curInfoTextHeight))
                curInfoTextHeight += self.infoLineHeight

            for addlInfo in self._viewInfo.addlInfoLines:
                if addlInfo == self._viewInfo.infoText:
                    continue
                self._screen.blit(
                    self._infoFont.render(
                        addlInfo,
                        True,
                        WHITE),
                    (self.infoSpaceFromLeft, self._window_size[1] - self.infoRowHeight + curInfoTextHeight))
                curInfoTextHeight += self.infoLineHeight

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
                        tileTerritoryPlayer = self._viewInfo.territories.territoryMap[tile.x][tile.y]
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
                self.drawGathers(self._viewInfo.redGatherNodes, self.redLineArrow, self.redLineArrow)
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

            # s(self._map.grid[1][1],

            while len(self._viewInfo.paths) > 0:
                pColorer = self._viewInfo.paths.pop()
                self.draw_path(pColorer.path, pColorer.color[0], pColorer.color[1], pColorer.color[2], pColorer.alpha,
                               pColorer.alphaDecreaseRate, pColorer.alphaMinimum)

            alpha = 250
            alphaDec = 4
            alphaMin = 135
            path = None
            if self._viewInfo.currentPath is not None:
                path = self._viewInfo.currentPath
            self.draw_path(path, 0, 200, 50, alpha, alphaDec, alphaMin)

            if self._viewInfo.dangerAnalyzer is not None and self._viewInfo.dangerAnalyzer.anyThreat:

                for threat in [self._viewInfo.dangerAnalyzer.fastestVisionThreat, self._viewInfo.dangerAnalyzer.fastestThreat,
                               self._viewInfo.dangerAnalyzer.highestThreat]:
                    if threat is None:
                        continue
                    # Draw danger path
                    alpha = 200
                    alphaDec = 6
                    alphaMin = 145
                    self.draw_path(threat.path, 150, 0, 0, alpha, alphaDec, alphaMin)

            for (tile, targetStyle) in self._viewInfo.targetedTiles:
                if tile is None:
                    continue
                pos_left = (CELL_MARGIN + self.cellWidth) * tile.x + CELL_MARGIN
                pos_top = (CELL_MARGIN + self.cellHeight) * tile.y + CELL_MARGIN
                pos_left_circle = int(pos_left + (self.cellWidth / 2))
                pos_top_circle = int(pos_top + (self.cellHeight / 2))
                targetColor = self.get_color_from_target_style(targetStyle)
                pygame.draw.circle(self._screen, BLACK, [pos_left_circle, pos_top_circle], int(self.cellWidth / 2 - 2),
                                   7)
                pygame.draw.circle(self._screen, targetColor, [pos_left_circle, pos_top_circle],
                                   int(self.cellWidth / 2) - 5, 1)
            for i, approx in enumerate(self._viewInfo.generalApproximations):
                if approx[2] > 0:
                    pColor = PLAYER_COLORS[i]
                    pos_left = (CELL_MARGIN + self.cellWidth) * approx[0] + CELL_MARGIN
                    pos_top = (CELL_MARGIN + self.cellHeight) * approx[1] + CELL_MARGIN
                    pos_left_circle = int(pos_left + (self.cellWidth / 2))
                    pos_top_circle = int(pos_top + (self.cellHeight / 2))
                    pygame.draw.circle(self._screen, BLACK, [pos_left_circle, pos_top_circle],
                                       int(self.cellWidth / 2 - 2),
                                       7)
                    pygame.draw.circle(self._screen, pColor, [pos_left_circle, pos_top_circle],
                                       int(self.cellWidth / 2) - 5, 1)
            s = pygame.Surface((self.cellWidth, self.cellHeight))
            s.fill(WHITE)
            s.set_colorkey(WHITE)

            pygame.draw.circle(s, BLACK, [int(self.cellWidth / 2), int(self.cellHeight / 2)],
                               int(self.cellWidth / 2 - 2), 7)

            s = pygame.Surface((self.cellWidth, self.cellHeight))
            s.fill(WHITE)
            s.set_colorkey(WHITE)
            pygame.draw.line(s, BLACK, (0, 0), (self.cellWidth, self.cellHeight), 4)
            pygame.draw.line(s, RED, (0, 0), (self.cellWidth, self.cellHeight), 2)
            pygame.draw.line(s, BLACK, (0, self.cellHeight), (self.cellWidth, 0), 4)
            pygame.draw.line(s, RED, (0, self.cellHeight), (self.cellWidth, 0), 2)
            if (self._map is not None and self._viewInfo is not None and self._viewInfo.evaluatedGrid is not None and len(
                    self._viewInfo.evaluatedGrid) > 0):
                for row in range(self._map.rows):
                    for column in range(self._map.cols):
                        countEvaluated = int(self._viewInfo.evaluatedGrid[column][row])
                        if countEvaluated > 0:
                            pos_left = (CELL_MARGIN + self.cellWidth) * column + CELL_MARGIN
                            pos_top = (CELL_MARGIN + self.cellHeight) * row + CELL_MARGIN
                            alpha = int(75 + countEvaluated * 3)
                            s.set_alpha(alpha if alpha < 255 else 255)
                            self._screen.blit(s, (pos_left, pos_top))
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
                        text = self._viewInfo.topRightGridText[column][row]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + self.cellWidth - self.get_text_offset_from_right(textVal),
                                               pos_top - 2))

                    if self._viewInfo.midRightGridText is not None:
                        text = self._viewInfo.midRightGridText[column][row]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + self.cellWidth - self.get_text_offset_from_right(textVal),
                                               pos_top + self.cellHeight / 3))

                    if self._viewInfo.bottomMidRightGridText is not None:
                        text = self._viewInfo.bottomMidRightGridText[column][row]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + self.cellWidth - self.get_text_offset_from_right(textVal),
                                               pos_top + 1.6 * self.cellHeight / 3))

                    if self._viewInfo.bottomRightGridText is not None:
                        text = self._viewInfo.bottomRightGridText[column][row]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + self.cellWidth - self.get_text_offset_from_right(textVal),
                                               pos_top + 2.2 * self.cellHeight / 3))

                    if self._viewInfo.bottomLeftGridText is not None:
                        text = self._viewInfo.bottomLeftGridText[column][row]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + 2, pos_top + 2.2 * self.cellHeight / 3))

                    if self._viewInfo.bottomMidLeftGridText is not None:
                        text = self._viewInfo.bottomMidLeftGridText[column][row]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + 2, pos_top + 1.6 * self.cellHeight / 3))

                    if self._viewInfo.midLeftGridText is not None:
                        text = self._viewInfo.midLeftGridText[column][row]
                        if text is not None:
                            textVal = clean_up_possible_float(text)
                            if text == -1000000:  # then was skipped
                                textVal = "x"
                            self._screen.blit(self.small_font(textVal, color_small_font),
                                              (pos_left + 2, pos_top + self.cellHeight / 3))

            self.draw_armies()

            self.draw_emergences()

            # Go ahead and update the screen with what we've drawn.
            pygame.display.flip()

            # Limit to 60 frames per second
            self._clock.tick(15)
        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
            # logging.info("inf")  # Log it or whatever here
            # logging.info(''.join('!! ' + line for line in lines))  # Log it or whatever here
            # logging.info("warn")  # Log it or whatever here
            # logging.warning(''.join('!! ' + line for line in lines))  # Log it or whatever here
            logging.info("err")  # Log it or whatever here
            logging.error(''.join('!! ' + line for line in lines))  # Log it or whatever here
            raise

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
        (playerR, playerG, playerB) = WHITE
        if army.player != army.tile.player:
            (playerR, playerG, playerB) = PLAYER_COLORS[army.player]
            playerR += 50
            playerG += 50
            playerB += 50
        # playerR = (playerR + 256) // 2
        # playerG = (playerG + 256) // 2
        # playerB = (playerB + 256) // 2
        self.draw_square(tile, 1, playerR, playerG, playerB, min(255, int(alphaStart * 1.3)))

        # self.draw_path(army.path, R, G, B, alphaStart, 0, 0)

        if army.expectedPath is not None:
            self.draw_path(army.expectedPath, 255, 0, 0, 150, 10, 100)

        pos_left = (CELL_MARGIN + self.cellWidth) * tile.x + CELL_MARGIN
        pos_top = (CELL_MARGIN + self.cellHeight) * tile.y + CELL_MARGIN
        self._screen.blit(self._medFont.render(army.name, True, WHITE), (pos_left + self.cellWidth - 10, pos_top))

    def draw_armies(self):
        if self._viewInfo.armyTracker is not None:
            for army in list(self._viewInfo.armyTracker.armies.values()):
                if army.scrapped:
                    self.draw_army(army, 200, 200, 200, 80)
                else:
                    self.draw_army(army, 255, 255, 255, 150)

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

    def draw_army_analysis(self, analysis: ArmyAnalyzer, chokeColor=None, draw_pathways=True, outerChokeColor=None,
                           innerChokeColor=None):
        if chokeColor:
            for choke in analysis.pathChokes:
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
        minLength = INF
        maxLength = 0 - INF
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
                logging.info('WTF, pathway seed tile was none...?')
                continue
            while len(drawingFrontier) != 0:
                tile = drawingFrontier.pop()
                tile = self._map.GetTile(tile.x, tile.y)
                if tile is None:
                    logging.info('WTF, none tile in pathway draw frontier??')
                    continue
                if tile not in drawnFrom:
                    drawnFrom.add(tile)
                    for adj in tile.movable:
                        if adj is None:
                            logging.info(f'WTF, moveable tile was none in tile {str(tile)}...?')
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
            if self._viewInfo.board_analysis.innerChokes[tile.x][tile.y]:
                (r, g, b) = innerChokeColor
                self.draw_square(tile, 1, r, g, b, 255, self.square_inner_2)

            if self._viewInfo.board_analysis.outerChokes[tile.x][tile.y]:
                (r, g, b) = outerChokeColor
                self.draw_square(tile, 1, r, g, b, 255, self.square_inner_3)

    def draw_division_borders(self):
        for (divisionMatrix, (r, g, b), alpha) in self._viewInfo._divisions:
            divisionLine = DirectionalShape(self.get_line(r, g, b, width=2), rotateInitial=90)

            def draw_border_func(tile):
                for move in tile.movable:
                    if move.isMountain or move.isNotPathable:
                        continue

                    if divisionMatrix[tile] != divisionMatrix[move]:
                        self.draw_between_tiles(divisionLine, tile, move, alpha=alpha)
            if len(self._viewInfo.board_analysis.intergeneral_analysis.shortestPathWay.tiles) > 0:
                startTiles = [t for t in self._viewInfo.board_analysis.intergeneral_analysis.shortestPathWay.tiles]
                SearchUtils.breadth_first_foreach(self._map, startTiles, 1000, draw_border_func, noLog=True)

    def draw_path(self, pathObject, R, G, B, alphaStart, alphaDec, alphaMin):
        if pathObject is None:
            return
        path = pathObject.start
        alpha = alphaStart
        key = WHITE
        color = (R, G, B)
        while path is not None and path.next is not None:
            try:
                s = pygame.Surface((self.cellWidth, self.cellHeight))
                s.set_colorkey(key)
                # first, "erase" the surface by filling it with a color and
                # setting this color as colorkey, so the surface is empty
                s.fill(key)

                tile = path.tile
                toTile = path.next.tile
                pygame.draw.polygon(s, color, self.Arrow)
                pygame.draw.polygon(s, BLACK, self.Arrow, 2)
                self.draw_between_tiles(DirectionalShape(s), tile, toTile, alpha)

                path = path.next
                alpha -= alphaDec
                if alpha < alphaMin:
                    alpha = alphaMin
            except:
                logging.error(f'wtf, couldnt draw path {str(path)}')
                path = path.next

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

    def drawGathers(self, nodes, shape, prunedShape):
        # pruneArrow = self.get_line_arrow(190, 30, 0)
        q = deque()
        for node in nodes:
            q.appendleft((node, True))
        while len(q) > 0:
            node, unpruned = q.pop()
            for child in node.children:
                q.appendleft((child, unpruned))
            for prunedChild in node.pruned:
                q.appendleft((prunedChild, False))

            if node.fromTile is not None:
                if unpruned:
                    self.draw_between_tiles(shape, node.fromTile, node.tile)
                else:
                    self.draw_between_tiles(prunedShape, node.fromTile, node.tile)

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
                    colorR = colorR // 3 + 50
                    colorG = colorG // 3 + 50
                    colorB = colorB // 3 + 50
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
                colorR = pColor[0] // 2 + 50
                colorG = pColor[1] // 2 + 50
                colorB = pColor[2] // 2 + 50
                pColor = (colorR, colorB, colorG)
        elif not tile.visible:
            pColor = GRAY

        # adjust color by map divisions:
        for (divisionMatrix, (r, g, b), alpha) in self._viewInfo._zones:
            if tile in divisionMatrix:
                pColor = rescale_color(alpha, 0, 255, pColor, (r, g, b))

        return pColor

    def get_color_from_target_style(self, targetStyle: TargetStyle) -> typing.Tuple[int, int, int]:
        if targetStyle == TargetStyle.RED:
            return RED
        if targetStyle == TargetStyle.BLUE:
            return 50, 50, 255
        if targetStyle == TargetStyle.GOLD:
            return 255, 215, 0
        if targetStyle == TargetStyle.GREEN:
            return P_GREEN
        if targetStyle == TargetStyle.PURPLE:
            return P_PURPLE
        return GRAY

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
        pygame.image.save(self._screen, f"{self.logDirectory}\\{self._map.turn}.png")

    def send_killed_event(self):
        self.send_closed_event(killedByUserClose=False)

    def send_closed_event(self, killedByUserClose: bool):
        self._event_queue.put(killedByUserClose)

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
        playersByScore = sorted(self._map.players, key=lambda player: (player.score, player.leftGameTurn), reverse=True)

        pos_left = 0

        for i, player in enumerate(playersByScore):
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

            playerSubSubtext = f"{player.expectedScoreDelta:+4d}ed {player.actualScoreDelta:+4d}a - {player.delta25score:+4d}dc {player.delta25tiles:+4d}tc"
            self._screen.blit(self._medFont.render(playerSubSubtext, True, WHITE),
                              (pos_left + 3, pos_top + 2 + 2 * self._medFont.get_height()))

            pos_left = pos_left + curScoreWidth



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
