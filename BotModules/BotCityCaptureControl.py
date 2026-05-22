from __future__ import annotations

import logbook
import typing


if typing.TYPE_CHECKING:
    from bot_ek0x45 import EklipZBot

class BotCityCaptureControl:
    @staticmethod
    def block_neutral_captures(bot: EklipZBot, reason: str = ''):
        if bot.curPath and bot.curPath.tail is not None and bot.curPath.tail.tile.isCity and bot.curPath.tail.tile.isNeutral:
            targetNeutCity = bot.curPath.tail.tile
            if bot.is_blocking_neutral_city_captures:
                bot.info(f'forcibly stopped taking neutral city {str(targetNeutCity)} {reason}')
                bot.curPath = None
        logbook.info(f'Preventing neutral city captures for now {reason}')
        bot.is_blocking_neutral_city_captures = True
