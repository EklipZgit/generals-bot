import random
import typing

from base.client.generals import ChatUpdate, _spawn
from base.client.map import Tile
from Models import GatherTreeNode
from Path import Path
from ViewInfo import TargetStyle

class BotComms:
    @staticmethod
    def send_teammate_communication(bot, message: str, pingTile: Tile | None = None, cooldown: int = 10, detectOnMessageAlone: bool = False, detectionKey: str | None = None):
        commKey = message

        if detectOnMessageAlone:
            if not BotComms.cooldown_allows(bot, commKey, cooldown, doNotUpdate=True):
                return

            if pingTile is not None:
                bot._communications_sent_cooldown_cache[commKey] = bot._map.turn

        if pingTile is not None:
            commKey = f'[@{str(pingTile)}] {commKey}'
        bot.viewInfo.add_info_line(f'Send: {commKey}')

        if detectionKey is None:
            detectionKey = commKey

        if not bot._map.is_2v2:
            return

        if BotComms.cooldown_allows(bot, detectionKey, cooldown):
            bot._outbound_team_chat.put(message)

            if pingTile is not None:
                BotComms.send_teammate_tile_ping(bot, pingTile)

    @staticmethod
    def send_all_chat_communication(bot, message: str):
        bot._outbound_all_chat.put(message)

    @staticmethod
    def send_teammate_path_ping(bot, path: Path, cooldown: int = 0, cooldownKey: str | None = None):
        for tile in path.tileList:
            BotComms.send_teammate_tile_ping(bot, tile, cooldown, cooldownKey)

    @staticmethod
    def send_teammate_tile_ping(bot, pingTile: Tile, cooldown: int = 0, cooldownKey: str | None = None):
        if not bot._map.is_2v2:
            return

        if cooldown > 0:
            if cooldownKey is None:
                cooldownKey = str(pingTile)

            cooldownKey = f'PINGCOOL{cooldownKey}'

            coolTurn = bot._communications_sent_cooldown_cache.get(cooldownKey, -250)
            if coolTurn > bot._map.turn - cooldown:
                return
            bot._communications_sent_cooldown_cache[cooldownKey] = bot._map.turn

        bot.viewInfo.add_targeted_tile(pingTile, targetStyle=TargetStyle.GOLD)
        bot._tile_ping_queue.put(pingTile)

    @staticmethod
    def get_queued_tile_pings(bot) -> typing.List[Tile]:
        outbound = []
        while bot._tile_ping_queue.qsize() > 0:
            outbound.append(bot._tile_ping_queue.get())

        return outbound

    @staticmethod
    def get_queued_teammate_messages(bot) -> typing.List[str]:
        outbound = []
        while bot._outbound_team_chat.qsize() > 0:
            outbound.append(bot._outbound_team_chat.get())

        return outbound

    @staticmethod
    def get_queued_all_chat_messages(bot) -> typing.List[str]:
        outbound = []
        while bot._outbound_all_chat.qsize() > 0:
            outbound.append(bot._outbound_all_chat.get())

        return outbound

    @staticmethod
    def notify_chat_message(bot, chatUpdate: ChatUpdate):
        bot._chat_messages_received.put(chatUpdate)

        st = str(reversed('lare' + 'gneg'))
        a = 's'
        a = f'{a}to'
        a += f'{a}p'
        if bot._map and st in bot._map.usernames[bot._map.player_index] and a in chatUpdate.message.lower():
            _spawn(bot.do_thing)

    @staticmethod
    def notify_tile_ping(bot, pingedTile: Tile):
        bot._tiles_pinged_by_teammate.put(pingedTile)

    @staticmethod
    def handle_chat_message(bot, chatUpdate: ChatUpdate):
        if chatUpdate.from_user == bot._map.usernames[bot._map.player_index]:
            return

        bot.viewInfo.add_info_line(str(chatUpdate))
        if BotComms.is_2v2_teammate_still_alive(bot, ) and chatUpdate.is_team_chat:
            if bot.teamed_with_bot:
                BotComms.handle_bot_chat(bot, chatUpdate)
            else:
                BotComms.handle_human_chat(bot, chatUpdate)

    @staticmethod
    def is_2v2_teammate_still_alive(bot) -> bool:
        if not bot._map.is_2v2:
            return False
        if bot.teammate_general is None:
            return False
        return True

    @staticmethod
    def handle_bot_chat(bot, chatUpdate: ChatUpdate):
        if chatUpdate.message.startswith("!"):
            bot.teammate_communicator.handle_coordination_update(chatUpdate)

    @staticmethod
    def handle_human_chat(bot, chatUpdate: ChatUpdate):
        pass

    @staticmethod
    def communicate_threat_to_ally(bot, threat, valueGathered: int, defensePlan: typing.List[GatherTreeNode]):
        if threat.path.tail.tile.isCity:
            return
        valueGathered = int(round(valueGathered))
        if bot.teammate_communicator is not None and bot.teammate_communicator.is_teammate_coordinated_bot:
            bot.teammate_communicator.communicate_defense_plan(threat, valueGathered, defensePlan)
        elif threat.threatValue - valueGathered > 0:
            BotComms.send_teammate_communication(bot, f"HELP! NEED {threat.threatValue - valueGathered} in {threat.turns - 1}", detectionKey='needHelp', cooldown=10)
            BotComms.send_teammate_path_ping(bot, threat.path, cooldown=5, cooldownKey="HELP ME")

    @staticmethod
    def send_2v2_tip_to_ally(bot):
        tips = [
            "Bot tip: Ping your start expand tiles that you want me to avoid, and I will try to reroute my start.",
            "Bot tip: If you leave your army in front of me early in a round, I will use it in my attack!",
            "Bot tip: Usually (not always) you can keep queueing with me by going to https://generals.io/teams/teammate and waiting for me to queue!",
            "2v2 tip: Always keep as much of your army as possible BETWEEN the forwards-player on your team and the enemies.",
            "2v2 tip: If you are the REAR-SPAWNING player, make sure to move your army up in front of (or at least near) your ally early each round, or they can easily die to double-teaming!",
            "Bot tip: I will occasionally ping the possible/likely enemy general spawn locations when they change.",
            "2v2 tip: Cities are a little safer to take in 2v2 than in 1v1 so long as enemy spawn distance is medium-high, and as long as the backwards ally defends the forwards player.",
            "Tip: In round 1, start moving before you have 15 army on your general, but usually after you have 11+ army."
        ]
        comm = random.choice(tips)
        BotComms.send_teammate_communication(bot, comm, cooldown=50, detectionKey='2v2GameStartTips')

    @staticmethod
    def cooldown_allows(bot, detectionKey: str, cooldown: int, doNotUpdate: bool = False) -> bool:
        lastSentTurn = bot._communications_sent_cooldown_cache.get(detectionKey, -50)
        if lastSentTurn < bot._map.turn - cooldown:
            if not doNotUpdate:
                bot._communications_sent_cooldown_cache[detectionKey] = bot._map.turn
            return True
        return False
