import SearchUtils


class BotDefenseQueries:
    @staticmethod
    def determine_fog_defense_amount_available_for_tiles(bot, targetTiles, enPlayer, fogDefenseTurns: int = 0, fogReachTurns: int = 8) -> int:
        """Does NOT include the army that is on the targetTiles."""
        targetArmy = bot.opponent_tracker.get_approximate_fog_army_risk(enPlayer, cityLimit=None, inTurns=fogDefenseTurns)

        genReachable = SearchUtils.build_distance_map_matrix_with_skip(bot._map, targetTiles, skipTiles=bot._map.visible_tiles)

        used = set()
        for army in bot.armyTracker.armies.values():
            if army.player != enPlayer:
                continue

            if army.name in used:
                continue

            if army.tile.visible:
                continue

            anyReachable = False
            if genReachable.raw[army.tile.tile_index] is None or genReachable.raw[army.tile.tile_index] >= fogReachTurns:
                for entangled in army.entangledArmies:
                    if genReachable.raw[entangled.tile.tile_index] is not None and genReachable.raw[entangled.tile.tile_index] < fogReachTurns:
                        anyReachable = True
            else:
                anyReachable = True

            if not anyReachable:
                targetArmy -= army.value
                used.add(army.name)

        return targetArmy
