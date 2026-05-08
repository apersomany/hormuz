from copy import deepcopy
import random

# ===========================================================================
# COMMAND BUS PROTOCOL
#
# A global 5-bit bus (bits 4..0) broadcast to every Cell.
# ===========================================================================
#
#   bit [1:0] — opcode
#       00 = RESET  — clear all state, randomly populate mines
#       01 = TICKH  — horizontal tick (player movement + wave propagation)
#       10 = TICKV  — vertical tick (collision detection)
#       11 = CHEAT  — display override (shows mines, no state change)
#
#   bit [3:2] — direction (only meaningful for TICKH when bit 4 is set)
#       00 = W (up)
#       01 = A (left)
#       10 = D (right)
#       11 = S (down)
#       Bitwise inversion of the direction code yields the opposite direction.
#
#   bit [4]   — movement enable (only meaningful for TICKH)
#       0 = no movement (wave propagation still occurs on TICKH)
#       1 = move player in the direction encoded by bits [3:2]
#
#   Other combinations (e.g. movement enable on RESET/TICKV/CHEAT) are
#   ignored; sub-blocks only examine the relevant bits.
# ===========================================================================

RESET = 0b00
TICKH = 0b01
TICKV = 0b10
CHEAT = 0b11

W = 0b00  # up
A = 0b01  # left
D = 0b10  # right
S = 0b11  # down

class Player:

    def __init__(self):
        self.player = False

    def tick(self, command_bus: int, adjacent: list[bool]) -> bool:
        if command_bus & 0b11 == RESET:
            return False

        # Bit 4 of the command bus is the movement enable.
        # Direction bit mapping: XOR with 0b11 inverts the direction
        # (adjacent list is ordered [W, A, D, S] but pressing e.g. W
        # reads the southern neighbour — bitwise inversion gives
        # bidirectional movement).
        if command_bus & 0b11 == TICKH and (command_bus >> 4) & 1:
            return adjacent[0b11 ^ (command_bus >> 2 & 0b11)]

        return self.player


class Mine:

    def __init__(self):
        self.mine = False

    def tick(self, command_bus: int, adjacent: list[bool]) -> bool:
        # RESET: 1/16 chance of placing a mine (LFSR + 4-bit comparator).
        if command_bus & 0b11 == RESET:
            return random.randint(0, 15) == 0

        return self.mine


class Wave:

    def __init__(self):
        self.wave = False

    def tick(self, command_bus: int, adjacent: list[bool]) -> bool:
        if command_bus & 0b11 == RESET:
            return False

        if command_bus & 0b11 == TICKH:
            # Conway-like neighbour-count rule (sum == 1 or 2).
            return sum(adjacent) in [1, 2]

        return self.wave


class Cell:

    def __init__(self):
        self.player = Player()
        self.mine = Mine()
        self.wave = Wave()

    def tick(self, command_bus: int, adjacent: list["Cell"]) -> tuple[bool, bool, bool, bool]:
        player_adjacent = [neighbour.player.player for neighbour in adjacent]
        mine_adjacent   = [neighbour.mine.mine   for neighbour in adjacent]
        wave_adjacent   = [neighbour.wave.wave   for neighbour in adjacent]

        next_player = self.player.tick(command_bus, player_adjacent)
        next_mine   = self.mine.tick(command_bus, mine_adjacent)
        next_wave   = self.wave.tick(command_bus, wave_adjacent)

        # TICKV collision detection: player + mine in same cell
        # destroys both, spawns wave.
        if command_bus & 0b11 == TICKV:
            if self.player.player and self.mine.mine:
                next_player = False
                next_mine   = False
                next_wave   = True

        # CHEAT reveals mines on display; default shows player/wave.
        if command_bus & 0b11 == CHEAT:
            display = self.mine.mine
        else:
            display = self.wave.wave or self.player.player

        return next_player, next_mine, next_wave, display


class Game:
    """2D grid of Cells. A global 5-bit command bus broadcasts to every Cell
    simultaneously. deepcopy enforces synchronous updates (all cells tick
    from the same previous state)."""

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self.grid = [[Cell() for _ in range(width)] for _ in range(height)]
        self.displays = [[False for _ in range(width)] for _ in range(height)]
        self.reset()

    def adjacent(self, x: int, y: int) -> list[Cell]:
        return [
            self.grid[y - 1][x] if y > 0 else Cell(),
            self.grid[y][x - 1] if x > 0 else Cell(),
            self.grid[y][x + 1] if x < self.width - 1 else Cell(),
            self.grid[y + 1][x] if y < self.height - 1 else Cell(),
        ]

    def tick_inner(self, command_bus: int):
        # Synchronous update: deepcopy ensures every cell sees the same
        # pre-tick state.
        next_grid = deepcopy(self.grid)
        self.displays = [[False for _ in range(self.width)] for _ in range(self.height)]
        for y in range(self.height):
            for x in range(self.width):
                next_player, next_mine, next_wave, display = (
                    self.grid[y][x].tick(command_bus, self.adjacent(x, y))
                )
                next_grid[y][x].player.player = next_player
                next_grid[y][x].mine.mine   = next_mine
                next_grid[y][x].wave.wave   = next_wave
                self.displays[y][x] = display
        self.grid = next_grid

    def reset(self):
        self.tick_inner(RESET)
        self.grid[self.height - 1][self.width // 2].player.player = True
        self.displays[self.height - 1][self.width // 2] = True

    def tick(self, w: bool, a: bool, s: bool, d: bool) -> str | None:
        # Phase 1: horizontal tick (movement + wave propagation).
        command_bus = TICKH
        if w:
            command_bus = TICKH | (W << 2) | (1 << 4)
        elif a:
            command_bus = TICKH | (A << 2) | (1 << 4)
        elif s:
            command_bus = TICKH | (S << 2) | (1 << 4)
        elif d:
            command_bus = TICKH | (D << 2) | (1 << 4)
        self.tick_inner(command_bus)

        if any(cell.player.player for cell in self.grid[0]):
            return "W"
        if any(cell.wave.wave for cell in self.grid[0]):
            return "L"

        # Phase 2: vertical tick (collision detection).
        self.tick_inner(TICKV)
        return None

    def show_cheat(self):
        self.tick_inner(CHEAT)


# ---- Terminal renderer & game loop ----

import sys
import time
import os

if __name__ == "__main__":
    HOME = "\033[H"
    CLEAR = "\033[2J"
    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"
    ANSI_RST = "\033[0m"

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    WHITE = "\033[97m"


    def get_key():
        if sys.platform == "win32":
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b"\xe0", b"\x00"):
                    msvcrt.getch()
                    return None
                return ch.lower()
        else:
            import select
            import tty
            import termios
            if select.select([sys.stdin], [], [], 0)[0]:
                return sys.stdin.read(1).lower()
        return None


    def draw(game: Game, message: str = "", cheat: bool = False):
        lines = [HOME]
        lines.append("+" + "---" * game.width + "+")
        for y in range(game.height):
            row = "|"
            for x in range(game.width):
                on = game.displays[y][x]
                if on:
                    row += f" {WHITE}\u2588\u2588{ANSI_RST}"
                else:
                    row += f" {DIM}\u00b7\u00b7{ANSI_RST}"
            lines.append(row + "|")
        lines.append("+" + "---" * game.width + "+")
        mode = f"{BOLD}{YELLOW}CHEAT{ANSI_RST}" if cheat else f"{BOLD}{GREEN}PLAY{ANSI_RST}"
        lines.append(f" {mode} WASD=move P=cheat Q=quit {message}")
        sys.stdout.write("\n".join(lines))
        sys.stdout.flush()


    has_tty = False
    if sys.platform != "win32":
        import tty
        import termios
        try:
            old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
            has_tty = True
        except Exception:
            pass

    sys.stdout.write(HIDE_CURSOR)
    sys.stdout.write(CLEAR)

    game = Game(21, 21)
    cheat = False
    message = ""

    try:
        while True:
            if cheat:
                game.show_cheat()

            draw(game, message, cheat)
            message = ""

            keys = []
            while True:
                key = get_key()
                if key is None:
                    break
                if isinstance(key, bytes):
                    keys.append(key)
                elif isinstance(key, str):
                    keys.append(key.encode())

            w = a = s = d = p = False
            quit_game = False
            for key in keys:
                if key == b"w":
                    w = True
                elif key == b"a":
                    a = True
                elif key == b"s":
                    s = True
                elif key == b"d":
                    d = True
                elif key == b"p":
                    p = True
                elif key == b"q" or key == b"\x1b":
                    quit_game = True

            if quit_game:
                break

            if p:
                cheat = not cheat

            if not cheat:
                result = game.tick(w, a, s, d)
                if result == "W":
                    message = f"{BOLD}{GREEN}YOU WIN!{ANSI_RST}"
                    draw(game, message, cheat)
                    time.sleep(1)
                    break
                elif result == "L":
                    message = f"{BOLD}{RED}YOU LOSE!{ANSI_RST}"
                    draw(game, message, cheat)
                    time.sleep(1)
                    break

            time.sleep(0.1)
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.write(CLEAR)
        sys.stdout.write(HOME)
        if has_tty:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
