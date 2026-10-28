"""What does "100kb/20kb" mean?  Turning speed words into numbers.

A speed is written "down/up" (or just one number for both), like:

    5/1          5 megabits down, 1 up (how network gear talks)
    0.8/0.16     fractional megabits
    100kb/20kb   kilobytes per second — how downloads display
    10mb/2mb     megabytes per second

There are 8 bits in a byte, so 100 KB/s = 800 kbit/s.
Everything is returned in kilobits per second (kbit/s), which is the
unit the Linux speed meter (tc) speaks.
"""

import re

# unit name -> how many kbit one unit is worth
_UNITS = {
    "": 1000, "m": 1000, "mbit": 1000,            # megabits
    "mb": 8000, "mbyte": 8000, "mbytes": 8000,    # megabytes
    "k": 1, "kbit": 1,                            # kilobits
    "kb": 8, "kbyte": 8, "kbytes": 8,             # kilobytes
}


def _side_to_kbit(side: str) -> int:
    m = re.fullmatch(r"\s*([0-9.]+)\s*([a-zA-Z]*)\s*", side)
    if not m:
        raise ValueError(f"couldn't understand '{side}'")
    value, unit = float(m.group(1)), m.group(2).lower()
    if unit not in _UNITS:
        raise ValueError(f"unknown unit '{unit}' — examples: 5/1 (Mbps), "
                         f"100kb/20kb (kilobytes/s), 500k/100k (kilobits/s)")
    return int(value * _UNITS[unit])


def parse_speed(speed: str) -> tuple:
    """'100kb/20kb' -> (800, 160) kilobits per second (down, up).

    Raises ValueError with a friendly message if the words don't parse.
    """
    if "/" in speed:
        down_s, up_s = speed.split("/", 1)
    else:
        down_s = up_s = speed
    down, up = _side_to_kbit(down_s), _side_to_kbit(up_s)
    if down <= 0 or up <= 0:
        raise ValueError("speeds must be positive — examples: 5/1, 100kb/20kb")
    return down, up


def human_speed(down_kbit: int, up_kbit: int) -> str:
    """Speeds in plain words: network units next to familiar KB/s."""
    def one(kbit: int) -> str:
        kb = kbit / 8
        if kbit >= 1000 and kbit % 1000 == 0:
            return f"{kbit // 1000} Mbps ({kb:.0f} KB/s)"
        return f"{kbit} kbit/s ({kb:.0f} KB/s)"
    return f"{one(down_kbit)} down / {one(up_kbit)} up"
