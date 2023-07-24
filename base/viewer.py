'''
	@ Harris Christiansen (Harris@HarrisChristiansen.com)
	January 2016
	Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
	Game Viewer
'''
import os
import pygame
from pygame import *
import threading
import time
import logging
from collections import deque 
from ArmyAnalyzer import * 
from copy import deepcopy
from base.client.generals import _spawn


# Color Definitions
BLACK = (0,0,0)
GRAY_DARK = (52,52,52)
UNDISCOVERED_GRAY = (110,110,110)
GRAY = (160,160,160)
WHITE = (255,255,255)
RED = (200,40,40)
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
CELL_WIDTH = 33
CELL_HEIGHT = 33
CELL_MARGIN = 1
SCORES_ROW_HEIGHT = 33
INFO_ROW_HEIGHT = 35
PLUS_DEPTH = 9
SQUARE = Rect(0, 0, CELL_WIDTH, CELL_HEIGHT)
SQUARE_1 = Rect(1, 1, CELL_WIDTH - 2, CELL_HEIGHT - 2)
SQUARE_2 = Rect(2, 2, CELL_WIDTH - 4, CELL_HEIGHT - 4)
SQUARE_SMALLER_INNER = Rect(0, 0, CELL_WIDTH - 1, CELL_HEIGHT - 1)




class DirectionalShape(object):
	def __init__(self, downShape):
		self.downShape = downShape		
		self.leftShape = pygame.transform.rotate(downShape, -90)
		self.rightShape = pygame.transform.rotate(downShape, 90)
		self.upShape = pygame.transform.rotate(downShape, 180)

class GeneralsViewer(object):
	def __init__(self, name=None):
		self._name = name
		self._receivedUpdate = False
		self._readyRender = False
		self.Arrow = None
		self.lineArrow = None
		self.line = None
		

	def updateGrid(self, update):
		updateDir = dir(update)
		self._map = update
		if "bottomText" in updateDir:
			self._bottomText = update.bottomText
		self._scores = sorted(update.scores, key=lambda general: general['total'], reverse=True) # Sort Scores
		
		self._receivedUpdate = True

		if "collect_path" in updateDir:
			self._collect_path = [(path.x, path.y) for path in update.collect_path]
		else:
			self._collect_path = None

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

		window_title = "Generals IO Bot"
		if (self._name != None):
			window_title += " - " + str(self._name)
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
		self.green_line = DirectionalShape(self.get_line(0, 175, 55))
		self.yellow_line = DirectionalShape(self.get_line(155, 151, 55))
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



	def mainViewerLoop(self, alignTop = True, alignLeft = True):
		while not self._receivedUpdate: # Wait for first update
			time.sleep(0.2)
		x = 3 if alignLeft else 1920 - 3 - (CELL_WIDTH + CELL_MARGIN) * self._map.cols
		y = 3 - 1080 if alignTop else 3 - (CELL_HEIGHT + CELL_MARGIN) * self._map.rows - 1080
		self._initViewier((x, y))

		done = False
		while not done:
			if (self._map.ekBot.viewInfo.readyToDraw):
				self._map.ekBot.viewInfo.readyToDraw = False
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
			if self._map.ekBot.allIn:
				allInText = "+"

			# Draw Bottom Info Text
			self._screen.blit(self._fontLrg.render("Turn: {}, ({})".format(self._map.turn, ("%.2f" % self._map.ekBot.viewInfo.lastMoveDuration).lstrip('0')), True, WHITE), (10, self._window_size[1] - INFO_ROW_HEIGHT + 4))
			self._screen.blit(self._font.render(self._map.ekBot.viewInfo.infoText, True, WHITE), (170, self._window_size[1] - INFO_ROW_HEIGHT))
			if self._map.ekBot.timings:
				timings = self._map.ekBot.timings
				self._screen.blit(self._font.render("Timings: {} ({})   - {}{}       {}".format(timings.toString(), (self._map.turn + timings.offsetTurns) % timings.cycleTurns, allInText, self._map.ekBot.all_in_counter, self._map.ekBot.viewInfo.addlTimingsLineText), True, WHITE), (170, self._window_size[1] - INFO_ROW_HEIGHT + 15))
		
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
						if (self._map.ekBot.targetPlayer == player.index):
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
							playerSubtext += " [{}]".format(str(int(self._map.ekBot.playerTargetScores[player.index])))
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
					color = WHITE
					color_font = WHITE

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
							colorR = colorR / 2.3 + FOG_COLOR_OFFSET
							colorG = colorG / 2.3 + FOG_COLOR_OFFSET
							colorB = colorB / 2.3 + FOG_COLOR_OFFSET
						color = (colorR, colorG, colorB)
					elif tile.isobstacle(): # Obstacle
						color = GRAY_DARK
					elif not tile.discovered:
						color = UNDISCOVERED_GRAY					
					elif tile.isCity and tile.player == -1:
						color = UNDISCOVERED_GRAY
						if (tile.visible):
							color = GRAY
						color_font = WHITE
					elif not tile.visible: 
						color = GRAY
					else:
						color_font = BLACK

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
					tileTerritoryPlayer = self._map.ekBot.territories.territoryMap[tile.x][tile.y]
					if tile.player != tileTerritoryPlayer:
						territoryColor = None
						if tileTerritoryPlayer != -1:
							territoryColor = PLAYER_COLORS[tileTerritoryPlayer]
							pygame.draw.rect(self._screen, territoryColor, [pos_left + CELL_WIDTH - territoryMarkerSize, pos_top, territoryMarkerSize, territoryMarkerSize])



			# Draw path
			
			self.draw_armies()
			
			if (self._map.ekBot.redTreeNodes != None):
				redArrow = DirectionalShape(self.get_line_arrow(255,0,0, width = 2))
				self.drawGathers(self._map.ekBot.redTreeNodes, redArrow)
			if (self._map.ekBot.gatherNodes != None):
				self.drawGathers(self._map.ekBot.gatherNodes, self.lineArrow)
			#self.draw_chokes()
			if self._map.ekBot.board_analysis and self._map.ekBot.board_analysis.intergeneral_analysis:
				chokeColor = (93, 0, 111) # purple
				self.draw_army_analysis(self._map.ekBot.board_analysis.intergeneral_analysis, chokeColor, draw_pathways = True)

			if self._map.ekBot.targetingArmy != None:
				self.draw_square(self._map.ekBot.targetingArmy.tile, 3, 1,1,1, 254, SQUARE_2)

			# LINE TESTING CODE		
			#gen = self._map.ekBot.general
			#left = self._map.grid[gen.y][gen.x - 1]
			#leftDown = self._map.grid[gen.y + 1][gen.x - 1]
			#down = self._map.grid[gen.y + 1][gen.x]
			
			#self.draw_between_tiles(self.green_line, gen, left)
			#self.draw_between_tiles(self.green_line, left, leftDown)
			#self.draw_between_tiles(self.green_line, leftDown, down)
			#self.draw_between_tiles(self.green_line, down, gen)

			#s(self._map.grid[1][1], 

			while len(self._map.ekBot.viewInfo.paths) > 0:
				pColorer = self._map.ekBot.viewInfo.paths.pop()	
				self.draw_path(pColorer.path, pColorer.color[0], pColorer.color[1], pColorer.color[2], pColorer.alpha, pColorer.alphaDecreaseRate, pColorer.alphaMinimum)
				
			alpha = 250
			alphaDec = 4
			alphaMin = 135
			path = None
			if self._map.ekBot.curPath != None:
				path = self._map.ekBot.curPath
			self.draw_path(path, 0, 200, 50, alpha, alphaDec, alphaMin)


			

			
			if (self._map.ekBot.dangerAnalyzer != None and self._map.ekBot.dangerAnalyzer.anyThreat):

				for threat in [self._map.ekBot.dangerAnalyzer.fastestVisionThreat, self._map.ekBot.dangerAnalyzer.fastestThreat, self._map.ekBot.dangerAnalyzer.highestThreat]:
					if threat == None:
						continue
					# Draw danger path
					#print("drawing path")
					alpha = 200
					alphaDec = 6
					alphaMin = 145				
					self.draw_path(threat.path, 150, 0, 0, alpha, alphaDec, alphaMin)
				
		
			for tile in self._map.ekBot.viewInfo.lastSearched:
				pos_left = (CELL_MARGIN + CELL_WIDTH) * tile.x + CELL_MARGIN
				pos_top = (CELL_MARGIN + CELL_HEIGHT) * tile.y + CELL_MARGIN
				pos_left_circle = int(pos_left + (CELL_WIDTH / 2))
				pos_top_circle = int(pos_top + (CELL_HEIGHT / 2))
				pygame.draw.circle(self._screen, BLACK, [pos_left_circle, pos_top_circle], int(CELL_WIDTH / 2 - 2), 7)
				pygame.draw.circle(self._screen, RED, [pos_left_circle, pos_top_circle], int(CELL_WIDTH / 2) - 5, 1)
				#pygame.draw.circle(self._screen, RED, [pos_left_circle, pos_top_circle], int(CELL_WIDTH / 2) - 10, 1)
			for approx in self._map.ekBot.generalApproximations:
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
			pygame.draw.circle(s, RED, [int(CELL_WIDTH / 2), int(CELL_HEIGHT / 2)], int(CELL_WIDTH / 2) - 5, 1)
			#pygame.draw.circle(s, RED, [int(CELL_WIDTH / 2), int(CELL_HEIGHT / 2)], int(CELL_WIDTH / 2) - 10, 1)
			for i in range(len(self._map.ekBot.viewInfo.searchHistory)):
				hist = self._map.ekBot.viewInfo.searchHistory[i]
				alpha = 200 - 20 * i
				s.set_alpha(alpha)
				for tile in hist:
					pos_left = (CELL_MARGIN + CELL_WIDTH) * tile.x + CELL_MARGIN
					pos_top = (CELL_MARGIN + CELL_HEIGHT) * tile.y + CELL_MARGIN
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
			if (self._map != None and self._map.ekBot != None and self._map.ekBot.viewInfo.evaluatedGrid != None and len(self._map.ekBot.viewInfo.evaluatedGrid) > 0):
				#print("if")
				for row in range(self._map.rows):
					for column in range(self._map.cols):		
						#print("loop")
						countEvaluated = int(self._map.ekBot.viewInfo.evaluatedGrid[column][row] + self._map.ekBot.viewInfo.lastEvaluatedGrid[column][row]);
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
					color = WHITE
					color_font = WHITE
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
						color_font = WHITE
					elif not tile.visible: 
						color = GRAY
					else:
						color_font = BLACK
					
					if not tile in self._map.ekBot.reachableTiles and not tile.isobstacle() and not tile.isCity and not tile.mountain:
						textVal = "   X"
						self._screen.blit(self._font.render(textVal, True, color_font), (pos_left + 2, pos_top + CELL_HEIGHT / 4))
						
					# Draw Text Value
					if (tile.army != 0 and (tile.discovered or tile in self._map.ekBot.armyTracker.armies)): # Don't draw on empty tiles
						textVal = str(tile.army)
						self._screen.blit(self._font.render(textVal, True, color_font), (pos_left + 2, pos_top + CELL_HEIGHT / 4))
					# Draw coords					
					textVal = "{},{}".format(tile.x, tile.y)
					self._screen.blit(self._fontSmall.render(textVal, True, color_font), (pos_left, pos_top - 2))
					
					if (self._map.ekBot.leafValueGrid != None):
						leafVal = self._map.ekBot.leafValueGrid[column][row]
						if (leafVal != None):
							textVal = "{0:.0f}".format(leafVal)
							if (leafVal == -1000000): #then was skipped
								textVal = "x"		
							self._screen.blit(self._fontSmall.render(textVal, True, color_font), (pos_left + CELL_WIDTH / 3, pos_top + 2 * CELL_HEIGHT / 3))
							
					if (self._map.ekBot.viewInfo.bottomRightGridText != None):
						text = self._map.ekBot.viewInfo.bottomRightGridText[column][row]
						if (text != None):
							textVal = "{0:.0f}".format(text)
							if (text == -1000000): #then was skipped
								textVal = "x"		
							self._screen.blit(self._fontSmall.render(textVal, True, color_font), (pos_left + 3 * CELL_WIDTH / 4, pos_top + 1.5 * CELL_HEIGHT / 3))
						elif self._map.ekBot.targetPlayer != -1:
							val = self._map.ekBot.armyTracker.emergenceLocationMap[self._map.ekBot.targetPlayer][column][row]
							if val != 0:
								textVal = "{:.0f}".format(val)
								self._screen.blit(self._fontSmall.render(textVal, True, color_font), (pos_left + 2.5 * CELL_WIDTH / 4, pos_top + 2 * CELL_HEIGHT / 3))

					if (self._map.ekBot.viewInfo.bottomLeftGridText != None):
						text = self._map.ekBot.viewInfo.bottomLeftGridText[column][row]
						if (text != None):
							textVal = "{0:.0f}".format(text)
							if (text == -1000000): #then was skipped
								textVal = "x"
							self._screen.blit(self._fontSmall.render(textVal, True, color_font), (pos_left + 0.5 * CELL_WIDTH / 4, pos_top + 2 * CELL_HEIGHT / 3))
							
					
					#if self._map.ekBot.board_analysis != None:
					#	if self._map.ekBot.board_analysis.intergeneral_analysis != None:
					#		val = self._map.ekBot.board_analysis.intergeneral_analysis.aMap[column][row]
					#		if val < 1000:
					#			textVal = "{}".format(val)
					#			self._screen.blit(self._fontSmall.render(textVal, True, color_font), (pos_left + 2.5 * CELL_WIDTH / 4, pos_top + 2 * CELL_HEIGHT / 3))
							
					#		val = self._map.ekBot.board_analysis.intergeneral_analysis.bMap[column][row]
					#		if val < 1000:
					#			textVal = "{}".format(val)
					#			self._screen.blit(self._fontSmall.render(textVal, True, color_font), (pos_left + 0.5 * CELL_WIDTH / 4, pos_top + 2 * CELL_HEIGHT / 3))
							
			#print("replay {} turn {}".format(self.repId, self._map.turn))
			# Limit to 60 frames per second
			self._clock.tick(60)
 
			# Go ahead and update the screen with what we've drawn.
			pygame.display.flip()
		except:
			raise
			# print("Unexpected error:", sys.exc_info()[0])
			
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
		for army in list(self._map.ekBot.armyTracker.armies.values()):
			if army.scrapped:
				self.draw_army(army, 200, 200, 200, 70)
			else:
				self.draw_army(army, 255, 255, 255, 120)


	def draw_army_analysis(self, analysis, chokeColor = None, draw_pathways = True):
		if chokeColor:		
			for choke in analysis.pathChokes:
				# Poiple
				self.draw_square(choke, 2, chokeColor[0], chokeColor[1], chokeColor[2], 230, SQUARE_SMALLER_INNER)
		if draw_pathways:
			uniquePathways = set(analysis.pathways.values())
			logging.info("pathways.values() {} vs uniquePathways {}".format(len(analysis.pathways.values()), len(uniquePathways)))
			for pathway in uniquePathways:
				self.draw_pathway(analysis.pathways, pathway)

	def draw_pathway(self, pathways, pathway):
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
							self.draw_between_tiles(self.green_line, tile, adj)
							drawingFrontier.appendleft(adj)
						#elif adj in pathways: # then check for closer path merge
						#	otherPath = pathways[adj]
						#	if otherPath.distance < pathway.distance:
						#		self.draw_between_tiles(self.yellow_line, tile, adj)


	def draw_chokes(self, R = 93, G = 0, B = 111):
		if self._map.ekBot.board_analysis != None:
			if self._map.ekBot.board_analysis.intergeneral_analysis != None:
				for choke in self._map.ekBot.board_analysis.intergeneral_analysis.pathChokes:
					# Poiple
					self.draw_square(choke, 2, R, G, B, 230, SQUARE_SMALLER_INNER)
					
			#for tile in self._map.reachableTiles:
			#	if self._map.ekBot.board_analysis.innerChokes[tile.x][tile.y]:
			#		# Dark green?
			#		self.draw_square(tile, 1, 30, 97, 10, 255, SQUARE_1)

			#	if self._map.ekBot.board_analysis.outerChokes[tile.x][tile.y]:
			#		# Dark yella
			#		self.draw_square(tile, 1, 135, 131, 0, 240, SQUARE_2)
	
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


	def draw_between_tiles(self, shape, sourceTile, destTile):
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