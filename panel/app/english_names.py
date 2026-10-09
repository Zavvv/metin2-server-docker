# =============================================================================
#  The official English names of this world's items and monsters, for the
#  panels (Blind and Tieru, 8 October).
#
#  The world's tables know an item or a monster by its Polish name alone
#  (item_proto / mob_proto locale_name), so a panel read in English listed
#  "Dziki Pies", "Wilk", "Alfa Wilk" - in Lostek's database editor, in the
#  drop editor and on the classic panel's pages - although the core has said
#  "Wild Dog", "Wolf" and "Alpha Wolf" to a player of English since 28
#  September. The names are the core's own file: playerbot_names_en.tsv,
#  rendered by tools/generate_english_names.py from Gameforge's English (and
#  this world's own items and monsters by hand), one line a vnum:
#
#      i<TAB>10<TAB>Sword+0<TAB>74bfb680
#
#  "i" an item, "m" a monster or an NPC, and last the FNV-1a of the Polish
#  proto name the English one was matched to (the CP1250 bytes the engine
#  holds). A line names a vnum only while the world still calls it that, the
#  rule playerbot_name_rules.h keeps in the core: the database editor can
#  rename an item, and a renamed item keeps its new Polish name rather than
#  wear the English of what it used to be.
#
#  The file is a panel sibling (files/playerbot_names_en.tsv, the same bytes
#  as linux-port-mt2009/docker/game/playerbot_names_en.tsv, which the
#  generator writes both of), staged into the panel's build context beside
#  this module: the panel container cannot read the game image. Read once,
#  on first use; a panel without it - or with a file it cannot read - names
#  everything in Polish exactly as it did before.
#
#  Only the display and the search change: what the database holds, what an
#  edit shows and writes, and every name a file or a history row is given
#  stay Polish.
# =============================================================================

import os
import threading

FILE_NAME = "playerbot_names_en.tsv"
ITEM = "i"
MOB = "m"

# playerbot_names::NAME_MAX_LEN: longer than any official name, shorter than
# anything a stray line of another file would be.
NAME_MAX_LEN = 48
_HEX = frozenset("0123456789abcdef")


def fnv1a(raw):
    """playerbot_names::HashProtoName over a name's bytes."""
    value = 2166136261
    for byte in raw:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value


def polish_bytes(name, codec="cp1250"):
    """A proto name as the engine holds it: bytes as they came from the
    database, or a decoded name put back into its column's encoding (CP1250
    in this world). None for a name that encoding cannot hold - a name the
    world does not hold either, so no line can be its."""
    if name is None:
        return None
    if isinstance(name, (bytes, bytearray)):
        return bytes(name)
    try:
        return str(name).encode(codec or "cp1250")
    except (LookupError, UnicodeError):
        return None


def parse_line(line):
    """(kind, vnum, name, hash) of one line (bytes or str), or None - for a
    comment, a blank line and anything that is not exactly what the generator
    writes, as playerbot_names::ParseNameLine reads it."""
    if isinstance(line, (bytes, bytearray)):
        try:
            line = bytes(line).decode("ascii")
        except UnicodeDecodeError:
            return None
    line = line.rstrip("\r\n")
    if len(line) < 2 or line[0] not in (ITEM, MOB) or line[1] != "\t":
        return None
    parts = line[2:].split("\t")
    if len(parts) != 3:
        return None
    vnum, name, digest = parts
    if not vnum or any(c not in "0123456789" for c in vnum):
        return None
    number = int(vnum)
    if number <= 0 or number > 100000000:
        return None
    if (not name or len(name) > NAME_MAX_LEN or name[0] == " " or name[-1] == " "
            or any(ord(c) < 0x20 or ord(c) > 0x7E for c in name)):
        return None
    if len(digest) != 8 or any(c not in _HEX for c in digest):
        return None
    return line[0], number, name, int(digest, 16)


class EnglishNames(object):
    """One file's names, read once and kept for the life of the panel (a new
    file comes with a new panel image)."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._lines = None              # {(kind, vnum): (name, hash)}
        self._folded = None             # {kind: [(lowered name, vnum, hash)]}

    def _table(self):
        lines = self._lines
        if lines is not None:
            return lines
        with self._lock:
            if self._lines is None:
                found = {}
                try:
                    with open(self.path, "rb") as handle:
                        for raw in handle:
                            parsed = parse_line(raw)
                            if parsed is not None:
                                found[(parsed[0], parsed[1])] = (parsed[2], parsed[3])
                except OSError:
                    found = {}
                folded = {ITEM: [], MOB: []}
                for (kind, vnum), (name, digest) in sorted(found.items()):
                    folded[kind].append((name.lower(), vnum, digest))
                self._folded = folded
                self._lines = found
            return self._lines

    def available(self):
        return bool(self._table())

    def name(self, kind, vnum, polish, codec="cp1250"):
        """The English name of a vnum the world calls `polish`, or None: no
        line for it, a line matched to another Polish name, or no file."""
        try:
            number = int(vnum)
        except (TypeError, ValueError):
            return None
        hit = self._table().get((kind, number))
        if hit is None:
            return None
        raw = polish_bytes(polish, codec)
        if not raw or fnv1a(raw) != hit[1]:
            return None
        return hit[0]

    def matching(self, kind, text):
        """{vnum: hash} of the lines whose English name holds `text`, any case.
        The caller checks each against the world's current name (the hash)
        before it counts as found."""
        needle = str(text or "").strip().lower()
        if not needle:
            return {}
        self._table()
        return dict((vnum, digest) for name, vnum, digest in (self._folded or {}).get(kind, ())
                    if needle in name)

    def matches_hash(self, digest, polish, codec="cp1250"):
        """Whether `polish` is the name a line of this hash was matched to."""
        raw = polish_bytes(polish, codec)
        return bool(raw) and fnv1a(raw) == digest


def default_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), FILE_NAME)


_DEFAULT = EnglishNames(default_path())


def english_item_name(vnum, polish):
    return _DEFAULT.name(ITEM, vnum, polish)


def english_mob_name(vnum, polish):
    return _DEFAULT.name(MOB, vnum, polish)
