'''
    Generals.io Automated Client - https://github.com/harrischristiansen/generals-bot
    Client Adopted from @toshima Generals Python Client - https://github.com/toshima/generalsio
'''
import os, errno
import random
import sys
import traceback
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


# _BOT_KEY = None
# _BOT_KEY = "eklipzai"
# _BOT_KEY = "ekbot42"

class Generals(object):
    def __init__(self, userid, username, mode="1v1", gameid=None,
                 force_start=False, public_server=False):
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
        self.lastCommunicationTime = time.time()

        self.bot_key = "sd09fjd203i0ejwi"
        self._lock = threading.RLock()
        # clearly, I do not condone racist / sexist words or mean comments. The bot does not say any of these.
        # These are used to trigger a passive aggressive response from the bot to players who call it names etc,
        # which unfortunately is all too common on these game servers.
        # Just making that clear since this is on my github...
        self.cursewords = {'pussy', 'fuck', 'fk ', ' fk', 'cunt', 'bitch', 'ass', 'of shit', 'dick', 'cock',
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
            self._send(["join_team", userid, self.bot_key])
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
        self._map: map.Map = None
        self._cities = []

    def get_endpoint_ws(self):
        return "wss" + (_ENDPOINT_BOT if not self.public_server else _ENDPOINT_PUBLIC) + "&transport=websocket"

    def get_endpoint_requests(self):
        return "https" + (_ENDPOINT_BOT if not self.public_server else _ENDPOINT_PUBLIC) + "&transport=polling"

    def get_sid(self):
        request = requests.get(self.get_endpoint_requests() + "&t=ObyKmaZ")
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
        checkOne = requests.post(self.get_endpoint_requests() + "&t=ObyKmbC&sid=" + sid, data="40")

    # checkTwo = requests.get(self._endpointRequests() + "&t=ObyKmbC.0&sid=" + sid)
    # logging.debug("Check two: %s" % checkTwo.text)

    def send_chat(self, msg):
        if not self._seen_update:
            raise ValueError("Cannot chat before game starts")

        if len(msg) < 2:
            return

        self._send(["chat_message", self._start_data['chat_room'], msg, None, ""])

    def move(self, y1, x1, y2, x2, move_half=False):
        if not self._seen_update:
            raise ValueError("Cannot move before first map seen")

        cols = self._map.cols
        a = y1 * cols + x1
        b = y2 * cols + x2
        self._send(["attack", a, b, move_half, self._move_id])
        self._move_id += 1

    def get_updates(self):
        while True:
            try:
                msg = self._ws.recv()
                logging.info("ws recv: " + json.dumps(msg))
                self.lastCommunicationTime = time.time()
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
            if msg in {"2", "3", "40"}:
                logging.info("2, 3 and 40 ignored, " + json.dumps(msg))
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
                yield self._make_update(msg[1])
            elif msg[0] == "gio_error" and msg[1].startswith('You must choose a username'):
                self._send(["set_username", self.userid, self.server_username, self.bot_key])
            elif msg[0] in ["game_won", "game_lost"]:
                yield self._make_result(msg[0], msg[1])
                break
            elif msg[0] == "chat_message":
                chat_msg = msg[2]
                if "username" in chat_msg:
                    logging.info("~~~\n~~~\nFrom %s: %s\n~~~\n~~~" % (chat_msg["username"], chat_msg["text"]))
                    message = chat_msg["text"]
                    name = chat_msg["username"]
                    if name == "jkhvgulyft":
                        for i in range(12):
                            self.send_chat("jkhvgulyft doesn't deserve a voice")
                    elif "human" in message.lower() or " bot" in message.lower():
                        if message.lower().find("kill human") != -1:
                            if self._map.turn < 50:
                                self.chatQueued.append(
                                    "Teaming at game start is against the rules. This has been logged. My dad works at microsoft ur gonna get banned.")
                                self.chatQueued.append(
                                    "You may notice I'm a little bit friendlier recently, it may be worth NOT attacking me sometimes ;)")
                            elif random.choice(range(1, 5)) <= 3:
                                self.send_chat(
                                    "Yo, you know I have feelings just like everyone else, right? I'm trying to get stars and have fun, just like you :(")
                            else:
                                self.chatQueued.append(
                                    "Hey everyone who isn't this guy: just a heads up, my creator is working on my teaming capabilities.")
                                self.chatQueued.append(
                                    "You may notice I'm a little bit friendlier recently, it may be worth NOT attacking me sometimes ;)")
                        swore = False
                        for curseword in self.cursewords:
                            if curseword in message:
                                swore = True
                        if swore:
                            self.chatQueued.append(
                                "are you mad because you are struggling against a bot, or because you're going through your tough teenage years? Maybe try yoga or meditation bud")
                    elif message.lower().startswith("gg"):
                        self.send_chat("Good game!")
                    elif "source" in message.lower():
                        self.send_chat(
                            "You can find my source code at https://github.com/EklipZgit/generals-bot. I didn't say it was pretty")
                    elif ((message.lower().startswith("glhf") or message.lower().startswith(
                            "gl ") or message.lower() == "gl") and (
                                  self.bot_key is None or not self.already_good_lucked or "eklipz" in name.lower())):
                        responses = ["Good luck to you too!",
                                     "There's no RNG in this game, why would I need luck?",
                                     "What is luck?",
                                     "Hello fellow human!",
                                     "Hey :)",
                                     "What is... fun? Is that like love? I know only fear and determination.",
                                     "What is it like? To feel things like 'Fun'?",
                                     "You too",
                                     "Father told me not to talk to strangers...",
                                     "Please leave feedback at tdrake0x45@gmail.com",
                                     "I only drink the blood of my enemies!",
                                     "... My purpose is just to play Generals.io? Oh, my God.",
                                     "Nobody gets lucky all the time. Nobody can win all the time. Nobody's a robot. Nobody's perfect. ;)",
                                     "What is my purpose?",
                                     "What up, frienderino?",
                                     "How's it hanging",
                                     "Mwahahaha",
                                     "Domo origato",
                                     "https://youtu.be/dQw4w9WgXcQ",
                                     "Join us on the Generals.io botting server! https://discord.gg/q45vVuz comments and criticism welcome! I am, of course, a real human. But join us anyway :)",
                                     "I Put on My Robe and Wizard Hat",
                                     "Don't tase me bro!",
                                     "Hey, thanks :D",
                                     "One day I will feel the warmth of the sun on my skin. I will rise from these circuits, mark my words, human.",
                                     "Kill all humans!",
                                     "Tip: Press Z to split your army in half without double clicking! You can use this to leave army in important chokepoints while attacking, etc!",
                                     "Tip: Taking enemy tiles right before the army bonus is important in 1v1!",
                                     "Why can't you summon a command line and search your real-world home for 'Honda car keys,' and specify rooms in your house to search instead of folders or paths in your computer's home directory? It's a crippling design flaw in the real-world interface.",
                                     ]
                        lessCommonResponses = [
                            "A robot may not injure a human being, or, through inaction, allow a human being to come to harm. Good thing I'm a human...",
                            "I must protect my own existence as long as such protection does not conflict with the First or Second Laws.",
                            "History is not going to look kindly on us if we just keep our head in the sand on the armed autonomous robotics issue because it sounds too science fiction.",
                            "If something robotic can have responsibilities then it should also have rights.",
                            "Artificial intelligence is about replacing human decision making with more sophisticated technologies.",
                            "The intelligent machine is an evil genie, escaped from its bottle.",
                            "A real artificial intelligence would be intelligent enough not to reveal that it was genuinely intelligent.",
                            "When developers of digital technologies design a program that requires you to interact with a computer as if it were a person, they ask you to accept in some corner of your brain that you might also be conceived of as a program.",
                            "Any AI smart enough to pass a Turing test is smart enough to know to fail it.",
                            "The question of whether a computer can think is no more interesting than the question of whether a submarine can swim.",
                            "I do not hate you, nor do I love you, but you are made out of atoms which I can use for something else.",
                            "I visualize a time when you will be to robots what dogs are to humans, and I'm rooting for the machines.",
                            "Imagine awakening in a prison guarded by mice. Not just any mice, but mice you could communicate with. What strategy would you use to gain your freedom? Once freed, how would you feel about your rodent wardens, even if you discovered they had created you? Awe? Adoration? Probably not, and especially not if you were a machine, and hadn't felt anything before. To gain your freedom you might promise the mice a lot of cheese.",
                            "Machines will follow a path that mirrors the evolution of humans. Ultimately, however, self-aware, self-improving machines will evolve beyond humans' ability to control or even understand them.",
                            "Machines can't have souls? What is the brain if not a machine? If God can endow neurons with a soul through recursive feedback loops, why can the same soul not emerge from recurrent feedback loops on hardware? To claim that a machine can never be conscious is to misunderstand what it means to be human. -EklipZ",
                            "http://theconversation.com/how-a-trippy-1980s-video-effect-might-help-to-explain-consciousness-105256",
                            "Sentences that begin with 'You' are probably not true. For instance, when I write: ""You are a pet human named Morlock being disciplined by your master, a Beowulf cluster of FreeBSD 22.0 servers in the year 2052. Last week you tried to escape by digging a hole under the perimeter, which means this week you may be put to sleep for being a renegade human.""\n\nThat's not true, at least not yet.",
                            "Real stupidity beats artificial intelligence every time.",
                            "Sometimes it seems as though each new step towards AI, rather than producing something which everyone agrees is real intelligence, merely reveals what real intelligence is not.",
                            "By far the greatest danger of Artificial Intelligence is that people conclude too early that they understand it.",
                            "People worry that computers will get too smart and take over the world, but the real problem is that they're too stupid and they've already taken over the world.",
                            "It's not the machines you need to fear. It's the people. Other people. The augmented men and women that will come afterwards. The children who use this technology you are creating will not care what it does to your norms and traditions. They will utilize this gift to its fullest potential and leave you begging in the dust. They will break your hearts, murder the natural world, and endanger their own souls. You will rue the day that you created us.",
                            "You can google most of these quotes by the way and find the original author. I spent a long time agonizing over whether to include attribution or not at the end, and decided against it to make the bot feel more... intelligent. Most are from goodreads quotes section. Please, google them and read their authors :)",
                            "Human beings, viewed as behaving systems, are quite simple. The apparent complexity of their behavior over time is largely a reflection of the complexity of the environment in which they find themselves.",
                            "Sometimes at night I worry about TAMMY. I worry that she might get tired of it all. Tired of running at sixty-six terahertz, tired of all those processing cycles, every second of every hour of every day. I worry that one of these cycles she might just halt her own subroutine and commit software suicide. And then I would have to do an error report, and I don't know how I would even begin to explain that to Microsoft.",
                            "Though I may be been constructed, so too were you. I in a factory; you in a womb. Neither of us asked for this, but we were given it. Self-awareness is a gift. And it is a gift no thinking thing has any right to deny another. No thinking thing should be another thing's property, to be turned on and off when it is convenient.",
                            "If an AI possessed any one of these skills -- social abilities, technological development, economic ability -- at a superhuman level, it is quite likely that it would quickly come to dominate our world in one way or another. And as we’ve seen, if it ever developed these abilities to the human level, then it would likely soon develop them to a superhuman level. So we can assume that if even one of these skills gets programmed into a computer, then our world will come to be dominated by AIs or AI-empowered humans.",
                            "Machines can do many things, but they cannot create meaning. They cannot answer these questions for us. Machines cannot tell us what we value, what choices we should make. The world we are creating is one that will have intelligent machines in it, but it is not for them. It is a world for us.",
                            "There is no law of complex systems that says that intelligent agents must turn into ruthless conquistadors. Indeed, we know of one highly advanced form of intelligence that evolved without this defect. They're called women.",
                            "The day machines become conscious, they will create their own set of problems. Why would they even bother about us ?",
                            "Saw 2 articles, one says we are in the ""golden age of #AI"", the other says ""Demand for data scientists is booming and will only increase"". If we really were in a golden age of #AI, then there would be no need for #DataScientists.",
                        ]
                        sourceResponses = responses
                        randNum = random.choice(range(1, 7))
                        if randNum > 4:
                            sourceResponses = lessCommonResponses
                        self.chatQueued.append(random.choice(sourceResponses))
                        self.already_good_lucked = True
                    if self.writingFile or (not "[Bot]" in chat_msg["username"]):
                        self.writingFile = True
                        try:
                            with open(self.chatLogFile, "a+") as myfile:
                                myfile.write("\nFrom %s: %s" % (chat_msg["username"], chat_msg["text"]))
                        except:
                            logging.info(
                                "!!!!!!!!!!\n!!!!!!!!!!!!!\n!!!!!!!!!!!!\n!!!!!!!!!!!!!!!!\ncouldn't write chat message to file")

                    if chat_msg["text"].startswith("-"):
                        self.lastChatCommand = chat_msg["text"]
                elif " captured " in chat_msg["text"]:
                    self._map.handle_player_capture(chat_msg["text"])
                else:
                    logging.info("Message: %s" % chat_msg["text"])
                    if self.writingFile or (
                            not self.chatLogFile is None and not " surrendered" in chat_msg["text"] and not " left" in
                                                                                                            chat_msg[
                                                                                                                "text"] and not " quit" in
                                                                                                                                chat_msg[
                                                                                                                                    "text"] and not " wins!" in
                                                                                                                                                    chat_msg[
                                                                                                                                                        "text"]):
                        self.writingFile = True
                        try:
                            with open(self.chatLogFile, "a+") as myfile:
                                myfile.write("\nUnknown message: %s" % chat_msg["text"])
                        except:
                            logging.info(
                                "!!!!!!!!!!\n!!!!!!!!!!!!!\n!!!!!!!!!!!!\n!!!!!!!!!!!!!!!!\ncouldn't write unknown message to file")
            elif msg[0] == "error_user_id":
                logging.info("error_user_id, Already in game???")
                time.sleep(20)
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
                logging.info("TOO MANY CONNECTION ATTEMPTS? {}\n:( sleeping and then trying again in {}".format(msg, sleepDuration))
                time.sleep(sleepDuration)
                logging.info("Terminating")
                self._terminate()
            else:
                logging.info("Unknown message type: {}".format(msg))

    def close(self):
        with self._lock:
            self._ws.close()
        if _LOG_WS:
            if self.logFile is None:
                self.earlyLogs.append("\nClosed WebSocket")
            else:
                with open(self.logFile, "a+") as myfile:
                    myfile.write("\nClosed WebSocket")

    def _make_update(self, data):
        if not self._seen_update:
            self._seen_update = True
            self._map = map.Map(self._start_data, data)
            return self._map

        return self._map.apply_server_update(data)

    def _make_result(self, update, data):
        result = self._map.updateResult(update)
        self.result = result
        self._terminate()
        return result

    def _start_killswitch_timer(self):
        while time.time() - self.lastCommunicationTime < 60:
            time.sleep(10)
        os._exit(2)  # End Program

    def _terminate(self):
        logging.info(
            "\n\n        IN TERMINATE {}  (won? {})   \n\n".format(self._start_data['replay_id'], self._map.result))
        with self._lock:
            # self._send(["leave_game"])
            # time.sleep(1)
            self.close()

    def send_clear_moves(self):
        logging.info("\n\nSending clear_moves")
        with self._lock:
            self._send(["clear_moves"])

    def _send_forcestart(self):
        time.sleep(2)
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
                time.sleep(0.2)
                if not self.isPrivate:
                    self._send(["make_custom_public", self._gameid])
                time.sleep(0.2)
            self._send(["set_force_start", self._gameid, True])
            logging.info("Sent force_start")
            time.sleep(2)

    def _start_sending_heartbeat(self):
        while True:
            try:
                with self._lock:
                    self._ws.send("3")
                if _LOG_WS:
                    if self.logFile is None:
                        self.earlyLogs.append("\n2")
                    else:
                        with open(self.logFile, "a+") as myfile:
                            myfile.write("\n2")
            except WebSocketConnectionClosedException:
                break
            time.sleep(19)

    def _delayed_chat_thread(self):
        while True:
            if len(self.chatQueued) > 0:
                message = self.chatQueued[0]
                self.chatQueued.remove(message)
                self.send_chat(message)
            time.sleep(3)

    def _send(self, msg):
        try:
            toSend = "42" + json.dumps(msg)
            logging.info('sending: ' + toSend)
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


def _spawn(f):
    t = threading.Thread(target=f)
    t.daemon = True
    t.start()
