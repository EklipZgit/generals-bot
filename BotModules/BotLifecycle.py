import BotLogging
import typing


if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot

class BotLifecycle:
    @staticmethod
    def initialize_logging(bot):
        bot.logDirectory = BotLogging.get_file_logging_directory(bot._map.usernames[bot._map.player_index], bot._map.replay_id)
        fileSafeUserName = BotLogging.get_file_safe_username(bot._map.usernames[bot._map.player_index])

        gameMode = '1v1'
        if bot._map.remainingPlayers > 2:
            gameMode = 'ffa'

        BotLogging.add_file_log_output(fileSafeUserName, gameMode, bot._map.replay_id, bot.logDirectory)
