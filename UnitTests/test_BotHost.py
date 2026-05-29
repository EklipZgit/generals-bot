import queue
import unittest

from BotHost import BotHostBase


class BotHostTilePingTests(unittest.TestCase):
    def test_handle_tile_ping_routes_to_bot_comms_queue(self):
        class BotStub:
            pass

        host = object.__new__(BotHostBase)
        host.eklipz_bot = BotStub()
        host.eklipz_bot._tiles_pinged_by_teammate = queue.Queue()
        pinged_tile = object()

        host.handle_tile_ping(pinged_tile)

        self.assertIs(pinged_tile, host.eklipz_bot._tiles_pinged_by_teammate.get_nowait())


if __name__ == '__main__':
    unittest.main()
