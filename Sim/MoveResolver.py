import typing
from base.client.map import MapBase, Tile
from Models.Move import Move

import logbook


class MoveResolver:
    """
    MoveResolver

    Handles the new move queue priority system that:
    1. Prioritizes defensive moves (moving to friendly tiles)
    2. Resolves offensive move conflicts based on army size (largest army wins)
    3. Processes dependent moves (e.g., moving to a tile that another player is moving away from)
    """
    def __init__(self, map: MapBase):
        """
        Set the map and generals for the resolver

        Args:
            map: The current map object
        """
        self.map = map
        self.teams = map.teams
        self.generals = map.generals

        # Configure the dependency checker based on the slippery modifier
        self.dependency_checker = self.has_dependency
        if self.map.has_slippery:
            self.dependency_checker = self.is_dependency

        # Ensure teams is properly populated
        if not self.teams or len(self.teams) != len(self.generals):
            self.teams = []
            for i in range(len(self.generals)):
                self.teams.append(i + 1)
            self.teams.append(-1)  # Add -1 at the end like in JS implementation

    def determine_move_order(self, moves: typing.List[typing.Tuple[int, Move]]) -> typing.List[typing.Tuple[int, Move]]:
        """
        Process all moves from all players, respecting the priority system.

        Args:
            moves: List of (player_index, Move) tuples in their original priority order

        Returns:
            List of (player_index, Move) tuples in the order they should be executed
        """
        if not moves or len(moves) == 0:
            return []

        output_moves = []
        logs = []

        # Add sorting metadata to each move
        moves_with_priority = []
        for i, move_tuple in enumerate(moves):
            player_index, move = move_tuple

            # Skip None moves
            if move is None:
                continue

            moves_with_priority.append({
                'move_tuple': move_tuple,
                'is_defensive': self.is_defensive_move(move_tuple),
                'is_general_attack': self.is_general_attack(move_tuple),
                'army': move.source.army,
                'base_priority': i
            })

        logs.append(['Pre-sort', [f"{mv['move_tuple'][0]} {mv['move_tuple'][1].source.x},{mv['move_tuple'][1].source.y}->{mv['move_tuple'][1].dest.x},{mv['move_tuple'][1].dest.y}" for mv in moves_with_priority]])

        # Sort moves according to priority rules
        moves_with_priority.sort(key=lambda a: (
            not a['is_defensive'],          # Defensive moves first
            a['is_general_attack'],         # Non-general attacks first
            -a['army'],                     # Higher army moves first
            a['base_priority']              # Base priority as tiebreaker
        ))

        logs.append(['Post-sort', [f"{mv['move_tuple'][0]} {mv['move_tuple'][1].source.x},{mv['move_tuple'][1].source.y}->{mv['move_tuple'][1].dest.x},{mv['move_tuple'][1].dest.y}" for mv in moves_with_priority]])

        # Extract the sorted moves and set up null-able array
        moves = [mv['move_tuple'] for mv in moves_with_priority]

        # Process moves while respecting dependencies
        progress = True
        redo_and_log = False
        start_idx = 0
        end_idx = len(moves) - 1

        # Process moves until we can't make progress
        while progress and start_idx <= end_idx:
            progress = False

            # Iterate through valid range
            for i in range(start_idx, end_idx + 1):
                move_tuple = moves[i]
                if move_tuple is None:
                    # Remove nulled moves from the range
                    if i == start_idx:
                        start_idx += 1
                    elif i == end_idx:
                        end_idx -= 1
                    continue

                # Check if this move can be executed (no dependency or dependency has been resolved)
                if not self.dependency_checker(move_tuple, moves, i, start_idx, end_idx):
                    if redo_and_log:
                        player_index, move = move_tuple
                        logbook.info(f"Move INCLUDED {player_index} {move.source.x},{move.source.y}(p{move.source.player} a{move.source.army}) -> {move.dest.x},{move.dest.y}(p{move.dest.player} a{move.dest.army})")

                    self.queue_output_move(moves, output_moves, move_tuple, i)
                    # Update indices if we removed from an endpoint
                    if i == start_idx:
                        start_idx += 1
                    elif i == end_idx:
                        end_idx -= 1
                    progress = True
                    break
                else:
                    player_index, move = move_tuple
                    logbook.info(f"Move {player_index} has dependency on it at tile {move.source.x},{move.source.y}. {player_index} {move.source.x},{move.source.y}(p{move.source.player} a{move.source.army}) -> {move.dest.x},{move.dest.y}(p{move.dest.player} a{move.dest.army})")

            # If we couldn't process any move but still have moves, break a circular dependency
            if not progress and start_idx <= end_idx:
                if not redo_and_log:
                    redo_and_log = True
                    progress = True
                    if logs:
                        for log_pack in logs:
                            logbook.info(*log_pack)
                        logs = []
                    continue

                redo_and_log = False
                # Break the cycle with the current highest priority move (at start_idx)
                logbook.info('Breaking cycle with highest priority move', [f"{mv[0]} {mv[1].source.x},{mv[1].source.y}(p{mv[1].source.player} a{mv[1].source.army}) -> {mv[1].dest.x},{mv[1].dest.y}(p{mv[1].dest.player} a{mv[1].source.army})" for mv in moves if mv is not None])
                hi_pri_move = moves[start_idx]
                self.queue_output_move(moves, output_moves, hi_pri_move, start_idx)
                start_idx += 1

                progress = start_idx <= end_idx

        return output_moves

    def is_defensive_move(self, move_tuple: typing.Tuple[int, Move]) -> bool:
        """
        Check if a move is defensive (moving to a friendly tile)

        Args:
            move_tuple: Tuple of (player_index, Move)

        Returns:
            True if defensive move
        """
        player_index, move = move_tuple
        destination_owner = move.dest.player

        return self.teams[destination_owner] == self.teams[player_index] if destination_owner >= 0 else False

    def is_general_attack(self, move_tuple: typing.Tuple[int, Move]) -> bool:
        """
        Check if the move is targeting a general

        Args:
            move_tuple: Tuple of (player_index, Move)

        Returns:
            True if attacking a general
        """
        _, move = move_tuple
        for general in self.generals:
            if general and move.dest.x == general.x and move.dest.y == general.y:
                return True
        return False

    def has_dependency(self, move_tuple: typing.Tuple[int, Move], moves: typing.List[typing.Tuple[int, Move]], 
                      move_idx: int, start_idx: int, end_idx: int) -> bool:
        """
        Check if a move has a dependency (any other player moving to this move's source tile)

        Args:
            move_tuple: The move to check for dependencies
            moves: List of all remaining moves
            move_idx: Index of the move in the moves list
            start_idx: Starting index for valid moves
            end_idx: Ending index for valid moves

        Returns:
            True if the move has a dependency
        """
        player_index, move = move_tuple

        # Check if anyone is targeting this move's source tile
        for i in range(start_idx, end_idx + 1):
            # Skip self and nulled entries
            if i == move_idx:
                continue
                
            other_move_tuple = moves[i]
            if other_move_tuple is None:
                continue
                
            other_player, other_move = other_move_tuple
            
            if (other_player != player_index and
                other_move.dest.x == move.source.x and
                other_move.dest.y == move.source.y and
                (other_move.source.x != move.dest.x or other_move.source.y != move.dest.y)):
                # Not a mutual attack with just 2 tiles, which we don't need to treat as a cycle
                return True

        return False

    def is_dependency(self, move_tuple: typing.Tuple[int, Move], moves: typing.List[typing.Tuple[int, Move]], 
                     move_idx: int, start_idx: int, end_idx: int) -> bool:
        """
        Check if this move would cause other moves to have dependencies (for slippery modifier)

        Args:
            move_tuple: The move to check
            moves: List of all remaining moves
            move_idx: Index of the move in the moves list
            start_idx: Starting index for valid moves
            end_idx: Ending index for valid moves

        Returns:
            True if the move is a dependency
        """
        player_index, move = move_tuple

        # Check if we are moving to a tile that someone else is moving from
        for i in range(start_idx, end_idx + 1):
            # Skip self and nulled entries
            if i == move_idx:
                continue
                
            other_move_tuple = moves[i]
            if other_move_tuple is None:
                continue
                
            other_player, other_move = other_move_tuple
            
            if (other_player != player_index and
                other_move.source.x == move.dest.x and
                other_move.source.y == move.dest.y and
                (other_move.dest.x != move.source.x or other_move.dest.y != move.source.y)):

                # Optimize general tile check - directly check if the destination is a general
                dest_x, dest_y = other_move.dest.x, other_move.dest.y
                is_general = False
                
                for general in self.generals:
                    if general and general.x == dest_x and general.y == dest_y:
                        is_general = True
                        break

                if not is_general:
                    return True

        return False

    def queue_output_move(self, remaining_moves: typing.List[typing.Tuple[int, Move]],
                         output_moves: typing.List[typing.Tuple[int, Move]],
                         move_tuple: typing.Tuple[int, Move], move_idx: int) -> bool:
        """
        Add a move to the output list and null it in the remaining moves array

        Args:
            remaining_moves: List of remaining moves
            output_moves: List of processed moves
            move_tuple: The move to process
            move_idx: Index of the move in remaining_moves

        Returns:
            True if the move was successfully queued
        """
        player_index = move_tuple[0]
        
        # Check if we already have a move from this player to prevent duplicates
        for existing_move in output_moves:
            if existing_move[0] == player_index:
                logbook.warning(f"Player {player_index} already has a move in output_moves!")
                return False
        
        # Add to output and null in the original array
        output_moves.append(move_tuple)
        remaining_moves[move_idx] = None
        return True
