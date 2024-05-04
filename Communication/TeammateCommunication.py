from base.client.tile import Tile


class TeammateCommunication(object):
    def __init__(self, message: str, pingTile: Tile | None = None, cooldown: int = 10, detectOnMessageAlone: bool = False, cooldownDetectionKey: str | None = None):
        self.message: str = message

        self.ping_tile: Tile | None = pingTile

        self.cooldown: int = cooldown

        self.cooldown_detection_on_message_alone: bool = detectOnMessageAlone
        """If true, the pinged tile will not be used as part of duplicate message cooldown determination."""

        self.cooldown_key: str | None = cooldownDetectionKey

