import unittest

from BotModules.BotCityCaptureControl import BotCityCaptureControl
from Path import Path


class _BotStub:
    def __init__(self):
        self.curPath = Path()
        self.is_blocking_neutral_city_captures = False
        self.info_messages = []

    def info(self, message):
        self.info_messages.append(message)


class BotCityCaptureControlTests(unittest.TestCase):
    def test_block_neutral_captures_handles_empty_curpath(self):
        bot = _BotStub()

        BotCityCaptureControl.block_neutral_captures(bot, 'test reason')

        self.assertIsNotNone(bot.curPath)
        self.assertTrue(bot.is_blocking_neutral_city_captures)
        self.assertEqual([], bot.info_messages)


if __name__ == '__main__':
    unittest.main()
