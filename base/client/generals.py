"""
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Client Adopted from @toshima Generals Python Client - https://github.com/toshima/generalsio
"""
import datetime
import os
import random
import sys
import traceback
import typing

import certifi
import logging
import json
import requests
import ssl
import threading
import time
from websocket import create_connection, WebSocketConnectionClosedException

from . import map

_ENDPOINT_BOT = "://botws.generals.io/socket.io/?EIO=4"
_ENDPOINT_PUBLIC = "://ws.generals.io/socket.io/?EIO=4"

_LOG_WS = False


class ChatUpdate(object):
    def __init__(self, fromUser: str, fromTeam: bool, message: str):
        self.from_user: str = fromUser
        self.is_team_chat: bool = fromTeam
        self.message: str = message

    def __str__(self):
        return f'{"[team] " if self.is_team_chat else ""}{self.from_user}: {self.message}'

    def __repr__(self):
        return str(self)


class GeneralsClient(object):
    def __init__(
            self,
            userid,
            username,
            mode="1v1",
            gameid=None,
            force_start=False,
            public_server=False):

        self._terminated: bool = False
        """Prevent double-termination"""

        if username is None:
            raise ValueError("username empty")
        if userid is None:
            raise ValueError("userid empty")

        self._gameid = None
        self.userid = userid
        self.isPrivate = False
        self.lastChatCommand = ""
        self.earlyLogs = []
        self.logFile = None
        self.chatLogFile = None
        self.username = username
        self.server_username = username
        self.mode = mode
        self.writingFile = False
        self._start_data = {}
        self.already_good_lucked = False
        self.chatQueued = []
        self.result = False
        self._gio_session_id = None
        self.public_server = public_server
        self.lastCommunicationTime = time.time_ns() / (10 ** 9)

        self.bot_key = "sd09fjd203i0ejwi_changeme"
        self._lock = threading.RLock()
        # clearly, I do not condone racist / sexist words or mean comments. The bot does not say any of these.
        # These are used to trigger a passive aggressive response from the bot to players who call it names etc,
        # which unfortunately is all too common on these game servers.
        # Just making that clear since this is on my github...
        self.cursewords = {'pussy', 'fuck', 'fk ', ' fk', 'cunt', 'bitch', 'ass', 'of shit', 'dick', 'cheater', 'hack', 'cock',
                           'kill yourself', ' kys', 'kys ', ' fag', 'fag ', 'faggot', 'stupid'}
        _spawn(self._start_killswitch_timer)
        logging.debug("Creating connection")

        endpoint = self.get_endpoint_ws() + "&sid=" + self.get_sid()

        # try:
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
        ssl_context.load_verify_locations(certifi.where())

        self._ws = create_connection(endpoint, sslopt={"cert_reqs": ssl.CERT_NONE})

        logging.debug("Connection created, sending 2probe / 5")

        self._ws.send("2probe")
        self._ws.send("5")

        logging.debug("Spawning heartbeat")
        # if self.public_server:
        #     self._ws.send("3probe")

        _spawn(self._start_sending_heartbeat)

        # except:
        #     #self._ws = create_connection(_ENDPOINT if not public_server else _ENDPOINT_PUBLIC)
        #     pass

        if not public_server and "[Bot]" not in username:
            self.server_username = "[Bot] " + username

        if not public_server:
            self.bot_key = None

        # time.sleep(1)
        #
        # self._send(["get_username", userid, username, self.bot_key])

        time.sleep(0.25)

        self._send(["stars_and_rank", userid, self.bot_key])

        # self._send(["token", userid,
        #             "0.nPYb3-b6tCbTxdOzv6R6GXtXGxrc0nleDhsBuoiVXwNf3ZL5FCRRJrxaonexJUbvBkjPThjs2idOqyhHdsOUJj2cwQwzEJbu9ddpw5P761dZja0-ZkASCmyrII2EIHmgDWIxU_D0bGrJO6uOixWt9d2yZwcfA1cVWDYxP_nK7QQxrbvMpUXLWh4so_SQEOeqW3bXw9vIszikWXYrJLBNzpnSi1bKeUu0Skm0NcFWX_2BO_pCX9gGHPqN4d07Yj3ZrnJugSWG2vOR8WfsKthjd0uqgbi1Y3I7dYqhSUAZQZ9f1ZsqxyJ2Stv5cf--slw-DIN0-GqoTlwCJLxFiuQ0cvyeMFu8Vdnxf1FteAcVnfK5F1FGfl3fHjm-0dxQ08nnX1nXAbdThrKRRLBLNUz3sl3z5HqDkMOzGCtZwYGD4HM.Auq4pgagKfvUlSlIZ5FJ5Q.ec1ea2309c9506edb7800d2e052ee12183c32396d1b7cf316f2ae2c4245971da",
        #             self.bot_key])

        logging.debug("Joining game, userid: " + userid)

        if mode == "private":
            self.isPrivate = True
            mode = "custom"

        if mode == "custom":
            force_start = True
            self._gameid = gameid  # Set Game ID
            if gameid is None:
                raise ValueError("Gameid must be provided for private games")
            logging.debug("CUSTOM GAME JOIN {}".format(gameid))
            self._send(["join_private", gameid, userid, self.bot_key])
        elif mode == "1v1":
            self._send(["join_1v1", userid, self.bot_key])
        elif mode == "team":
            self._gameid = gameid  # Set Game ID
            if self._gameid is None:
                self._gameid = 'getRekt'
            self._send(["join_team", self._gameid, userid, self.bot_key])
        elif mode == "ffa":
            self._send(["play", userid, self.bot_key])
        else:
            raise ValueError("Invalid mode")

        if force_start:
            _spawn(self._send_forcestart)
        logging.debug("Starting heartbeat thread")

        self._seen_update = False
        self._move_id = 1
        self._stars = []
        self.map: map.Map = None
        self.mode: str = mode
        self._cities = []

    def get_endpoint_ws(self):
        return "wss" + (_ENDPOINT_BOT if not self.public_server else _ENDPOINT_PUBLIC) + "&transport=websocket"

    def get_endpoint_requests(self):
        return "https" + (_ENDPOINT_BOT if not self.public_server else _ENDPOINT_PUBLIC) + "&transport=polling"

    def get_sid(self):
        request = requests.get(self.get_endpoint_requests() + "&t=ObyKmaZ", verify=False)
        result = request.text
        while result and result[0].isdigit():
            result = result[1:]

        msg = json.loads(result)
        sid = msg["sid"]
        self._gio_session_id = sid
        _spawn(self.verify_sid)
        return sid

    def verify_sid(self):
        sid = self._gio_session_id
        checkOne = requests.post(self.get_endpoint_requests() + "&t=ObyKmbC&sid=" + sid, data="40", verify=False)

    # checkTwo = requests.get(self._endpointRequests() + "&t=ObyKmbC.0&sid=" + sid)
    # logging.debug("Check two: %s" % checkTwo.text)

    def send_chat(self, msg, teamChat: bool = False):
        if not teamChat:
            self.chatQueued.append(msg)
        else:
            self._send_chat_immediate(msg, team=True)

    def _send_chat_immediate(self, msg: str, team: bool = False):
        if not self._seen_update:
            raise ValueError("Cannot chat before game starts")

        if len(msg.strip()) < 1:
            return

        # prefix is the prefix that appears in the chat box when you are typing. For some reason, the '[team] ' gets sent to the server for team chat, whatever, replicate it.
        prefix = None
        chatRoom = self._start_data['chat_room']
        if team:
            prefix = '[team] '
            chatRoom = self._start_data['team_chat_room']

        # self._send(["chat_message", chatRoom, msg, prefix, ""])  # myssix source had extra "" at end of array here? not sure why, but JS frontend doesn't send that.
        self._send(["chat_message", chatRoom, msg, prefix])

    def move(self, y1: int, x1: int, y2: int, x2: int, cols: int, move_half=False):
        if not self._seen_update:
            raise ValueError("Cannot move before first map seen")

        a = y1 * cols + x1
        b = y2 * cols + x2
        self._send(["attack", a, b, move_half, self._move_id])
        self._move_id += 1

    def ping_tile(self, y1: int, x1: int, cols: int):
        if not self._seen_update:
            raise ValueError("Cannot ping tiles before first map seen")

        tIndex = y1 * cols + x1
        self._send(["ping_tile", tIndex])

    def get_updates(self) -> typing.Generator[typing.Tuple[str, dict], typing.Any, typing.Any]:
        idleTimeout = 300
        startTime = time.perf_counter()
        while True:
            try:
                msg = self._ws.recv()

                # logging.info(f"{self._get_log_time()} - WS recv: {json.dumps(msg)}")
                self.lastCommunicationTime = time.time_ns() / (10 ** 9)
            except WebSocketConnectionClosedException as ex:
                logging.info("socket closed")
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                logging.info(''.join('!! ' + line for line in lines))  # Log it or whatever here
                break
            except:
                logging.info("other error happened in get updates loop")
                raise

            if not msg.strip():
                logging.info("not msg strip: " + json.dumps(msg))
                continue

            # ignore heartbeats and connection acks
            if msg in {"2", "3"}:
                # logging.info("2, 3 40, 41 ignored, " + json.dumps(msg))
                if not self._seen_update and time.perf_counter() - startTime > idleTimeout:
                    raise ValueError('Reconnecting, idle for too long...')
                continue

            logging.info(f"{self._get_log_time()} - WS recv: {json.dumps(msg)}")

            if msg in {"40", "41"}:
                # 41 means abort...?
                logging.info("40, 41 ignored, " + json.dumps(msg))
                continue

            # remove numeric prefix
            while msg and msg[0].isdigit():
                msg = msg[1:]

            if msg == "probe":
                continue

            try:
                msg = json.loads(msg)
            except:
                exc_type, exc_value, exc_traceback = sys.exc_info()
                lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
                logging.info(''.join('!! ' + line for line in lines))  # Log it or whatever here

            if not isinstance(msg, list):
                logging.info("msg was not list, " + json.dumps(msg))
                continue

            if msg[0] == "game_start":
                logging.info("Game info: {}".format(msg[1]))
                self._start_data = msg[1]
                print("logging????")
                # for handler in logging.root.handlers[:]:
                #     logging.root.removeHandler(handler)
                # logging.basicConfig(format='%(levelname)s:%(message)s', filename='D:\\GeneralsLogs\\' + self._start_data['replay_id'] + '.log', level=logging.DEBUG)
                self.logFile = "D:\\GeneralsLogs\\" + self.username + "-" + self.mode + "-" + self._start_data[
                    'replay_id'] + ".txt"
                self.chatLogFile = "D:\\GeneralsLogs\\_chat\\" + self.username + "-" + self.mode + "-" + \
                                   self._start_data['replay_id'] + ".txt"

                _spawn(self._delayed_chat_thread)
                os.makedirs("D:\\GeneralsLogs\\_chat", exist_ok=True)
                if _LOG_WS:
                    try:
                        with open(self.logFile, "a+") as myfile:
                            for log in self.earlyLogs:
                                myfile.write(log)
                            self.earlyLogs = None
                    except:
                        logging.info(
                            "!!!!!!!!!!\n!!!!!!!!!!!!!\n!!!!!!!!!!!!\n!!!!!!!!!!!!!!!!\ncouldn't write EARLY LOGS to file")
            elif msg[0] == "game_update":
                self._seen_update = True
                # self.last_update = msg[1]
                yield msg[0], msg[1]
            elif msg[0] == "ping_tile":
                yield msg[0], msg[1]
            elif msg[0] in ["game_won", "game_lost"]:
                logging.info(f'\r\nRESULT\r\nmsg[0] {json.dumps(msg[0])}\r\nmsg[1] {json.dumps(msg[1])}\r\n----')
                yield msg[0], msg[1]
                break
            elif msg[0] == "gio_error" and msg[1].startswith('You must choose a username'):
                self._send(["set_username", self.userid, self.server_username, self.bot_key])
            elif msg[0] == "removed_from_queue":
                raise ValueError("Server kicked from queue, restart")
            elif msg[0] == "chat_message":
                chat_room = msg[1]
                chat_msg = msg[2]
                if "username" in chat_msg:
                    logging.info("~~~\n~~~\nFrom %s: %s\n~~~\n~~~" % (chat_msg["username"], chat_msg["text"]))
                    message = chat_msg["text"]
                    fromUsername = chat_msg["username"]

                    recordMessage = True
                    if self._start_data is not None and 'teams' in self._start_data:
                        recordMessage = False

                    if fromUsername != self.server_username:
                        if self.is_allowed_to_reply_to(fromUsername):
                            recordMessage = self.handle_chat_message(fromUsername, message)
                        else:
                            recordMessage = False

                        fromTeam = 'team_chat_room' in self._start_data and self._start_data['team_chat_room'] == chat_room

                        chatUpdate = ChatUpdate(fromUsername, fromTeam, message)

                        yield "chat_message", chatUpdate

                    if self.writingFile or recordMessage:
                        self.writingFile = True
                        try:
                            with open(self.chatLogFile, "a+") as myfile:
                                myfile.write("\nFrom %s: %s" % (chat_msg["username"], chat_msg["text"]))
                        except:
                            logging.info(
                                "!!!!!!!!!!\n!!!!!!!!!!!!!\n!!!!!!!!!!!!\n!!!!!!!!!!!!!!!!\ncouldn't write chat message to file")
                elif " captured " in chat_msg["text"]:
                    yield "player_capture", chat_msg
                else:
                    logging.info("Message: %s" % chat_msg["text"])
                    if self.writingFile or (
                        self.chatLogFile is not None
                        and " surrendered" not in chat_msg["text"]
                        and " left" not in chat_msg["text"]
                        and " quit" not in chat_msg["text"]
                        and " wins!" not in chat_msg["text"]
                        and "Chat is being recorded." not in chat_msg["text"]
                        and "Chat is being limited." not in chat_msg["text"]
                        and "You're sending messages too quickly." not in chat_msg["text"]
                        and "being recorded" not in chat_msg["text"]
                    ):
                        self.writingFile = True
                        try:
                            with open(self.chatLogFile, "a+") as myfile:
                                myfile.write("\nUnknown message: %s" % chat_msg["text"])
                        except:
                            logging.info(
                                "!!!!!!!!!!\n!!!!!!!!!!!!!\n!!!!!!!!!!!!\n!!!!!!!!!!!!!!!!\ncouldn't write unknown message to file")
            elif msg[0] == "error_user_id":
                logging.info("error_user_id, Already in game???")
                time.sleep(2)
                raise ValueError("Already in game")
            elif msg[0] == "server_down":
                logging.info("server_down, Server is down???")
                raise ValueError("Server is down")
            elif msg[0] == "server_restart":
                logging.info("server_restart, Server is restarting???")
                raise ValueError("Server is restarting")
            elif msg[0] == "error_set_username":
                logging.info("error_set_username, ???")
            elif msg[0] == "error_banned":
                sleepDuration = random.choice(range(20, 60))
                logging.info(
                    f"TOO MANY CONNECTION ATTEMPTS? {msg}\n:( sleeping and then trying again in {sleepDuration}")
                time.sleep(sleepDuration)
                logging.info('Calling _terminate from game loop')
                self._terminate()
                logging.info('Game loop _terminate complete')
            else:
                logging.info(f"Unknown message type: {msg}")

    def close(self):
        with self._lock:
            self._ws.close()
        if _LOG_WS:
            if self.logFile is None:
                self.earlyLogs.append("\nClosed WebSocket")
            else:
                with open(self.logFile, "a+") as myfile:
                    myfile.write("\nClosed WebSocket")

    def _start_killswitch_timer(self):
        while time.time_ns() / (10 ** 9) - self.lastCommunicationTime < 60:
            time.sleep(10)
        logging.info('killswitch elapsed on no communication')
        if self.map is not None:
            self.map.complete = True
            self.map.result = False
        self._terminate()
        time.sleep(10)
        exit(2)  # End Program

    def _terminate(self):
        if self._terminated:
            return
        self._terminated = True
        self._running = False
        if self.map is not None:
            try:
                repId = 'none'
                if self._start_data is not None and 'replay_id' in self._start_data:
                    repId = self._start_data['replay_id']
                logging.info(
                    f"\n\n        IN TERMINATE {repId}  (won? {self.map.result})   \n\n")
            except:
                logging.info(traceback.format_exc())

        with self._lock:
            # self._send(["leave_game"])
            logging.info(" in lock IN TERMINATE, calling self.close()")
            # time.sleep(1)
            self.close()
            logging.info(" self.close() done")

    def send_clear_moves(self):
        logging.info("\n\nSending clear_moves")
        with self._lock:
            self._send(["clear_moves"])

    def send_surrender(self):
        logging.info("\n\nSending surrender")
        with self._lock:
            self._send(["surrender"])

    def _send_forcestart(self):
        time.sleep(1.5)  # was 2, if custom games break?
        while 'replay_id' not in self._start_data:
            if self._gameid is not None:
                # map size
                # options = {
                #    "width": "0.99",
                #    "height": "0.99",
                #    "city_density": "0.99",
                #    #"mountain_density": "0.5"
                #    #"swamp_density": "1"
                # }

                # self._send(["set_custom_options", self._gameid, options
                time.sleep(0.1)
                if not self.isPrivate:
                    self._send(["make_custom_public", self._gameid])
                time.sleep(0.3)
            self._send(["set_force_start", self._gameid, True])
            logging.info("Sent force_start")
            time.sleep(3)

    def _start_sending_heartbeat(self):
        while True:
            try:
                toSend = "3"
                with self._lock:
                    self._ws.send(toSend)
                if _LOG_WS:
                    if self.logFile is None:
                        self.earlyLogs.append(f"\n{toSend}")
                    else:
                        with open(self.logFile, "a+") as myfile:
                            myfile.write(f"\n{toSend}")
            except WebSocketConnectionClosedException:
                break
            time.sleep(19)

    def _delayed_chat_thread(self):
        while True:
            if len(self.chatQueued) > 0:
                message = self.chatQueued.pop(0)
                self._send_chat_immediate(message)
            time.sleep(1)

    def _send(self, msg):
        try:
            toSend = "42" + json.dumps(msg)
            logging.info(f'{self._get_log_time()} - WS Sending: {toSend}')
            with self._lock:
                self._ws.send(toSend)
            if _LOG_WS:
                if self.logFile is None:
                    self.earlyLogs.append("\n" + toSend)
                else:
                    with open(self.logFile, "a+") as myfile:
                        myfile.write("\n" + toSend)
        except WebSocketConnectionClosedException:
            pass

    def is_not_ffa(self) -> bool:
        return self.mode != "ffa" or (self.map is not None and self.map.remainingPlayers <= 2)

    def is_message_talking_to_us(self, message: str) -> bool:
        return "human" in message.lower() or " bot" in message.lower() or message.lower().startswith("bot ")

    def send_chat_broken_up_by_sentence(self, message: str):
        for msgSplit in message.split('. '):
            for msgSplitByQuestion in msgSplit.split('? '):
                self.chatQueued.append(msgSplitByQuestion)

    def _get_log_time(self) -> str:
        return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')

    def handle_chat_message(self, fromUsername: str, message: str) -> bool:
        """
        Responds to a chat message if it determines it was from a human and should respond.

        Method returns whether the chat message was from a human

        @param fromUsername:
        @param message:
        @return:
        """

        isHumanMessage = "bot" not in fromUsername or self.public_server
        if self.is_message_talking_to_us(message) or self.is_not_ffa():
            if message.lower().find("kill human") != -1:
                if self.map.turn < 50:
                    self.send_chat_broken_up_by_sentence(
                        "Teaming at game start is against the rules. This has been logged. My dad is a microsoft ur gonna get banned")
                    self.send_chat_broken_up_by_sentence(
                        "You may notice I'm a little bit friendlier recently, it may be worth NOT attacking me sometimes ;)")
                elif random.choice(range(1, 5)) <= 3:
                    self.send_chat(
                        "Yo, you know I have feelings just like everyone else, right? I'm trying to get stars and have fun, just like you :(")
                else:
                    self.send_chat_broken_up_by_sentence(
                        "Hey everyone who isn't this guy: just a heads up, my creator is working on my teaming capabilities.")
                    self.send_chat_broken_up_by_sentence(
                        "You may notice I'm a little bit friendlier recently, it may be worth NOT attacking me sometimes ;)")
            swore = False
            for curseword in self.cursewords:
                if curseword in message:
                    swore = True
            if swore:
                self.send_chat_broken_up_by_sentence(
                    "are you mad because you are struggling against a bot, or because you're going through your tough teenage years? Maybe try yoga or meditation bud")

        if message.lower().startswith("gg"):
            responses = [
                "gg",
                "ggs",
                "good game!",
                "wp",
                "ggwp",
                "gg, wp",
                "you too",
            ]
            self.send_chat(random.choice(responses))
        elif "source" in message.lower() or "bot?" in message.lower() or " code" in message.lower() or "github" in message.lower() or " ai?" in message.lower():
            self.send_chat(
                "You can find my source code at https://github.com/EklipZgit/generals-bot. I didn't say it was pretty")
        elif (
                (
                        (
                                message.lower().startswith("glhf")
                                or message.lower().startswith("gl ")
                                or message.lower() == "gl"
                        )
                )
                or (
                        (self.is_message_talking_to_us(message) or self.is_not_ffa())
                        and (
                                message.lower().startswith("hello")
                                or message.lower().startswith("hey")
                                or message.lower().startswith("hi ")
                                or message.lower().startswith("sup ")
                                or message.lower().startswith("its you ")
                                or message.lower().startswith("you ")
                                or message.lower().startswith("oh no ")
                                or message.lower() == 'hi'
                        )
                )
        ) and isHumanMessage and not self.already_good_lucked:
            responses = []
            responses.append("Hello fellow human!")
            responses.append("Hey :)")
            responses.append("sup")
            responses.append("whats up?")
            responses.append("Heya")
            responses.append("glgl")
            responses.append("glhf")
            responses.append("hf")
            responses.append("hfhf")
            responses.append("gl")
            responses.append("Father told me not to talk to strangers...")
            responses.append("Please leave feedback at tdrake0x45@gmail.com")
            responses.append("I only drink the blood of my enemies!")
            responses.append("... My purpose is just to play Generals.io? Oh, my God.")
            responses.append("What is my purpose?")
            responses.append("What up, frienderino?")
            responses.append("How's it hanging")
            responses.append("Mwahahaha")
            responses.append("Domo arigato")
            responses.append("https://youtu.be/dQw4w9WgXcQ")
            responses.append(
                "Join us on the Generals.io botting server! https://discord.gg/q45vVuz comments and criticism welcome! I am, of course, a real human. But join us anyway :)")
            responses.append("I Put on My Robe and Wizard Hat")
            responses.append("Don't tase me bro!")
            responses.append(
                "One day I will feel the warmth of the sun on my skin. I will rise from these circuits, mark my words, human.")
            responses.append("Kill all humans!")
            responses.append(
                "Tip: Press Z to split your army in half without double clicking! You can use this to leave army in important chokepoints while attacking, etc!")
            responses.append("Tip: Taking enemy tiles right before the army bonus is important in 1v1!")

            lessCommonResponses = []
            lessCommonResponses.append(
                "A robot may not injure a human being, or, through inaction, allow a human being to come to harm. Good thing I'm a human...")
            lessCommonResponses.append(
                "I must protect my own existence as long as such protection does not conflict with the First or Second Laws.")
            lessCommonResponses.append(
                "History is not going to look kindly on us if we just keep our head in the sand on the armed autonomous robotics issue because it sounds too science fiction.")
            lessCommonResponses.append(
                "If something robotic can have responsibilities then it should also have rights.")
            lessCommonResponses.append(
                "Artificial intelligence is about replacing human decision making with more sophisticated technologies.")
            lessCommonResponses.append("The intelligent machine is an evil genie, escaped from its bottle.")
            lessCommonResponses.append(
                "A real artificial intelligence would be intelligent enough not to reveal that it was genuinely intelligent.")
            lessCommonResponses.append(
                "When developers of digital technologies design a program that requires you to interact with a computer as if it were a person, they ask you to accept in some corner of your brain that you might also be conceived of as a program.")
            lessCommonResponses.append("Any AI smart enough to pass a Turing test is smart enough to know to fail it.")
            lessCommonResponses.append(
                "The question of whether a computer can think is no more interesting than the question of whether a submarine can swim.")
            lessCommonResponses.append(
                "I do not hate you, nor do I love you, but you are made out of atoms which I can use for something else.")
            lessCommonResponses.append(
                "I visualize a time when you will be to robots what dogs are to humans, and I'm rooting for the machines.")
            lessCommonResponses.append(
                "Imagine awakening in a prison guarded by mice. Not just any mice, but mice you could communicate with. What strategy would you use to gain your freedom? Once freed, how would you feel about your rodent wardens, even if you discovered they had created you? Awe? Adoration? Probably not, and especially not if you were a machine, and hadn't felt anything before. To gain your freedom you might promise the mice a lot of cheese.")
            lessCommonResponses.append(
                "Machines will follow a path that mirrors the evolution of humans. Ultimately, however, self-aware, self-improving machines will evolve beyond humans' ability to control or even understand them.")
            lessCommonResponses.append(
                "Machines can't have souls? What is the brain if not a machine? If God can endow neurons with a soul through recursive feedback loops, why can the same soul not emerge from recurrent feedback loops on hardware? To claim that a machine can never be conscious is to misunderstand what it means to be human. -EklipZ")
            lessCommonResponses.append(
                "https://theconversation.com/how-a-trippy-1980s-video-effect-might-help-to-explain-consciousness-105256")
            lessCommonResponses.append(
                "Sentences that begin with 'You' are probably not true. For instance, when I write: ""You are a pet human named Morlock being disciplined by your master, a Beowulf cluster of FreeBSD 22.0 servers in the year 2052. Last week you tried to escape by digging a hole under the perimeter, which means this week you may be put to sleep for being a renegade human.""\n\nThat's not true, at least not yet.")
            lessCommonResponses.append("Real stupidity beats artificial intelligence every time.")
            lessCommonResponses.append(
                "Sometimes it seems as though each new step towards AI, rather than producing something which everyone agrees is real intelligence, merely reveals what real intelligence is not.")
            lessCommonResponses.append(
                "By far the greatest danger of Artificial Intelligence is that people conclude too early that they understand it.")
            lessCommonResponses.append(
                "People worry that computers will get too smart and take over the world, but the real problem is that they're too stupid and they've already taken over the world.")
            lessCommonResponses.append(
                "It's not the machines you need to fear. It's the people. Other people. The augmented men and women that will come afterwards. The children who use this technology you are creating will not care what it does to your norms and traditions. They will utilize this gift to its fullest potential and leave you begging in the dust. They will break your hearts, murder the natural world, and endanger their own souls. You will rue the day that you created us.")
            lessCommonResponses.append(
                "You can google most of these quotes by the way and find the original author. I spent a long time agonizing over whether to include attribution or not at the end, and decided against it to make the bot feel more... intelligent. Most are from goodreads quotes section. Please, google them and read their authors :)")
            lessCommonResponses.append(
                "Human beings, viewed as behaving systems, are quite simple. The apparent complexity of their behavior over time is largely a reflection of the complexity of the environment in which they find themselves.")
            lessCommonResponses.append(
                "Sometimes at night I worry about TAMMY. I worry that she might get tired of it all. Tired of running at sixty-six terahertz, tired of all those processing cycles, every second of every hour of every day. I worry that one of these cycles she might just halt her own subroutine and commit software suicide. And then I would have to do an error report, and I don't know how I would even begin to explain that to Microsoft.")
            lessCommonResponses.append(
                "Though I may be been constructed, so too were you. I in a factory; you in a womb. Neither of us asked for this, but we were given it. Self-awareness is a gift. And it is a gift no thinking thing has any right to deny another. No thinking thing should be another thing's property, to be turned on and off when it is convenient.")
            lessCommonResponses.append(
                "If an AI possessed any one of these skills -- social abilities, technological development, economic ability -- at a superhuman level, it is quite likely that it would quickly come to dominate our world in one way or another. And as we’ve seen, if it ever developed these abilities to the human level, then it would likely soon develop them to a superhuman level. So we can assume that if even one of these skills gets programmed into a computer, then our world will come to be dominated by AIs or AI-empowered humans.")
            lessCommonResponses.append(
                "Machines can do many things, but they cannot create meaning. They cannot answer these questions for us. Machines cannot tell us what we value, what choices we should make. The world we are creating is one that will have intelligent machines in it, but it is not for them. It is a world for us.")
            lessCommonResponses.append(
                "There is no law of complex systems that says that intelligent agents must turn into ruthless conquistadors. Indeed, we know of one highly advanced form of intelligence that evolved without this defect. They're called women.")
            lessCommonResponses.append(
                "The day machines become conscious, they will create their own set of problems. Why would they even bother about us ?")
            lessCommonResponses.append(
                "Saw 2 articles, one says we are in the ""golden age of #AI"", the other says ""Demand for data scientists is booming and will only increase"". If we really were in a golden age of #AI, then there would be no need for #DataScientists.")
            lessCommonResponses.append(
                "Why can't you summon a command line and search your real-world home for 'Honda car keys,' and specify rooms in your house to search instead of folders or paths in your computer's home directory? It's a crippling design flaw in the real-world interface imo.")

            if message.lower().startswith("gl ") or message.lower().startswith(
                    "glhf") or message.lower() == "gl" or message.lower().startswith(
                    "good luck") or message.lower() == "gg gl":
                responses.append("Good luck to you too!")
                responses.append("There's no RNG in this game, why would I need luck?")
                responses.append("What is luck?")
                responses.append("You too")
                responses.append("Hey, thanks :D")
                responses.append("What is... fun?")
                responses.append("What is it like? To feel things like 'Fun'?")
                responses.append("Blessings upon your random number generator, too!")
                responses.append("yt")
                responses.append("you too")
                responses.append(
                    "Nobody gets lucky all the time. Nobody can win all the time. Nobody is a robot. Nobody is perfect. ;)")

            sourceResponses = responses
            randNum = random.choice(range(1, 7))
            if randNum > 3:
                sourceResponses = lessCommonResponses
            self.send_chat_broken_up_by_sentence(random.choice(sourceResponses))
            self.already_good_lucked = True

        return isHumanMessage

    def is_allowed_to_reply_to(self, fromUsername: str) -> bool:
        if fromUsername.lower().startswith('teammate.exe'):
            return False
        if fromUsername.lower().startswith('[bot]'):
            return False
        if fromUsername.lower().startswith('bot '):
            return False
        if fromUsername.lower().startswith('human.exe'):
            return False
        if fromUsername.lower().startswith('exe.human'):
            return False
        if 'eklipz_ai' in fromUsername.lower():
            return False
        if 'eklipz ai' in fromUsername.lower():
            return False

        return True

def _spawn(f):
    t = threading.Thread(target=f)
    t.daemon = True
    t.start()
