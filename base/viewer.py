'''
	@ Harris Christiansen (Harris@HarrisChristiansen.com)
	January 2016
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	Game Viewer
'''
import os
import typing

import pygame
from pygame import *
import threading
import time
import logging
from collections import deque 
from ArmyAnalyzer import * 
from copy import deepcopy

from ViewInfo import TargetStyle
from base.client.generals import _spawn
from base.client.map import MapBase, Score

# Color Definitions
BLACK = (0,0,0)
GRAY_DARK = (52,52,52)
UNDISCOVERED_GRAY = (110,110,110)
GRAY = (160,160,160)
WHITE = (255,255,255)
RED = (200,40,40)
PURPLE = (190,30,210)
DARK_PURPLE = (140,0,180)
CHOKE_PURPLE = (93, 0, 111)

P_RED = (245,65,50)
P_BLUE = (30,30,230)
P_GREEN = (60,160,10)
P_PURPLE = (128,30,128)
P_TEAL = (30,128,128)
P_DARK_GREEN = (5,75,45)
P_DARK_RED = (100,5,35)
P_YELLOW = (170,140,20)
P_BRIGHT_GREEN = (10,20,10)


#P_BRIGHT_GREEN = (10,225,90)
PLAYER_COLORS = [P_RED, P_BLUE, P_GREEN, P_PURPLE, P_TEAL, P_DARK_GREEN, P_YELLOW, P_DARK_RED, P_BRIGHT_GREEN]
FOG_COLOR_OFFSET = 25
KING_COLOR_OFFSET = 35

UP_ARROW = "^"
DOWN_ARROW = "v"
LEFT_ARROW = "<"
RIGHT_ARROW = ">"

# Table Properies
CELL_WIDTH = 35
CELL_HEIGHT = 35
CELL_MARGIN = 1
SCORES_ROW_HEIGHT = CELL_HEIGHT + 3

INFO_ROW_HEIGHT = 170
INFO_LINE_HEIGHT = 17
INFO_SPACING_FROM_LEFT = 180

PLUS_DEPTH = 9
OFFSET_1080_ABOVE_1440p_MONITOR = 276  # 320 was too far right...?
SQUARE = Rect(0, 0, CELL_WIDTH, CELL_HEIGHT)
SQUARE_INNER_1 = Rect(1, 1, CELL_WIDTH - 2, CELL_HEIGHT - 2)
SQUARE_INNER_2 = Rect(2, 2, CELL_WIDTH - 4, CELL_HEIGHT - 4)
SQUARE_INNER_3 = Rect(3, 3, CELL_WIDTH - 6, CELL_HEIGHT - 6)
SQUARE_INNER_4 = Rect(4, 4, CELL_WIDTH - 8, CELL_HEIGHT - 8)
SQUARE_INNER_5 = Rect(5, 5, CELL_WIDTH - 10, CELL_HEIGHT - 10)

FORCE_NO_UI = True

"""
LEGEND
Player information card readout:
{Name} ([Stars])
{Army} on {TileCount} ({CityCount}) [{TargetPriority*}]

	*Target Priority is used to select which player to consider the current main opponent during an FFA
	
Information area:
Top line
	-> The THING the bot is currently doing, basically the evaluation that led to a move selection.
Timings: C {CycleInterval} Q {QuickExpandTurns} G {Gather/AttackSplitTurn} L {LaunchTiming} Off {Offset} ({CurrentCycleTurn})

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
	def __init__(self, downShape):
		self.downShape = downShape		
		self.leftShape = pygame.transform.rotate(downShape, -90)
		self.rightShape = pygame.transform.rotate(downShape, 90)
		self.upShape = pygame.transform.rotate(downShape, 180)

class GeneralsViewer(object):
	def __init__(self, name=None, ekBot=None):
		self._scores: typing.List[Score] = []
		self._bottomText = None
		self._map: MapBase = None
		self._name = name
		self._receivedUpdate = False
		self._readyRender = False
		self.Arrow = None
		self.lineArrow = None
		self.line = None
		self.ekBot = ekBot
		

	def updateGrid(self, update: MapBase, bottomText: str = None):
		updateDir = dir(update)
		self._map = update

		if bottomText is not None:
			self._bottomText = bottomText

		self._scores = sorted(update.scores, key=lambda score: score.total, reverse=True) # Sort Scores
		
		self._receivedUpdate = True

	def get_line_arrow(self, r, g, b, width = 3):
		s = pygame.Surface((CELL_WIDTH + 2*CELL_MARGIN, CELL_HEIGHT + 2*CELL_MARGIN))
		# first, "erase" the surface by filling it with a color and
		# setting this color as colorkey, so the surface is empty
		s.fill(WHITE)
		s.set_colorkey(WHITE)
		pygame.draw.line(s, (r, g, b), ((CELL_WIDTH) // 2 + CELL_MARGIN, 0), ((CELL_WIDTH) // 2 + CELL_MARGIN, CELL_HEIGHT), width)
		pygame.draw.line(s, (r, g, b), ((CELL_WIDTH) // 2 + CELL_MARGIN, CELL_HEIGHT), (CELL_WIDTH * 2.5 / 8 + CELL_MARGIN, CELL_HEIGHT * 5 / 8), width)
		pygame.draw.line(s, (r, g, b), ((CELL_WIDTH) // 2 + CELL_MARGIN, CELL_HEIGHT), (CELL_WIDTH * 5.5 / 8 + CELL_MARGIN, CELL_HEIGHT * 5 / 8), width)
		return s

	def get_line(self, r, g, b, width = 1):
		s = pygame.Surface((CELL_WIDTH + 2*CELL_MARGIN, CELL_HEIGHT + 2*CELL_MARGIN))
		# first, "erase" the surface by filling it with a color and
		# setting this color as colorkey, so the surface is empty
		s.fill(WHITE)
		s.set_colorkey(WHITE)		
		#pygame.draw.line(s, (r, g, b), ((CELL_MARGIN + CELL_WIDTH) // 2, 0), ((CELL_MARGIN + CELL_WIDTH) // 2, CELL_HEIGHT + 1), width)
		pygame.draw.line(s, (r, g, b), ((CELL_WIDTH) // 2 + CELL_MARGIN, 0), ((CELL_WIDTH) // 2 + CELL_MARGIN, CELL_HEIGHT), width)
		return s


	def _initViewier(self, position):
		os.environ['SDL_VIDEO_WINDOW_POS'] = "%d,%d" % position
		os.environ['SDL_VIDEO_ALLOW_SCREENSAVER'] = "1"
		os.environ['SDL_HINT_VIDEO_ALLOW_SCREENSAVER'] = "1"
		pygame.init()

		# Set Window Size
		window_height = self._map.rows * (CELL_HEIGHT + CELL_MARGIN) + CELL_MARGIN + SCORES_ROW_HEIGHT + INFO_ROW_HEIGHT
		window_width = self._map.cols * (CELL_WIDTH + CELL_MARGIN) + CELL_MARGIN
		self._window_size = [window_width, window_height]
		self._screen = pygame.display.set_mode(self._window_size)
		self._transparent = pygame.Surface(self._window_size, pygame.SRCALPHA)

		window_title = str(self._name)
		pygame.display.set_caption(window_title)
		self._font = pygame.font.SysFont('Arial', int(CELL_HEIGHT // 2) - 2)
		self._fontSmall = pygame.font.SysFont('Arial', min(9, int(CELL_HEIGHT // 3)))
		self._fontLrg = pygame.font.SysFont('Arial', CELL_HEIGHT - 7) 
		self._bottomText = ""

		self._clock = pygame.time.Clock()
		
		self.pathAlphas = []
		self.Arrow = [(CELL_WIDTH / 2, 0), (CELL_WIDTH / 8, CELL_HEIGHT / 2), (CELL_WIDTH / 2, CELL_HEIGHT / 4), (7 * CELL_WIDTH / 8, CELL_HEIGHT / 2)]
		# self.Arrow = [(CELL_WIDTH / 2, 0), (CELL_WIDTH / 8, CELL_HEIGHT / 2), (CELL_WIDTH / 2, CELL_HEIGHT / 4), (7 * CELL_WIDTH / 8, CELL_HEIGHT / 2)]
		
		self.lineArrow = DirectionalShape(self.get_line_arrow(0,0,0))
		self.line = DirectionalShape(self.get_line(0,0,0))
		self.green_line = DirectionalShape(self.get_line(0, 185, 35))
		self.yellow_line = DirectionalShape(self.get_line(185, 181, 35))
		self.red_line = DirectionalShape(self.get_line(225, 15, 15))
		self.repId = self._map.replay_url.split("/").pop()
		fileSafeUserName = self._map.usernames[self._map.player_index]
		fileSafeUserName = fileSafeUserName.replace("[Bot] ", "")
		fileSafeUserName = fileSafeUserName.replace("[Bot]", "")
		#logging.info("\n\n\nFILE SAFE USERNAME\n {}\n\n".format(fileSafeUserName))
		self.logDirectory = "D:\\GeneralsLogs\\{}-{}".format(fileSafeUserName, self.repId)
		if not os.path.exists(self.logDirectory):
			try:
				os.makedirs(self.logDirectory)
			except:
				logging.info("Couldn't create dir")
		_spawn(self.save_images)

	def main_viewer_loop(self, alignTop = True, alignLeft = True):
		while not self._receivedUpdate:  # Wait for first update
			logging.info("viewer waiting for first update...")
			time.sleep(0.2)

		x = 3 + OFFSET_1080_ABOVE_1440p_MONITOR
		if not alignLeft:
			x = OFFSET_1080_ABOVE_1440p_MONITOR + 1920 - 3 - (CELL_WIDTH + CELL_MARGIN) * self._map.cols

		y = 3 - 1080
		if not alignTop:
			y = 3 - (CELL_HEIGHT + CELL_MARGIN) * self._map.rows - 1080

		self._initViewier((x, y))

		done = False
		while not done:
			if self.ekBot.viewInfo and self.ekBot.viewInfo.readyToDraw:
				self.ekBot.viewInfo.readyToDraw = False
				self._drawGrid()
				self._readyRender = True
			for event in pygame.event.get(): # User did something
				if event.type == pygame.QUIT: # User clicked quit
					done = True # Flag done
				elif event.type == pygame.MOUSEBUTTONDOWN: # Mouse Click
					pos = pygame.mouse.get_pos()
					
					# Convert screen to grid coordinates
					column = pos[0] // (CELL_WIDTH + CELL_MARGIN)
					row = pos[1] // (CELL_HEIGHT + CELL_MARGIN)
					
					print("Click ", pos, "Grid coordinates: ", row, column)

			time.sleep(0.05)
		time.sleep(2.0)
		pygame.quit() # Done.  Quit pygame.

	def _drawGrid(self):
		try:
			self._screen.fill(BLACK) # Set BG Color
			self._transparent.fill((0,0,0,0)) # transparent
			allInText = " "
			if self.ekBot.allIn:
				allInText = "+"

			# Draw Bottom Info Text
			self._screen.blit(self._fontLrg.render("Turn: {}, ({})".format(self._map.turn, ("%.2f" % self.ekBot.viewInfo.lastMoveDuration).lstrip('0')), True, WHITE), (10, self._window_size[1] - INFO_ROW_HEIGHT + 4))
			curInfoTextHeight = 0
			self._screen.blit(self._font.render(self.ekBot.viewInfo.infoText, True, WHITE), (INFO_SPACING_FROM_LEFT, self._window_size[1] - INFO_ROW_HEIGHT))
			curInfoTextHeight += INFO_LINE_HEIGHT
			if self.ekBot.timings:
				timings = self.ekBot.timings
				timingTurn = (self._map.turn + timings.offsetTurns) % timings.cycleTurns
				self._screen.blit(
					self._font.render(
						"Timings: {} ({})   - {}{}       {}".format(
							timings.toString(), timingTurn, allInText, self.ekBot.all_in_counter, self.ekBot.viewInfo.addlTimingsLineText),
						True,
						WHITE),
					(INFO_SPACING_FROM_LEFT, self._window_size[1] - INFO_ROW_HEIGHT + curInfoTextHeight))
				curInfoTextHeight += INFO_LINE_HEIGHT

			for addlInfo in self.ekBot.viewInfo.addlInfoLines:
				self._screen.blit(
					self._font.render(
						addlInfo,
						True,
						WHITE),
					(INFO_SPACING_FROM_LEFT, self._window_size[1] - INFO_ROW_HEIGHT + curInfoTextHeight))
				curInfoTextHeight += INFO_LINE_HEIGHT


			# Draw Scores
			pos_top = self._window_size[1] - INFO_ROW_HEIGHT - SCORES_ROW_HEIGHT
			score_width = self._window_size[0] / len(self._map.players)
			#self._scores = sorted(update.scores, key=lambda general: general['total'], reverse=True)
			if (self._map != None):				
				playersByScore = sorted(self._map.players, key=lambda player: player.score, reverse=True) # Sort Scores
				
				for i, player in enumerate(playersByScore):
					if player != None:
						score_color = PLAYER_COLORS[player.index]
						if (player.leftGame):
							score_color = BLACK
						if (player.dead):
							score_color = GRAY_DARK
						pygame.draw.rect(self._screen, score_color, [score_width * i, pos_top, score_width, SCORES_ROW_HEIGHT])
						if (self.ekBot.targetPlayer == player.index):
							pygame.draw.rect(self._screen, GRAY, [score_width * i, pos_top, score_width, SCORES_ROW_HEIGHT], 1)
						userName = self._map.usernames[player.index]
						userString = "{} ({})".format(userName, player.stars)
						try:
							self._screen.blit(self._font.render(userString, True, WHITE), (score_width * i + 3, pos_top + 1))
						except:
							userString = "{} ({})".format("INVALID_NAME", player.stars)
							self._screen.blit(self._font.render(userString, True, WHITE), (score_width * i + 3, pos_top + 1))
							

						playerSubtext = "{} on {} ({})".format(player.score, player.tileCount, player.cityCount)
						if player.index != self._map.player_index:
							playerSubtext += " [{}]".format(str(int(self.ekBot.playerTargetScores[player.index])))
						self._screen.blit(self._font.render(playerSubtext, True, WHITE), (score_width * i + 3, pos_top + 1 + self._font.get_height()))
			#for i, score in enumerate(self._scores):
			#	score_color = PLAYER_COLORS[int(score['i'])]
			#	if (score['dead'] == True):
			#		score_color = GRAY_DARK
			#	pygame.draw.rect(self._screen, score_color, [score_width * i, pos_top, score_width, SCORES_ROW_HEIGHT])
			#	userString = self._map.usernames[int(score['i'])]
			#	if (self._map.stars): 
			#		userString = userString + " (" + str(self._map.stars[int(score['i'])]) + ")"
			#	self._screen.blit(self._font.render(userString, True, WHITE), (score_width * i + 3, pos_top + 1))
			#	self._screen.blit(self._font.render(str(score['total']) + " on " + str(score['tiles']), True, WHITE), (score_width * i + 3, pos_top + 1 + self._font.get_height()))
		
			# Draw Grid
			#print("drawing grid")
			for row in range(self._map.rows):
				for column in range(self._map.cols):
					tile = self._map.grid[row][column]
					# Determine BG Color
					color = self.get_tile_color(tile)

					pos_left = (CELL_MARGIN + CELL_WIDTH) * column + CELL_MARGIN
					pos_top = (CELL_MARGIN + CELL_HEIGHT) * row + CELL_MARGIN

					if (tile in self._map.generals): # General
						# Draw Plus
						pygame.draw.rect(self._screen, color, [pos_left + PLUS_DEPTH, pos_top, CELL_WIDTH - PLUS_DEPTH * 2, CELL_HEIGHT])
						pygame.draw.rect(self._screen, color, [pos_left, pos_top + PLUS_DEPTH, CELL_WIDTH, CELL_HEIGHT - PLUS_DEPTH * 2])
					elif (tile.isCity): # City
						# Draw Circle
						
						pos_left_circle = int(pos_left + (CELL_WIDTH / 2))
						pos_top_circle = int(pos_top + (CELL_HEIGHT / 2))
						pygame.draw.circle(self._screen, color, [pos_left_circle, pos_top_circle], int(CELL_WIDTH / 2))
					else:
						# Draw Rect
						pygame.draw.rect(self._screen, color, [pos_left, pos_top, CELL_WIDTH, CELL_HEIGHT])

					# mark tile territories
					territoryMarkerSize = 5
					tileTerritoryPlayer = self.ekBot.territories.territoryMap[tile.x][tile.y]
					if tile.player != tileTerritoryPlayer:
						territoryColor = None
						if tileTerritoryPlayer != -1:
							territoryColor = PLAYER_COLORS[tileTerritoryPlayer]
							pygame.draw.rect(self._screen, territoryColor, [pos_left + CELL_WIDTH - territoryMarkerSize, pos_top, territoryMarkerSize, territoryMarkerSize])


			# Draw path
			
			self.draw_armies()
			
			if (self.ekBot.redTreeNodes != None):
				redArrow = DirectionalShape(self.get_line_arrow(255,0,0, width = 2))
				self.drawGathers(self.ekBot.redTreeNodes, redArrow)
			if (self.ekBot.gatherNodes != None):
				self.drawGathers(self.ekBot.gatherNodes, self.lineArrow)

			self.draw_board_chokes()

			# if self.ekBot.board_analysis and self.ekBot.board_analysis.intergeneral_analysis:
			# 	chokeColor = CHOKE_PURPLE # purple
			# 	self.draw_army_analysis(self.ekBot.board_analysis.intergeneral_analysis, chokeColor, draw_pathways = True)

			if self.ekBot.targetingArmy != None:
				self.draw_square(self.ekBot.targetingArmy.tile, 3, 1,1,1, 254, SQUARE_INNER_3)

			# LINE TESTING CODE		
			#gen = self.ekBot.general
			#left = self._map.grid[gen.y][gen.x - 1]
			#leftDown = self._map.grid[gen.y + 1][gen.x - 1]
			#down = self._map.grid[gen.y + 1][gen.x]
			
			#self.draw_between_tiles(self.green_line, gen, left)
			#self.draw_between_tiles(self.green_line, left, leftDown)
			#self.draw_between_tiles(self.green_line, leftDown, down)
			#self.draw_between_tiles(self.green_line, down, gen)

			#s(self._map.grid[1][1], 

			while len(self.ekBot.viewInfo.paths) > 0:
				pColorer = self.ekBot.viewInfo.paths.pop()	
				self.draw_path(pColorer.path, pColorer.color[0], pColorer.color[1], pColorer.color[2], pColorer.alpha, pColorer.alphaDecreaseRate, pColorer.alphaMinimum)
				
			alpha = 250
			alphaDec = 4
			alphaMin = 135
			path = None
			if self.ekBot.curPath != None:
				path = self.ekBot.curPath
			self.draw_path(path, 0, 200, 50, alpha, alphaDec, alphaMin)

			if (self.ekBot.dangerAnalyzer != None and self.ekBot.dangerAnalyzer.anyThreat):

				for threat in [self.ekBot.dangerAnalyzer.fastestVisionThreat, self.ekBot.dangerAnalyzer.fastestThreat, self.ekBot.dangerAnalyzer.highestThreat]:
					if threat == None:
						continue
					# Draw danger path
					#print("drawing path")
					alpha = 200
					alphaDec = 6
					alphaMin = 145				
					self.draw_path(threat.path, 150, 0, 0, alpha, alphaDec, alphaMin)
		
			for (tile, targetStyle) in self.ekBot.viewInfo.redTargetedTiles:
				pos_left = (CELL_MARGIN + CELL_WIDTH) * tile.x + CELL_MARGIN
				pos_top = (CELL_MARGIN + CELL_HEIGHT) * tile.y + CELL_MARGIN
				pos_left_circle = int(pos_left + (CELL_WIDTH / 2))
				pos_top_circle = int(pos_top + (CELL_HEIGHT / 2))
				targetColor = self.get_color_from_target_style(targetStyle)
				pygame.draw.circle(self._screen, BLACK, [pos_left_circle, pos_top_circle], int(CELL_WIDTH / 2 - 2), 7)
				pygame.draw.circle(self._screen, targetColor, [pos_left_circle, pos_top_circle], int(CELL_WIDTH / 2) - 5, 1)
			for approx in self.ekBot.generalApproximations:
				if (approx[2] > 0):
					pos_left = (CELL_MARGIN + CELL_WIDTH) * approx[0] + CELL_MARGIN
					pos_top = (CELL_MARGIN + CELL_HEIGHT) * approx[1] + CELL_MARGIN
					pos_left_circle = int(pos_left + (CELL_WIDTH / 2))
					pos_top_circle = int(pos_top + (CELL_HEIGHT / 2))
					pygame.draw.circle(self._screen, BLACK, [pos_left_circle, pos_top_circle], int(CELL_WIDTH / 2 - 2), 7)
					pygame.draw.circle(self._screen, RED, [pos_left_circle, pos_top_circle], int(CELL_WIDTH / 2) - 5, 1)
					#pygame.draw.circle(self._screen, RED, [pos_left_circle, pos_top_circle], int(CELL_WIDTH / 2) - 10, 1)
			#print("history")
			s = pygame.Surface((CELL_WIDTH, CELL_HEIGHT))
			s.fill(WHITE)
			s.set_colorkey(WHITE)

			pygame.draw.circle(s, BLACK, [int(CELL_WIDTH / 2), int(CELL_HEIGHT / 2)], int(CELL_WIDTH / 2 - 2), 7)
			#pygame.draw.circle(s, RED, [int(CELL_WIDTH / 2), int(CELL_HEIGHT / 2)], int(CELL_WIDTH / 2) - 10, 1)
			for i in range(len(self.ekBot.viewInfo.redTargetedTileHistory)):
				hist = self.ekBot.viewInfo.redTargetedTileHistory[i]
				alpha = 150 - 30 * i
				s.set_alpha(alpha)
				for (tile, targetStyle) in hist:
					targetColor = self.get_color_from_target_style(targetStyle)
					pos_left = (CELL_MARGIN + CELL_WIDTH) * tile.x + CELL_MARGIN
					pos_top = (CELL_MARGIN + CELL_HEIGHT) * tile.y + CELL_MARGIN
					pygame.draw.circle(s, targetColor, [int(CELL_WIDTH / 2), int(CELL_HEIGHT / 2)], int(CELL_WIDTH / 2) - 5, 1)
					# first, "erase" the surface by filling it with a color and
					# setting this color as colorkey, so the surface is empty
					self._screen.blit(s, (pos_left, pos_top))
			#print("surface")
			s = pygame.Surface((CELL_WIDTH, CELL_HEIGHT))
			s.fill(WHITE)
			s.set_colorkey(WHITE)
			pygame.draw.line(s, BLACK, (0, 0), (CELL_WIDTH, CELL_HEIGHT), 4)
			pygame.draw.line(s, RED, (0, 0), (CELL_WIDTH, CELL_HEIGHT), 2)
			pygame.draw.line(s, BLACK, (0, CELL_HEIGHT), (CELL_WIDTH, 0), 4)
			pygame.draw.line(s, RED, (0, CELL_HEIGHT), (CELL_WIDTH, 0), 2)
			#print("val")
			if (self._map != None and self.ekBot != None and self.ekBot.viewInfo.evaluatedGrid != None and len(self.ekBot.viewInfo.evaluatedGrid) > 0):
				#print("if")
				for row in range(self._map.rows):
					for column in range(self._map.cols):		
						#print("loop")
						countEvaluated = int(self.ekBot.viewInfo.evaluatedGrid[column][row] + self.ekBot.viewInfo.lastEvaluatedGrid[column][row]);
						#print("loopVal")
						if (countEvaluated > 0):					
							#print("CountVal: {},{}: {}".format(column, row, countEvaluated))
							pos_left = (CELL_MARGIN + CELL_WIDTH) * column + CELL_MARGIN
							pos_top = (CELL_MARGIN + CELL_HEIGHT) * row + CELL_MARGIN
							alpha = int(75 + countEvaluated * 3)
							s.set_alpha(alpha if alpha < 255 else 255)
							self._screen.blit(s, (pos_left, pos_top))
			#print("deltas")
			#print("drawing deltas")
			# Draw deltas
			for row in range(self._map.rows):
				for column in range(self._map.cols):
					tile = self._map.grid[row][column]
					pos_left = (CELL_MARGIN + CELL_WIDTH) * column + CELL_MARGIN
					pos_top = (CELL_MARGIN + CELL_HEIGHT) * row + CELL_MARGIN

					if (tile.delta.toTile != None):
						if (tile.x - tile.delta.toTile.x > 0): #left
							#print("left " + str(tile.x) + "," + str(tile.y))
							pygame.draw.polygon(self._screen, GRAY_DARK, [(pos_left + CELL_WIDTH / 4, pos_top), (pos_left + CELL_WIDTH / 4, pos_top + CELL_HEIGHT), (pos_left - CELL_WIDTH / 4, pos_top + CELL_HEIGHT / 2)])
						elif (tile.x - tile.delta.toTile.x < 0): #right
							#print("right " + str(tile.x) + "," + str(tile.y))
							pygame.draw.polygon(self._screen, GRAY_DARK, [(pos_left + 3 * CELL_WIDTH / 4, pos_top), (pos_left + 3 * CELL_WIDTH / 4, pos_top + CELL_HEIGHT), (pos_left + 5 * CELL_WIDTH / 4, pos_top + CELL_HEIGHT / 2)])			
						elif (tile.y - tile.delta.toTile.y > 0): #up
							#print("up " + str(tile.x) + "," + str(tile.y))
							pygame.draw.polygon(self._screen, GRAY_DARK, [(pos_left, pos_top + CELL_HEIGHT / 4), (pos_left + CELL_WIDTH, pos_top + CELL_HEIGHT / 4), (pos_left + CELL_WIDTH / 2, pos_top - CELL_HEIGHT / 4)])	
						elif (tile.y - tile.delta.toTile.y < 0): #down
							#print("down " + str(tile.x) + "," + str(tile.y))
							pygame.draw.polygon(self._screen, GRAY_DARK, [(pos_left, pos_top + 3 * CELL_HEIGHT / 4), (pos_left + CELL_WIDTH, pos_top + 3 * CELL_HEIGHT / 4), (pos_left + CELL_WIDTH / 2, pos_top + 5 * CELL_HEIGHT / 4)])			


			#print("drawing text")
			#draw text
			for row in range(self._map.rows):
				for column in range(self._map.cols):
					tile = self._map.grid[row][column]	
					pos_left = (CELL_MARGIN + CELL_WIDTH) * column + CELL_MARGIN
					pos_top = (CELL_MARGIN + CELL_HEIGHT) * row + CELL_MARGIN

					color_font = self.get_font_color(tile)
					
					if not tile in self.ekBot.reachableTiles and not tile.isobstacle() and not tile.isCity and not tile.mountain:
						textVal = "   X"
						self._screen.blit(self._font.render(textVal, True, color_font),
										  (pos_left + 2, pos_top + CELL_HEIGHT / 4))
						
					# Draw Text Value
					if (tile.army != 0 and (tile.discovered or tile in self.ekBot.armyTracker.armies)): # Don't draw on empty tiles
						textVal = str(tile.army)
						self._screen.blit(self._font.render(textVal, True, color_font),
										  (pos_left + 2, pos_top + CELL_HEIGHT / 4))
					# Draw coords					
					textVal = "{},{}".format(tile.x, tile.y)
					self._screen.blit(self.small_font(textVal, color_font),
									  (pos_left, pos_top - 2))
					
					if (self.ekBot.leafValueGrid != None):
						leafVal = self.ekBot.leafValueGrid[column][row]
						if (leafVal != None):
							textVal = "{0:.0f}".format(leafVal)
							if (leafVal == -1000000): #then was skipped
								textVal = "x"		
							self._screen.blit(self.small_font(textVal, color_font),
											  (pos_left + CELL_WIDTH / 3, pos_top + 2.2 * CELL_HEIGHT / 3))

					if (self.ekBot.viewInfo.midRightGridText != None):
						text = self.ekBot.viewInfo.midRightGridText[column][row]
						if (text != None):
							textVal = "{0:.0f}".format(text)
							if (text == -1000000):  # then was skipped
								textVal = "x"
							self._screen.blit(self.small_font(textVal, color_font),
											  (pos_left + 3 * CELL_WIDTH / 4, pos_top + CELL_HEIGHT / 3))

					if (self.ekBot.viewInfo.bottomRightGridText != None):
						text = self.ekBot.viewInfo.bottomRightGridText[column][row]
						if (text != None):
							textVal = "{0:.0f}".format(text)
							if (text == -1000000): #then was skipped
								textVal = "x"		
							self._screen.blit(self.small_font(textVal, color_font),
											  (pos_left + 3 * CELL_WIDTH / 4, pos_top + 2.2 * CELL_HEIGHT / 3))

					# bottom righter...?
					if self.ekBot.targetPlayer != -1:
						val = self.ekBot.armyTracker.emergenceLocationMap[self.ekBot.targetPlayer][column][row]
						if val != 0:
							textVal = "{:.0f}".format(val)
							self._screen.blit(self.small_font(textVal, color_font),
											  (pos_left + 3 * CELL_WIDTH / 4, pos_top + 1.6 * CELL_HEIGHT / 3))

					if (self.ekBot.viewInfo.bottomLeftGridText != None):
						text = self.ekBot.viewInfo.bottomLeftGridText[column][row]
						if (text != None):
							textVal = "{0:.0f}".format(text)
							if (text == -1000000):  # then was skipped
								textVal = "x"
							self._screen.blit(self.small_font(textVal, color_font),
											  (pos_left + 2, pos_top + 2.2 * CELL_HEIGHT / 3))

			# Limit to 60 frames per second
			self._clock.tick(60)
 
			# Go ahead and update the screen with what we've drawn.
			pygame.display.flip()
		except:
			raise
			# print("Unexpected error:", sys.exc_info()[0])

	def tile_text_colorer(self, tile) -> typing.Tuple[int, int, int]:
		if tile.player == -1 and tile.visible:
			return BLACK
		return WHITE

	def draw_square(self, tile, width, R, G, B, alpha, shape = None):
		if shape == None:
			shape = SQUARE
		key = BLACK
		color = (min(255,R),min(255,G),min(255,B))
		s = pygame.Surface((CELL_WIDTH, CELL_HEIGHT))
		# first, "erase" the surface by filling it with a color and
		# setting this color as colorkey, so the surface is empty
		s.fill(key)
		s.set_colorkey(key)			

		pos_left = (CELL_MARGIN + CELL_WIDTH) * tile.x + CELL_MARGIN
		pos_top = (CELL_MARGIN + CELL_HEIGHT) * tile.y + CELL_MARGIN
		#logging.info("drawing square for tile {} alpha {} width {} at pos {},{}".format(tile.toString(), alpha, width, pos_left, pos_top))
		
		pygame.draw.rect(s, color, shape, width)
			
		s.set_alpha(alpha)
		self._screen.blit(s, (pos_left, pos_top))


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
			#playerR = (playerR + 256) // 2
			#playerG = (playerG + 256) // 2
			#playerB = (playerB + 256) // 2
		self.draw_square(tile, 1, playerR, playerG, playerB, min(255, int(alphaStart * 1.3)))

		#self.draw_path(army.path, R, G, B, alphaStart, 0, 0)

		if army.expectedPath != None:
			self.draw_path(army.expectedPath, 255, 0, 0, 150, 10, 100)
		
		pos_left = (CELL_MARGIN + CELL_WIDTH) * tile.x + CELL_MARGIN
		pos_top = (CELL_MARGIN + CELL_HEIGHT) * tile.y + CELL_MARGIN
		self._screen.blit(self._font.render(army.name, True, WHITE), (pos_left + CELL_WIDTH - 10, pos_top))

		
	def draw_armies(self):
		for army in list(self.ekBot.armyTracker.armies.values()):
			if army.scrapped:
				self.draw_army(army, 200, 200, 200, 70)
			else:
				self.draw_army(army, 255, 255, 255, 120)


	def draw_army_analysis(self, analysis: ArmyAnalyzer, chokeColor = None, draw_pathways = True, outerChokeColor = None, innerChokeColor = None):
		if chokeColor:		
			for choke in analysis.pathChokes:
				# Poiple
				self.draw_square(choke, 1, chokeColor[0], chokeColor[1], chokeColor[2], 230, SQUARE_INNER_1)

		if draw_pathways:
			self.draw_pathways(analysis.pathways)

	def draw_line_between_tiles(self, sourceTile: Tile, destTile: Tile, color: typing.Tuple[int, int, int], alpha = 255):
		pos_left = 0
		pos_top = 0

		xDiff = destTile.x - sourceTile.x
		yDiff = destTile.y - sourceTile.y

		(r, g, b) = color
		line = self.get_line(r, g, b)

		if (xDiff > 0):
			pos_left = (CELL_MARGIN + CELL_WIDTH) * sourceTile.x + CELL_WIDTH // 2 + CELL_MARGIN
			pos_top = (CELL_MARGIN + CELL_HEIGHT) * sourceTile.y + CELL_MARGIN
			line = pygame.transform.rotate(line, -90)
		if (xDiff < 0):
			pos_left = (CELL_MARGIN + CELL_WIDTH) * sourceTile.x - CELL_WIDTH // 2 + CELL_MARGIN
			pos_top = (CELL_MARGIN + CELL_HEIGHT) * sourceTile.y + CELL_MARGIN
			line = pygame.transform.rotate(line, 90)
		if (yDiff > 0):
			pos_left = (CELL_MARGIN + CELL_WIDTH) * sourceTile.x + CELL_MARGIN
			pos_top = (CELL_MARGIN + CELL_HEIGHT) * sourceTile.y + CELL_HEIGHT // 2 + CELL_MARGIN
			line = pygame.transform.rotate(line, 180)
		if (yDiff < 0):
			pos_left = (CELL_MARGIN + CELL_WIDTH) * sourceTile.x + CELL_MARGIN
			pos_top = (CELL_MARGIN + CELL_HEIGHT) * sourceTile.y - CELL_HEIGHT // 2 + CELL_MARGIN

		line.set_alpha(alpha)
		self._screen.blit(line, (pos_left - 1, pos_top - 1))

	def draw_pathways(self, pathways: MapMatrix):
		allPathWays = pathways.values()
		uniquePathways: typing.Set[PathWay] = set(allPathWays)
		logging.info(
			"pathways.values() {} vs uniquePathways {}".format(len(allPathWays), len(uniquePathways)))
		minLength = INF
		maxLength = 0 - INF
		for pathway in uniquePathways:
			if minLength > pathway.distance:
				minLength = pathway.distance
			if maxLength < pathway.distance and len(pathway.tiles) > 1:
				maxLength = pathway.distance

		for pathway in uniquePathways:
			drawnFrom = set()
			drawingFrontier = deque()
			drawingFrontier.appendleft(pathway.seed_tile)
			while len(drawingFrontier) != 0:
				tile = drawingFrontier.pop()
				if tile not in drawnFrom:
					drawnFrom.add(tile)
					for adj in tile.moveable:
						if adj not in drawnFrom:
							if adj in pathway.tiles:
								g = rescale_value(pathway.distance, minLength, maxLength, 255, 55)
								r = rescale_value(pathway.distance, minLength, maxLength, 55, 255)

								self.draw_line_between_tiles(tile, adj, (r, g, 55), 190)
								drawingFrontier.appendleft(adj)
							#elif adj in pathways: # then check for closer path merge
							#	otherPath = pathways[adj]
							#	if otherPath.distance < pathway.distance:
							#		self.draw_between_tiles(self.yellow_line, tile, adj)


	def draw_board_chokes(self, interChokeColor = None, innerChokeColor = None, outerChokeColor = None):
		if self.ekBot.board_analysis is None:
			return

		if interChokeColor is None:
			interChokeColor = CHOKE_PURPLE

		if innerChokeColor is None:
			innerChokeColor = P_DARK_GREEN

		if outerChokeColor is None:
			outerChokeColor = P_TEAL

		if self.ekBot.board_analysis.intergeneral_analysis is not None:
			self.draw_army_analysis(self.ekBot.board_analysis.intergeneral_analysis,
									chokeColor=interChokeColor,
									draw_pathways=True)

		for tile in self._map.reachableTiles:
			if self.ekBot.board_analysis.innerChokes[tile.x][tile.y]:
				(r, g, b) = innerChokeColor
				self.draw_square(tile, 1, r, g, b, 255, SQUARE_INNER_2)

			if self.ekBot.board_analysis.outerChokes[tile.x][tile.y]:
				(r, g, b) = outerChokeColor
				self.draw_square(tile, 1, r, g, b, 255, SQUARE_INNER_3)
	
	def draw_path(self, pathObject, R, G, B, alphaStart, alphaDec, alphaMin):
		if pathObject == None:
			return
		path = pathObject.start
		alpha = alphaStart
		key = WHITE
		color = (R,G,B)
		while (path != None and path.next != None):
			s = pygame.Surface((CELL_WIDTH, CELL_HEIGHT))
			s.set_colorkey(key)
			# first, "erase" the surface by filling it with a color and
			# setting this color as colorkey, so the surface is empty
			s.fill(key)
			
			# after drawing the circle, we can set the 
			# alpha value (transparency) of the surface
			tile = path.tile
			toTile = path.next.tile
			#print("drawing path {},{} -> {},{}".format(tile.x, tile.y, toTile.x, toTile.y))
			pos_left = (CELL_MARGIN + CELL_WIDTH) * tile.x + CELL_MARGIN
			pos_top = (CELL_MARGIN + CELL_HEIGHT) * tile.y + CELL_MARGIN
			xOffs = 0
			yOffs = 0
			pygame.draw.polygon(s, color, self.Arrow)
			pygame.draw.polygon(s, BLACK, self.Arrow, 2)
			s.set_alpha(alpha)
			self.draw_between_tiles(DirectionalShape(s), tile, toTile)

			path = path.next	
			alpha -= alphaDec					
			if (alpha < alphaMin):
				alpha = alphaMin


	def drawGathers(self, nodes, shape):
		#pruneArrow = self.get_line_arrow(190, 30, 0)
			q = deque()
			for node in nodes:
				q.appendleft((node, True))
			while (len(q) > 0):
				node, unpruned = q.pop()
				for child in node.children:
					q.appendleft((child, unpruned))
				for prunedChild in node.pruned:
					q.appendleft((prunedChild, False))

				if node.fromTile != None:
					self.draw_between_tiles(shape, node.fromTile, node.tile)


	def draw_between_tiles(self, shape, sourceTile, destTile, alpha = 255):
		xDiff = destTile.x - sourceTile.x
		yDiff = destTile.y - sourceTile.y
		s = None
		if (xDiff > 0):
			pos_left = (CELL_MARGIN + CELL_WIDTH) * sourceTile.x + CELL_WIDTH // 2 + CELL_MARGIN
			pos_top = (CELL_MARGIN + CELL_HEIGHT) * sourceTile.y + CELL_MARGIN
			s = shape.leftShape
		if (xDiff < 0):
			pos_left = (CELL_MARGIN + CELL_WIDTH) * sourceTile.x - CELL_WIDTH // 2 + CELL_MARGIN
			pos_top = (CELL_MARGIN + CELL_HEIGHT) * sourceTile.y + CELL_MARGIN
			s = shape.rightShape
		if (yDiff > 0):
			pos_left = (CELL_MARGIN + CELL_WIDTH) * sourceTile.x + CELL_MARGIN
			pos_top = (CELL_MARGIN + CELL_HEIGHT) * sourceTile.y + CELL_HEIGHT // 2 + CELL_MARGIN
			s = shape.upShape
		if (yDiff < 0):
			pos_left = (CELL_MARGIN + CELL_WIDTH) * sourceTile.x + CELL_MARGIN
			pos_top = (CELL_MARGIN + CELL_HEIGHT) * sourceTile.y - CELL_HEIGHT // 2 + CELL_MARGIN
			s = shape.downShape
		s.set_alpha(alpha)
		self._screen.blit(s, (pos_left - 1, pos_top - 1))



	def getCenter(self, tile):
		left, top = self.getTopLeft(tile)
		return (left + CELL_WIDTH / 2, top + CELL_HEIGHT / 2)

	def getTopLeft(self, tile):		
		pos_left = (CELL_MARGIN + CELL_WIDTH) * tile.x + CELL_MARGIN
		pos_top = (CELL_MARGIN + CELL_HEIGHT) * tile.y + CELL_MARGIN
		return (pos_left, pos_top)
					

	def save_images(self):		
		while True:
			if self._readyRender:
				#self.images.append(("{}\\{}.bmp".format(self.logDirectory, self._map.turn), pygame.image.tostring(self._screen, "RGB")))
				
				pygame.image.save(self._screen, "{}\\{}.png".format(self.logDirectory, self._map.turn))
				self._readyRender = False
			time.sleep(0.1)

	def get_font_color(self, tile) -> typing.Tuple[int, int, int]:
		color_font = WHITE
		if tile.visible and tile.player == -1 and not tile.isCity:
			color_font = BLACK
		elif tile.player >= 0 or tile.isobstacle() or not tile.discovered or (tile.isCity and tile.player == -1):
			color_font = WHITE
		elif tile.visible:
			color_font = BLACK
		return color_font

	def get_tile_color(self, tile) -> typing.Tuple[int, int, int]:
		color = WHITE

		if tile.mountain: # Mountain
			color = BLACK
		elif tile.player >= 0:
			playercolor = PLAYER_COLORS[tile.player]
			colorR = playercolor[0]
			colorG = playercolor[1]
			colorB = playercolor[2]
			if (tile.isCity or tile.isGeneral):
				colorR = colorR + KING_COLOR_OFFSET if colorR <= 255 - KING_COLOR_OFFSET else 255
				colorG = colorG + KING_COLOR_OFFSET if colorG <= 255 - KING_COLOR_OFFSET else 255
				colorB = colorB + KING_COLOR_OFFSET if colorB <= 255 - KING_COLOR_OFFSET else 255
			if (not tile.visible):
				colorR = colorR / 2 + 40
				colorG = colorG / 2 + 40
				colorB = colorB / 2 + 40
			color = (colorR, colorG, colorB)
		elif tile.isobstacle(): # Obstacle
			color = GRAY_DARK
		elif not tile.discovered:
			color = UNDISCOVERED_GRAY
		elif tile.isCity and tile.player == -1:
			color = UNDISCOVERED_GRAY
			if (tile.visible):
				color = GRAY

		elif not tile.visible:
			color = GRAY

		return color

	def get_color_from_target_style(self, targetStyle: TargetStyle) -> typing.Tuple[int, int, int]:
		if targetStyle == TargetStyle.RED:
			return RED
		if targetStyle == TargetStyle.BLUE:
			return (50, 50, 255)
		if targetStyle == TargetStyle.GOLD:
			return (255, 215, 0)
		if targetStyle ==TargetStyle.GREEN:
			return P_DARK_GREEN
		if targetStyle == TargetStyle.PURPLE:
			return DARK_PURPLE
		return GRAY

	def small_font(self, text_val: str, color_font: typing.Tuple[int, int, int]):
		return self._fontSmall.render(text_val, True, color_font)

def rescale_value(valToScale, valueMin, valueMax, newScaleMin, newScaleMax):
	# Figure out how 'wide' each range is
	leftSpan = valueMax - valueMin
	rightSpan = newScaleMax - newScaleMin

	# Convert the left range into a 0-1 range (float)
	valueScaled = float(valToScale - valueMin) / float(leftSpan)

	# Convert the 0-1 range into a value in the right range.
	return newScaleMin + (valueScaled * rightSpan)

