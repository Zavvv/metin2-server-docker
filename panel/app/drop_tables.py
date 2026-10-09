# -*- coding: utf-8 -*-
"""The chest groups (special_item_group.txt) and the monster drop groups
(mob_drop_item.txt) as the mt2009 game core reads them, for the panel's
editor of the two files (the operator, 7 October).

Pure code: no Flask, no database, no file system. The panel hands it bytes and
the sets of item and monster numbers it read from player.item_proto and
player.mob_proto, and gets bytes, groups and verdicts back.

Why an emulation and not a tidy grammar. Both files are read at every core's
boot by CTextFileLoader (game/src/text_file_loader.cpp) and then by
ITEM_MANAGER::ReadSpecialDropItemFile / ReadMonsterDropItemGroup
(item_manager_read_tables.cpp), and every way they can go wrong ends the boot
of every core (`thecore_shutdown`, `exit(1)` or an uncaught std::out_of_range
from `pTok->at(n)`), or empties a chest whose next opening reads
`m_vecProbs.back()` of an empty vector. So the reader here does what those do,
byte for byte where it matters:

  * CMemoryTextFileLoader::Bind: a CR, an LF or any pair of them ends a line
    (two blank lines in a row are one break), and a byte >= 0x80 takes the
    next byte with it, whatever it is - CP949's double bytes, which is how a
    3-byte UTF-8 Korean group name swallows the CR after it;
  * SplitLine: tokens split on space and tab, a token starting with '"' runs
    to the next '"', and a token starting with '#' that is not "#--#" throws
    the WHOLE line away, tokens before it included;
  * LoadGroup: keys are lowercased, the first occurrence of a key wins
    (emplace), "Group" needs exactly two tokens or the process exits, a key
    line with one token ends its group early and its remaining lines are read
    one level up, and a '}' at the top level ends the file;
  * the readers: entries are the keys "1", "2", ... read until the first
    missing one; a chest line with prob 0 is skipped (AddItem), the kill
    type's line needs four tokens, and so on.

The override the editor saves is group-level, like the operator's Moonlight
chest (special_item_group.moonlight.custom.txt): the groups the operator
changed or added, and the keys of the groups taken out. m2-drop-tables in the
game container merges it over the image's own file before every boot of the
cores - the same algorithm as merge() below, which
tests/drop_tables_merge_test.py holds the two to - so an update that changes
the game's own groups keeps the operator's groups and still brings everything
else.

Every verdict is a Msg with a Polish and an English text (describe()): the
panel speaks both.
"""
import difflib
import hashlib
import re
import unicodedata

FORMAT = 1
FILES = ("special_item_group.txt", "mob_drop_item.txt")
KIND = {"special_item_group.txt": "special", "mob_drop_item.txt": "mob"}
SLUG = {"special_item_group.txt": "chests", "mob_drop_item.txt": "mobs"}
FILE_OF_SLUG = dict((v, k) for k, v in SLUG.items())

# item_length.h: ITEM_DS. A Dragon Stone's proto stands for its whole hundred
# (ClientManagerBoot.cpp, ENABLE_AUTODETECT_VNUMRANGE: dwVnumRange = 99), and
# ITEM_MANAGER::GetTable finds 110003 under 110000.
ITEM_DS = 29

SPECIAL_KEYWORDS = ("exp", "mob", "slow", "drain_hp", "poison", "group", "gold")
SPECIAL_TYPES = ("", "pct", "quest", "special")      # "attr" groups are not edited here
MOB_TYPES = ("kill", "drop", "limit", "thiefgloves")
SPECIAL_MAX_ENTRIES = 1023                            # `k < 1024` in the reader
MOB_MAX_ENTRIES = 255                                 # `k < 256`

# Bounds for a group the editor writes. The game's own files stay inside them
# (measured on the 2.2.74 image: a chest weight of at most 160 and amounts of
# yang up to a million, a percent of at most 100 in a Pct chest, 400 in a
# drop line, a kill weight of 100).
WEIGHT_MAX = 1000000
ITEM_COUNT_MAX = 10000
AMOUNT_MAX = 1000000000
PERCENT_MAX = 10000.0
LEVEL_LIMIT_MAX = 999
KILL_DROP_MAX = 1000000
NAME_RE = re.compile(r"[A-Za-z0-9_.\-]{1,48}")
UINT_RE = re.compile(r"[0-9]{1,10}")
PERCENT_RE = re.compile(r"[0-9]{1,6}(\.[0-9]{1,6})?")

HEADER = b"# m2-drop-override"


# =============================================================================
#  What the checks say, in both of the panel's languages
# =============================================================================
TEXTS = {
    "top_brace": ("a '}}' outside every group ends the file at line {line}",
                  "„}}” poza grupą kończy plik w linii {line}"),
    "group_syntax": ("line {line}: 'Group' needs exactly one name, without spaces - the core exits",
                     "linia {line}: „Group” potrzebuje dokładnie jednej nazwy, bez spacji - rdzeń się wyłącza"),
    "no_value": ("line {line}: a key without a value ends its group early",
                 "linia {line}: klucz bez wartości przedwcześnie kończy grupę"),
    "no_vnum": ("line {line}: a chest group without its Vnum", "linia {line}: grupa skrzyni bez Vnum"),
    "attr_values": ("line {line}: an attribute line needs a type and a value",
                    "linia {line}: linia atrybutu potrzebuje typu i wartości"),
    "no_item_line": ("line {line}: there is no item {item} in item_proto",
                     "linia {line}: nie ma przedmiotu {item} w item_proto"),
    "chest_values": ("line {line}: a chest line needs an item, a count and a probability",
                     "linia {line}: linia skrzyni potrzebuje przedmiotu, ilości i szansy"),
    "chest_empty": ("chest {key} gives nothing, and opening it reads an empty table (the core crashes)",
                    "skrzynia {key} nic nie daje, a jej otwarcie czyta pustą tabelę (rdzeń pada)"),
    "chest_sum": ("chest {key}: the weights add up past 2^31", "skrzynia {key}: wagi sumują się powyżej 2^31"),
    "no_type": ("line {line}: a drop group without its Type", "linia {line}: grupa dropu bez Type"),
    "no_mob": ("line {line}: a drop group without its Mob", "linia {line}: grupa dropu bez Mob"),
    "no_kill_drop": ("line {line}: a kill group without its kill_drop", "linia {line}: grupa kill bez kill_drop"),
    "no_level_limit": ("line {line}: a limit group without its level_limit",
                       "linia {line}: grupa limit bez level_limit"),
    "bad_mob_type": ("line {line}: '{type}' is no drop type (kill, drop, limit, thiefgloves)",
                     "linia {line}: „{type}” to nie typ dropu (kill, drop, limit, thiefgloves)"),
    "drop_count": ("line {line}: a drop line needs a count of at least 1",
                   "linia {line}: linia dropu potrzebuje ilości co najmniej 1"),
    "drop_values": ("line {line}: a {type} line needs {n} values", "linia {line}: linia {type} potrzebuje {n} wartości"),
    "kill_zero": ("line {line}: a kill line's weight must not be 0", "linia {line}: waga linii kill nie może być 0"),
    # The merge's own verdicts (m2-drop-tables gives the same in English).
    "ov_header": ("the first line is not '# m2-drop-override {format} {file}'",
                  "pierwsza linia to nie „# m2-drop-override {format} {file}”"),
    "ov_nul": ("a NUL byte in the file", "bajt NUL w pliku"),
    "ov_remove_late": ("a '# remove' line after the first group (line {line})",
                       "linia „# remove” po pierwszej grupie (linia {line})"),
    "ov_remove_key": ("a bad '# remove' key (line {line})", "zły klucz „# remove” (linia {line})"),
    "ov_twice": ("the key {key} twice", "klucz {key} dwa razy"),
    "ov_outside": ("text outside a group (line {line})", "tekst poza grupą (linia {line})"),
    "ov_open": ("a group without its closing '}}'", "grupa bez zamykającego „}}”"),
    "ov_head": ("a Group line needs exactly one name (line {line})",
                "linia Group potrzebuje dokładnie jednej nazwy (linia {line})"),
    "ov_brace": ("a group whose second line is not '{{' (line {line})",
                 "grupa, której druga linia to nie „{{” (linia {line})"),
    "ov_nokey": ("a group without its key (line {line})", "grupa bez klucza (linia {line})"),
    "ov_file": ("the override file: {why}", "plik z Twoimi grupami: {why}"),
    # A group the operator writes.
    "name": ("the group's name: letters, digits, _ . - only, at most 48",
             "nazwa grupy: tylko litery, cyfry, _ . -, najwyżej 48 znaków"),
    "name_chars": ("the group's name cannot start with {{ }} # \" or hold a space",
                   "nazwa grupy nie może zaczynać się od {{ }} # \" ani mieć spacji"),
    "vnum": ("the chest's number must be a whole number from 1", "numer skrzyni musi być liczbą całkowitą od 1"),
    "special_type": ("the chest type must be normal, Pct, Quest or special",
                     "typ skrzyni musi być zwykły, Pct, Quest albo special"),
    "chest_no_lines": ("a chest with no line gives nothing, and opening it crashes the core",
                       "skrzynia bez linii nic nie daje, a jej otwarcie wywraca rdzeń"),
    "too_many": ("at most {n} lines", "najwyżej {n} linii"),
    "mob_count": ("line {line}: 'mob' takes a monster's number as its count, and {value} is none",
                  "linia {line}: „mob” bierze numer potwora jako ilość, a {value} nim nie jest"),
    "amount": ("line {line}: the amount must be 1..{high}", "linia {line}: kwota musi być od 1 do {high}"),
    "count_whole": ("line {line}: the count must be a whole number", "linia {line}: ilość musi być liczbą całkowitą"),
    "no_chest_ref": ("line {line}: {item} names no chest group of this file",
                     "linia {line}: {item} nie wskazuje żadnej grupy skrzyni w tym pliku"),
    "count": ("line {line}: the count must be 1..{high}", "linia {line}: ilość musi być od 1 do {high}"),
    "no_item": ("line {line}: there is no item {item} in item_proto", "linia {line}: nie ma przedmiotu {item} w item_proto"),
    "prob": ("line {line}: the probability must be a whole number 0..{high}",
             "linia {line}: szansa musi być liczbą całkowitą od 0 do {high}"),
    "rare": ("line {line}: the rare chance must be 0..100", "linia {line}: szansa na rzadki musi być od 0 do 100"),
    "all_zero": ("every line has probability 0: the chest gives nothing and its opening crashes the core",
                 "każda linia ma szansę 0: skrzynia nic nie daje, a jej otwarcie wywraca rdzeń"),
    "sum": ("the weights add up past 2^31", "wagi sumują się powyżej 2^31"),
    "no_monster": ("there is no monster {mob} in mob_proto", "nie ma potwora {mob} w mob_proto"),
    "mob_type": ("the type must be kill, drop, limit or thiefgloves", "typ musi być kill, drop, limit albo thiefgloves"),
    "kill_drop": ("kill_drop must be 0..{high}", "kill_drop musi być od 0 do {high}"),
    "level_limit": ("level_limit must be 1..{high}", "level_limit musi być od 1 do {high}"),
    "mob_no_lines": ("a group with no line drops nothing - remove the group instead",
                     "grupa bez linii nic nie daje - zamiast tego usuń grupę"),
    "bad_chest_number": ("line {line}: {item} is no chest group number", "linia {line}: {item} to nie numer grupy skrzyni"),
    "weight": ("line {line}: a kill line's weight must be 1..{high}", "linia {line}: waga linii kill musi być od 1 do {high}"),
    "kill_rare": ("line {line}: a kill line needs its rare chance, 0..100",
                  "linia {line}: linia kill potrzebuje szansy na rzadki, od 0 do 100"),
    "percent": ("line {line}: the percent must be a number 0..{high}, with a dot",
                "linia {line}: procent musi być liczbą od 0 do {high}, z kropką"),
    "only_kill_rare": ("line {line}: only a kill line has a rare chance", "linia {line}: tylko linia kill ma szansę na rzadki"),
    "cell": ("a value with a space, a quote, a brace, a # or a letter outside ASCII",
             "wartość ze spacją, cudzysłowem, klamrą, # albo literą spoza ASCII"),
    # The verdict on the whole change.
    "nothing_to_remove": ("{key} is not among the game's own groups: nothing to take out",
                          "{key} nie jest grupą gry: nie ma czego usuwać"),
    "game_stops": ("the game would stop reading the merged file: {why}", "gra przestałaby czytać połączony plik: {why}"),
    "split": ("the merged file's groups are not the ones the game reads ({engine} to the game, {merge} to the merge)",
              "grupy połączonego pliku to nie te, które czyta gra ({engine} dla gry, {merge} dla scalania)"),
    "written_twice": ("the group is written {n} times", "grupa jest zapisana {n} razy"),
    "dropped_lines": ("{n} line(s) the game never read (a gap in the numbering) are left out",
                      "{n} linii, których gra nigdy nie czytała (przerwa w numeracji), zostaje pominiętych"),
    "one_of_many": ("the game's file had this group {n} times; one is written",
                    "plik gry miał tę grupę {n} razy; zapisana zostaje jedna"),
    "sig_use": ("items of a Quest group or of a group numbered under 30000 are used under the group's number "
                "(a quest's sig_use) - check the quests that use them",
                "przedmioty grupy Quest albo grupy o numerze poniżej 30000 są używane pod numerem grupy "
                "(sig_use questa) - sprawdź questy, które ich używają"),
    "names_removed": ("{key} still names the removed group {item}", "{key} nadal wskazuje usuniętą grupę {item}"),
}


class Msg(object):
    """A verdict: a code and its numbers, said in either language."""
    __slots__ = ("code", "args")

    def __init__(self, code, **args):
        self.code = code
        self.args = args

    def __str__(self):
        return describe(self, "en")

    def __repr__(self):
        return "Msg(%r, %r)" % (self.code, self.args)

    def __eq__(self, other):
        return isinstance(other, Msg) and (self.code, self.args) == (other.code, other.args)

    def __hash__(self):
        return hash((self.code, tuple(sorted(self.args.items()))))


def describe(msg, lang="en"):
    if not isinstance(msg, Msg):
        return str(msg)
    texts = TEXTS.get(msg.code)
    if texts is None:
        return msg.code
    template = texts[1] if lang == "pl" else texts[0]
    args = {}
    for key, value in msg.args.items():
        args[key] = describe(value, lang) if isinstance(value, Msg) else value
    try:
        return template.format(**args)
    except (KeyError, IndexError, ValueError):
        return texts[0]


class OverrideError(ValueError):
    """An override file m2-drop-tables would refuse."""

    def __init__(self, msg):
        ValueError.__init__(self, str(msg))
        self.msg = msg


# =============================================================================
#  The engine's reader
# =============================================================================
_BIND_SPECIAL = re.compile(rb"[\r\n\x80-\xff]")


def engine_lines(raw):
    """CMemoryTextFileLoader::Bind, byte for byte (the runs between the bytes
    it treats specially copied whole)."""
    lines = []
    cur = bytearray()
    pos, size = 0, len(raw)
    while pos < size:
        m = _BIND_SPECIAL.search(raw, pos)
        if m is None:
            cur += raw[pos:]
            break
        i = m.start()
        cur += raw[pos:i]
        if raw[i] in (10, 13):
            pos = i + 1
            if pos < size and raw[pos] in (10, 13):
                pos += 1
            lines.append(bytes(cur))
            cur = bytearray()
        else:
            # `stLine.append(c_pcBuf + (pos-1), 2); ++pos;` - the next byte goes
            # with it, a CR or an LF included.
            cur += raw[i:i + 2]
            pos = i + 2
    lines.append(bytes(cur))
    return lines


_DELIM = b" \t"


def split_line(line):
    """CMemoryTextFileLoader::SplitLine(" \\t"): a list of tokens, or None for
    a line the loader skips (blank, a '#' token, an unterminated quote)."""
    tokens = []
    base, size = 0, len(line)
    while True:
        begin = base
        while begin < size and line[begin] in _DELIM:
            begin += 1
        if begin >= size:
            return None
        if line[begin] == 0x23 and line[begin:begin + 4] != b"#--#":
            return None
        if line[begin] == 0x22:
            begin += 1
            end = line.find(b'"', begin)
            if end < 0:
                return None
            tokens.append(line[begin:end])
            base = end + 1
        else:
            end = begin
            while end < size and line[end] not in _DELIM:
                end += 1
            tokens.append(line[begin:end])
            base = end
        rest = base
        while rest < size and line[rest] in _DELIM:
            rest += 1
        if rest >= size or base >= size:
            break
    return tokens


def ascii_lower(value):
    return bytes(c + 32 if 65 <= c <= 90 else c for c in value)


_NUMBER = re.compile(rb"[ \t\n\v\f\r]*([+-]?)([0-9]*)")


def c_strtol(value):
    """strtol(in, NULL, 10) on the 32-bit build (long is 32 bits): leading
    blanks, a sign, the digits that follow; clamped to LONG_MIN..LONG_MAX."""
    m = _NUMBER.match(value or b"")
    digits = m.group(2)
    if not digits:
        return 0
    n = int(digits)
    if m.group(1) == b"-":
        n = -n
    return max(-2 ** 31, min(2 ** 31 - 1, n))


def c_strtoul(value):
    """strtoul on the 32-bit build: a minus wraps, an overflow is ULONG_MAX."""
    m = _NUMBER.match(value or b"")
    digits = m.group(2)
    if not digits:
        return 0
    n = int(digits)
    if n > 2 ** 32 - 1:
        return 2 ** 32 - 1
    if m.group(1) == b"-":
        n = (-n) % 2 ** 32
    return n


def c_atof(value):
    m = re.match(rb"[ \t\n\v\f\r]*[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?", value or b"")
    if not m:
        return 0.0
    try:
        return float(m.group(0))
    except ValueError:
        return 0.0


class Node(object):
    __slots__ = ("name", "parent", "children", "keys", "first", "last", "ended")

    def __init__(self, name, parent, first):
        self.name = name
        self.parent = parent
        self.children = []
        self.keys = {}          # lowered key -> (values, line index); first wins
        self.first = first      # index of the "Group" line
        self.last = None        # index of the line that ended it
        self.ended = None       # "brace", "value", "eof"


def load_tree(raw):
    """CTextFileLoader::Load/LoadGroup. Returns (root, lines, problems); a
    problem is (kind, line index, Msg) with kind "exit" (the process exits),
    "value" (a key without a value cut its group short) or "top" (a '}' at the
    top level ended the file)."""
    lines = engine_lines(raw)
    problems = []
    root = Node(b"global", None, -1)
    state = {"i": 0, "exit": False}

    def load_group(node):
        while state["i"] < len(lines):
            i = state["i"]
            tokens = split_line(lines[i])
            if tokens is None:
                state["i"] += 1
                continue
            first = ascii_lower(tokens[0])
            if first[:1] == b"{":
                state["i"] += 1
                continue
            if first[:1] == b"}":
                node.last, node.ended = i, "brace"
                if node.parent is None:
                    problems.append(("top", i, Msg("top_brace", line=i + 1)))
                return
            if first == b"group":
                if len(tokens) != 2:
                    problems.append(("exit", i, Msg("group_syntax", line=i + 1)))
                    state["exit"] = True
                    return
                child = Node(ascii_lower(tokens[1]), node, i)
                node.children.append(child)
                state["i"] += 1
                load_group(child)
                if state["exit"]:
                    return
                state["i"] += 1
                continue
            if first == b"list":
                # Neither file uses a list; skipped the way LoadGroup reads one.
                if len(tokens) == 2:
                    state["i"] += 1
                    while state["i"] < len(lines):
                        sub = split_line(lines[state["i"]])
                        if sub is not None and sub[0][:1] == b"}":
                            break
                        state["i"] += 1
                state["i"] += 1
                continue
            if len(tokens) == 1:
                problems.append(("value", i, Msg("no_value", line=i + 1)))
                node.last, node.ended = i, "value"
                return
            node.keys.setdefault(first, (tokens[1:], i))
            state["i"] += 1
        node.ended = node.ended or "eof"

    load_group(root)
    return root, lines, problems


def make_item_exists(item_vnums, ds_vnums=()):
    """ITEM_MANAGER::GetTable(vnum) != NULL, from the proto's numbers."""
    items = frozenset(item_vnums)
    ds = frozenset(ds_vnums)

    def exists(vnum):
        return vnum in items or (vnum - vnum % 100) in ds
    return exists


class Loaded(object):
    """What one file's reader made of it."""

    def __init__(self):
        self.groups = []       # dicts, in file order
        self.fatal = []        # (line index, Msg): the boot of every core stops
        self.hazards = []      # (line index, Msg): loads, then misbehaves


def _entries(node, limit):
    """The numbered lines the reader takes, and the ones it never reaches."""
    taken = []
    for k in range(1, limit + 1):
        hit = node.keys.get(str(k).encode())
        if hit is None:
            break
        taken.append((k, hit[0], hit[1]))
    reached = set(str(k).encode() for k, _v, _i in taken)
    skipped = sorted(i for key, (_v, i) in node.keys.items()
                     if re.fullmatch(rb"[0-9]+", key) and key not in reached)
    return taken, skipped


def _text(value):
    return value.decode("utf-8", "replace")


def _problems(out, problems):
    for kind, i, msg in problems:
        (out.fatal if kind in ("exit", "value") else out.hazards).append((i, msg))
    return any(kind == "exit" for kind, _i, _m in problems)


def read_special(raw, item_exists):
    """ITEM_MANAGER::ReadSpecialDropItemFile."""
    root, _lines, problems = load_tree(raw)
    out = Loaded()
    if _problems(out, problems):
        return out
    for node in root.children:
        group = {"name": node.name, "line": node.first, "vnum": None, "type": "",
                 "entries": [], "skipped": [], "attr": False}
        vnum = node.keys.get(b"vnum")
        if not vnum or not vnum[0]:
            out.fatal.append((node.first, Msg("no_vnum", line=node.first + 1)))
            return out
        group["vnum"] = c_strtol(vnum[0][0])
        typ = node.keys.get(b"type")
        if typ and typ[0]:
            group["type"] = ascii_lower(typ[0][0]).decode("latin1")
        taken, group["skipped"] = _entries(node, SPECIAL_MAX_ENTRIES)
        if group["type"] == "attr":
            group["attr"] = True
            for k, values, i in taken:
                if len(values) < 2:
                    out.fatal.append((i, Msg("attr_values", line=i + 1)))
                    return out
                group["entries"].append({"index": k, "line": i, "name": values[0],
                                         "count": c_strtol(values[1]), "prob": 1, "rare": 0,
                                         "special": False, "keyword": None, "vnum": 0})
            out.groups.append(group)
            continue
        for k, values, i in taken:
            name = values[0]
            keyword = name.decode("latin1") if name.decode("latin1") in SPECIAL_KEYWORDS else None
            special = False
            vnum_value = 0
            if keyword is None and name[:1] == b"s":
                special = True
                vnum_value = c_strtoul(name[1:])
            elif keyword is None:
                vnum_value = c_strtoul(name) if name else 0
                if not item_exists(vnum_value):
                    out.fatal.append((i, Msg("no_item_line", line=i + 1, item=_text(name))))
                    return out
            if len(values) < 3:
                out.fatal.append((i, Msg("chest_values", line=i + 1)))
                return out
            group["entries"].append({
                "index": k, "line": i, "name": name, "keyword": keyword, "special": special,
                "vnum": vnum_value, "count": c_strtol(values[1]), "prob": c_strtol(values[2]),
                "rare": c_strtol(values[3]) if len(values) > 3 else 0})
        out.groups.append(group)
    for group in out.groups:
        if group["attr"]:
            continue
        live = [e for e in group["entries"] if e["prob"]]
        if not live:
            out.hazards.append((group["line"], Msg("chest_empty", key=group["vnum"])))
        elif group["type"] != "pct" and sum(e["prob"] for e in live) > 2 ** 31 - 1:
            out.hazards.append((group["line"], Msg("chest_sum", key=group["vnum"])))
    return out


def read_mob(raw, item_exists):
    """ITEM_MANAGER::ReadMonsterDropItemGroup."""
    root, _lines, problems = load_tree(raw)
    out = Loaded()
    if _problems(out, problems):
        return out
    for node in root.children:
        typ = node.keys.get(b"type")
        if not typ or not typ[0]:
            out.fatal.append((node.first, Msg("no_type", line=node.first + 1)))
            return out
        mob = node.keys.get(b"mob")
        if not mob or not mob[0]:
            out.fatal.append((node.first, Msg("no_mob", line=node.first + 1)))
            return out
        # The type's value is compared as written: "Kill" is no type at all.
        kind = typ[0][0].decode("latin1")
        group = {"name": node.name, "line": node.first, "mob": c_strtol(mob[0][0]), "type": kind,
                 "kill_drop": 1, "level_limit": 0, "entries": [], "skipped": []}
        if kind == "kill":
            kd = node.keys.get(b"kill_drop")
            if not kd or not kd[0]:
                out.fatal.append((node.first, Msg("no_kill_drop", line=node.first + 1)))
                return out
            group["kill_drop"] = c_strtol(kd[0][0])
        if kind == "limit":
            ll = node.keys.get(b"level_limit")
            if not ll or not ll[0]:
                out.fatal.append((node.first, Msg("no_level_limit", line=node.first + 1)))
                return out
            group["level_limit"] = c_strtol(ll[0][0])
        if group["kill_drop"] == 0:
            # Read and set aside: the reader `continue`s before its lines.
            out.groups.append(group)
            continue
        if kind not in MOB_TYPES:
            out.fatal.append((node.first, Msg("bad_mob_type", line=node.first + 1, type=kind)))
            return out
        taken, group["skipped"] = _entries(node, MOB_MAX_ENTRIES)
        need = 4 if kind == "kill" else 3
        for k, values, i in taken:
            name = values[0]
            special = kind == "drop" and name[:1] == b"s"
            vnum_value = c_strtoul(name[1:] if special else name) if name else 0
            if not special and not item_exists(vnum_value):
                out.fatal.append((i, Msg("no_item_line", line=i + 1, item=_text(name))))
                return out
            if len(values) < 2 or c_strtol(values[1]) < 1:
                out.fatal.append((i, Msg("drop_count", line=i + 1)))
                return out
            if len(values) < need:
                out.fatal.append((i, Msg("drop_values", line=i + 1, type=kind, n=need)))
                return out
            entry = {"index": k, "line": i, "name": name, "special": special, "vnum": vnum_value,
                     "count": c_strtol(values[1]), "keyword": None}
            if kind == "kill":
                entry["prob"] = c_strtol(values[2])
                if entry["prob"] == 0:
                    out.fatal.append((i, Msg("kill_zero", line=i + 1)))
                    return out
                entry["rare"] = max(0, min(100, c_strtol(values[3])))
            else:
                entry["prob"] = c_atof(values[2])
                entry["rare"] = 0
            group["entries"].append(entry)
        out.groups.append(group)
    return out


def read_engine(file_name, raw, item_exists):
    if KIND[file_name] == "special":
        return read_special(raw, item_exists)
    return read_mob(raw, item_exists)


# =============================================================================
#  Blocks: the splitter m2-drop-tables merges with
# =============================================================================
def _strip_cr(line):
    """`sub(/\\r$/, "", l)`: one CR off the end, as m2-drop-tables does."""
    return line[:-1] if line.endswith(b"\r") else line


def _words(line):
    """awk's default field split (blanks only) of a line with its CR taken off."""
    return [w for w in re.split(rb"[ \t]+", _strip_cr(line)) if w]


def _ignored(words):
    return any(w[:1] == b"#" and w[:4] != b"#--#" for w in words)


def raw_lines(raw):
    """awk's records: split on LF, no empty last record after a final LF."""
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return lines


def join_lines(lines):
    return b"".join(line + b"\n" for line in lines)


def block_key(file_name, lines):
    """The key of a block as m2-drop-tables computes it, or None: a chest's
    Vnum, a monster group's Mob and Type."""
    first = {}
    for line in lines[1:]:
        w = _words(line)
        if len(w) < 2 or _ignored(w):
            continue
        k = ascii_lower(w[0])
        if k not in first:
            first[k] = w[1]
    if KIND[file_name] == "special":
        if b"vnum" not in first:
            return None
        return str(c_strtol(first[b"vnum"]))
    if b"mob" not in first or b"type" not in first:
        return None
    return "%d %s" % (c_strtol(first[b"mob"]), first[b"type"].decode("latin1"))


def split_blocks(file_name, raw):
    """The file as ("text", [lines]) and ("block", [lines], key) parts, lines
    without their LF. A block runs from a top-level "Group" line to the '}'
    line that closes it, nested groups counted; ("open", ...) is one the file
    ends inside."""
    parts = []
    text = []
    block = None
    depth = 0
    for line in raw_lines(raw):
        w = _words(line)
        live = bool(w) and not _ignored(w)
        if block is None:
            if live and ascii_lower(w[0]) == b"group":
                if text:
                    parts.append(("text", text))
                    text = []
                block = [line]
                depth = 1
            else:
                text.append(line)
            continue
        block.append(line)
        if live and ascii_lower(w[0]) == b"group":
            depth += 1
        elif live and w[0][:1] == b"}":
            depth -= 1
            if depth == 0:
                parts.append(("block", block, block_key(file_name, block)))
                block = None
    if block is not None:
        parts.append(("open", block, block_key(file_name, block)))
    if text:
        parts.append(("text", text))
    return parts


# =============================================================================
#  The override file
# =============================================================================
class Override(object):
    def __init__(self, file_name, removes=(), blocks=()):
        self.file_name = file_name
        self.removes = list(removes)        # keys, in order
        self.blocks = list(blocks)          # (key, [lines])

    def keys(self):
        return [k for k, _l in self.blocks]

    def touched(self):
        return list(dict.fromkeys(self.removes + self.keys()))

    def empty(self):
        return not self.removes and not self.blocks


def normalise_key(file_name, text):
    """A key as typed or read ("50011", "103 drop") in the form block_key
    gives, or None."""
    words = [w for w in re.split(r"[ \t]+", str(text or "")) if w]
    if not words or not re.fullmatch(r"-?[0-9]{1,10}", words[0]):
        return None
    number = c_strtol(words[0].encode("ascii"))
    if KIND[file_name] == "special":
        return str(number) if len(words) == 1 else None
    if len(words) != 2 or not re.fullmatch(r"[A-Za-z]{1,16}", words[1]):
        return None
    return "%d %s" % (number, words[1])


def parse_override(file_name, raw):
    """The panel's override, read the way m2-drop-tables reads it. Raises
    OverrideError with the reason it would give."""
    lines = raw_lines(raw)
    if not lines or _strip_cr(lines[0]) != HEADER + b" %d %s" % (FORMAT, file_name.encode()):
        raise OverrideError(Msg("ov_header", format=FORMAT, file=file_name))
    if b"\x00" in raw:
        raise OverrideError(Msg("ov_nul"))
    removes = []
    blocks = []
    seen = set()
    started = False
    number = 0
    for part in split_blocks(file_name, raw):
        if part[0] == "text":
            for line in part[1]:
                number += 1
                if number == 1:
                    continue
                w = _words(line)
                if not w:
                    continue
                if w[0] == b"#" and len(w) >= 2 and w[1] == b"remove":
                    if started:
                        raise OverrideError(Msg("ov_remove_late", line=number))
                    key = None
                    if len(w) >= 3 and re.fullmatch(rb"-?[0-9]{1,10}", w[2]):
                        if KIND[file_name] == "special" and len(w) == 3:
                            key = str(c_strtol(w[2]))
                        elif KIND[file_name] == "mob" and len(w) == 4:
                            key = "%d %s" % (c_strtol(w[2]), w[3].decode("latin1"))
                    if key is None:
                        raise OverrideError(Msg("ov_remove_key", line=number))
                    if key in seen:
                        raise OverrideError(Msg("ov_twice", key=key))
                    seen.add(key)
                    removes.append(key)
                    continue
                if w[0][:1] == b"#":
                    continue
                raise OverrideError(Msg("ov_outside", line=number))
            continue
        started = True
        kind, block, key = part
        first = number + 1
        number += len(block)
        # In m2-drop-tables' order: the Group line, the brace, the end.
        if len(_words(block[0])) != 2:
            raise OverrideError(Msg("ov_head", line=first))
        if len(block) >= 2 and _words(block[1]) != [b"{"]:
            raise OverrideError(Msg("ov_brace", line=first + 1))
        if kind == "open":
            raise OverrideError(Msg("ov_open"))
        if len(block) < 2:
            raise OverrideError(Msg("ov_brace", line=first + 1))
        if key is None:
            raise OverrideError(Msg("ov_nokey", line=number))
        if key in seen:
            raise OverrideError(Msg("ov_twice", key=key))
        seen.add(key)
        blocks.append((key, block))
    return Override(file_name, removes, blocks)


def render_override(override, base_sha256=""):
    out = [HEADER + b" %d %s" % (FORMAT, override.file_name.encode()),
           b"# base " + base_sha256.encode("ascii"),
           b"# The operator's groups for this file, written by the panel's editor.",
           b"# m2-drop-tables merges them over the image's own file before every boot."]
    for key in override.removes:
        out.append(b"# remove " + key.encode("latin1"))
    text = b"".join(line + b"\r\n" for line in out)
    for _key, lines in override.blocks:
        text += join_lines(lines)
    return text


def merge(file_name, original, override_raw):
    """The effective file: the image's own with the operator's group in place
    of the first group with its key (the others of that key dropped), the
    removed keys gone and the new keys appended. m2-drop-tables does exactly
    this, line for line."""
    override = parse_override(file_name, override_raw)
    by_key = dict(override.blocks)
    removed = set(override.removes)
    done = set()
    out = []
    for part in split_blocks(file_name, original):
        if part[0] in ("text", "open"):
            out.extend(part[1])
            continue
        _kind, lines, key = part
        if key is not None and key in by_key:
            if key not in done:
                out.extend(by_key[key])
                done.add(key)
            continue
        if key is not None and key in removed:
            continue
        out.extend(lines)
    for key, lines in override.blocks:
        if key not in done:
            out.extend(lines)
    return join_lines(out)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def receipt(file_name, override_raw, base_sha256, admin, saved_at, counts):
    """The file beside the override that says the panel checked these bytes.
    m2-drop-tables installs nothing whose bytes it does not match."""
    admin = re.sub(r"[^A-Za-z0-9_.@\- ]", "_", str(admin))[:48]
    lines = ["format=%d" % FORMAT, "file=%s" % file_name, "sha256=%s" % sha256(override_raw),
             "base_sha256=%s" % base_sha256, "saved_at=%d" % int(saved_at), "admin=%s" % admin,
             "replaced=%d" % counts.get("replaced", 0), "added=%d" % counts.get("added", 0),
             "removed=%d" % counts.get("removed", 0)]
    return ("\n".join(lines) + "\n").encode("ascii")


def parse_kv(raw):
    """key=value lines (the receipt, the status the game writes)."""
    out = {}
    for line in (raw or b"").decode("utf-8", "replace").splitlines():
        line = line.rstrip("\r")
        if "=" in line:
            key, value = line.split("=", 1)
            out.setdefault(key.strip(), value)
    return out


# =============================================================================
#  The editor's groups
# =============================================================================
class Entry(object):
    """One line of a group as the editor shows it: the item (a number, a
    special keyword or s<chest>), and its numbers as written."""
    __slots__ = ("item", "count", "prob", "rare", "comment")

    def __init__(self, item, count, prob, rare="", comment=b""):
        self.item = item            # str: "27001", "gold", "s10901"
        self.count = count          # str
        self.prob = prob            # str
        self.rare = rare            # str ("" = not written)
        self.comment = comment      # bytes after the dashes (kept as written)

    def as_tuple(self):
        return (self.item, self.count, self.prob, self.rare)


class Group(object):
    """A group the editor shows: for a chest its Vnum and Type, for a monster
    its Mob, Type and kill_drop / level_limit. `blocks` is how many blocks the
    file holds under the key (the game reads the first for a chest, a kill, a
    limit or a thief-gloves group, and all of them for a drop group)."""

    def __init__(self, file_name, key, name, fields, entries, raw_blocks=(), extra=()):
        self.file_name = file_name
        self.kind = KIND[file_name]
        self.key = key
        self.name = name                # bytes, as written
        self.fields = dict(fields)      # special: vnum, type, vnum_comment; mob: mob, type, kill_drop, level_limit, mob_comment
        self.entries = list(entries)
        self.raw_blocks = list(raw_blocks)
        self.extra = list(extra)        # lines kept as written (comments, commented-out lines)
        self.skipped = []               # numbered lines the game never reaches

    @property
    def blocks(self):
        return len(self.raw_blocks)

    def raw(self):
        return b"".join(join_lines(b) for b in self.raw_blocks)


def _comment_of(line, words_used):
    """What follows the values on a line: the rest of it after `words_used`
    words, without the dashes it starts with ("-- Pierscien", and the
    package's odd "- Biala Perla")."""
    rest = _strip_cr(line)
    pos = 0
    for _n in range(words_used):
        while pos < len(rest) and rest[pos] in _DELIM:
            pos += 1
        while pos < len(rest) and rest[pos] not in _DELIM:
            pos += 1
    return rest[pos:].strip(b" \t").lstrip(b"-").strip(b" \t")


def _block_group(file_name, key, lines):
    """One block read by the engine's own loader, as the editor's fields."""
    root, elines, _problems = load_tree(join_lines(lines))
    if not root.children:
        return None
    node = root.children[0]
    name_words = _words(lines[0])
    name = name_words[1] if len(name_words) > 1 else b""
    kind = KIND[file_name]
    fields = {}
    if kind == "special":
        v = node.keys.get(b"vnum")
        fields["vnum"] = v[0][0].decode("latin1") if v and v[0] else ""
        fields["vnum_comment"] = _comment_of(elines[v[1]], 2) if v else b""
        t = node.keys.get(b"type")
        fields["type"] = t[0][0].decode("latin1") if t and t[0] else ""
        limit = SPECIAL_MAX_ENTRIES
    else:
        for k in (b"mob", b"type", b"kill_drop", b"level_limit"):
            hit = node.keys.get(k)
            fields[k.decode()] = hit[0][0].decode("latin1") if hit and hit[0] else ""
        # What the reader takes: kill_drop of a kill group, level_limit of a
        # limit group. The package writes a Level_limit into a few drop
        # groups too, where nothing reads it, and the editor does not show it.
        if fields["type"] != "kill":
            fields["kill_drop"] = ""
        if fields["type"] != "limit":
            fields["level_limit"] = ""
        m = node.keys.get(b"mob")
        fields["mob_comment"] = _comment_of(elines[m[1]], 2) if m else b""
        limit = MOB_MAX_ENTRIES
    taken, skipped = _entries(node, limit)
    entries = []
    # A fourth number is the rare chance of a chest's and a kill group's line;
    # the other drop types never read it, so it is not carried into the editor.
    rare_read = kind == "special" or fields.get("type") == "kill"
    for _k, values, i in taken:
        item = values[0].decode("latin1")
        count = values[1].decode("latin1") if len(values) > 1 else ""
        prob = values[2].decode("latin1") if len(values) > 2 else ""
        rare = ""
        consumed = min(len(values), 3)
        if len(values) > 3 and re.fullmatch(rb"[+-]?[0-9]+", values[3]):
            consumed = 4
            if rare_read:
                rare = values[3].decode("latin1")
        entries.append(Entry(item, count, prob, rare, _comment_of(elines[i], 1 + consumed)))
    extra = []
    # Comments and commented-out lines are kept when the group is written
    # again; the keys and the numbered lines are written from the fields.
    for line in lines[1:-1]:
        w = _words(line)
        if w and (w[0][:1] == b"#" or w[0].startswith(b"--")):
            extra.append(_strip_cr(line))
    group = Group(file_name, key, name, fields, entries, [lines], extra)
    group.skipped = [elines[i] for i in skipped]
    return group


def logical_groups(file_name, raw):
    """The file as the editor's groups, in file order, one per key."""
    groups = []
    by_key = {}
    for part in split_blocks(file_name, raw):
        if part[0] != "block" or part[2] is None:
            continue
        _kind, lines, key = part
        if key in by_key:
            group = by_key[key]
            group.raw_blocks.append(lines)
            if KIND[file_name] == "mob" and group.fields.get("type") == "drop":
                more = _block_group(file_name, key, lines)
                if more is not None:
                    group.entries.extend(more.entries)
                    group.extra.extend(more.extra)
                    group.skipped.extend(more.skipped)
            continue
        group = _block_group(file_name, key, lines)
        if group is None:
            continue
        by_key[key] = group
        groups.append(group)
    return groups


_FOLD = {u"ł": "l", u"Ł": "L", u"ß": "ss", u"æ": "ae", u"Æ": "AE", u"ø": "o", u"Ø": "O", u"đ": "d", u"Đ": "D"}


def ascii_comment(text):
    """An item's name as a comment the reader cannot split: ASCII, no '#',
    no quote. A 3-byte UTF-8 letter would carry the next byte into its token
    (Bind), so none is written."""
    text = "".join(_FOLD.get(c, c) for c in str(text or ""))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9 ()+.,:/'_-]", "", text).strip()
    return text[:60].encode("ascii")


def safe_comment(text):
    """A kept comment with nothing the reader acts on: a token starting with
    '#' throws its whole line away (SplitLine), one starting with '"' runs on
    to the next quote."""
    return (text or b"").replace(b"#", b"").replace(b'"', b"").replace(b"\r", b"").strip(b" \t")


def render_group(group):
    """A group written the way the game's own groups are: tabs, CRLF, the
    entries numbered from one, every comment kept."""
    t = b"\t"
    out = [b"Group" + t + group.name, b"{"]
    f = group.fields
    if group.kind == "special":
        line = t + b"Vnum" + t + f["vnum"].encode("latin1")
        if safe_comment(f.get("vnum_comment")):
            line += t + b"-- " + safe_comment(f["vnum_comment"])
        out.append(line)
        if f.get("type"):
            out.append(t + b"Type" + t + f["type"].encode("latin1"))
    else:
        line = t + b"Mob" + t + f["mob"].encode("latin1")
        if safe_comment(f.get("mob_comment")):
            line += t + b"-- " + safe_comment(f["mob_comment"])
        out.append(line)
        out.append(t + b"Type" + t + f["type"].encode("latin1"))
        if f["type"] == "kill":
            out.append(t + b"kill_drop" + t + f["kill_drop"].encode("latin1"))
        if f["type"] == "limit":
            out.append(t + b"level_limit" + t + f["level_limit"].encode("latin1"))
    for n, e in enumerate(group.entries, start=1):
        cells = [str(n), e.item, e.count, e.prob]
        if e.rare != "":
            cells.append(e.rare)
        line = t + t.join(c.encode("latin1") for c in cells)
        if safe_comment(e.comment):
            line += t + b"-- " + safe_comment(e.comment)
        out.append(line)
    for line in group.extra:
        out.append(t + line.lstrip(b" \t"))
    out.append(b"}")
    return [line + b"\r" for line in out]


# =============================================================================
#  Checks of a group the operator wrote
# =============================================================================
def _uint(value, low, high):
    return bool(UINT_RE.fullmatch(value or "")) and low <= int(value) <= high


def check_group(group, item_exists, mob_exists, special_keys, is_new=False):
    """The strict rules for a group the editor writes: a list of Msg, empty
    when the group may be saved. The game's own groups are held to what the
    engine does instead (read_engine); a group the operator only edits keeps
    its name as the game's file has it, Korean bytes and all."""
    problems = []
    f = group.fields
    name = group.name
    if is_new and not NAME_RE.fullmatch(name.decode("latin1")):
        problems.append(Msg("name"))
    if not name or name[:1] in (b"{", b"}", b"#", b'"') or b" " in name or b"\t" in name:
        problems.append(Msg("name_chars"))
    if group.kind == "special":
        if not _uint(f.get("vnum", ""), 1, 2 ** 31 - 1):
            problems.append(Msg("vnum"))
        typ = (f.get("type") or "").lower()
        if typ not in SPECIAL_TYPES:
            problems.append(Msg("special_type"))
        if not group.entries:
            problems.append(Msg("chest_no_lines"))
        if len(group.entries) > SPECIAL_MAX_ENTRIES:
            problems.append(Msg("too_many", n=SPECIAL_MAX_ENTRIES))
        live = 0
        total = 0
        for n, e in enumerate(group.entries, start=1):
            item = e.item
            if item in SPECIAL_KEYWORDS:
                if item == "mob":
                    if not _uint(e.count, 1, 2 ** 31 - 1) or not mob_exists(int(e.count)):
                        problems.append(Msg("mob_count", line=n, value=e.count or "''"))
                elif item in ("gold", "exp"):
                    if not _uint(e.count, 1, AMOUNT_MAX):
                        problems.append(Msg("amount", line=n, high=AMOUNT_MAX))
                elif not _uint(e.count, 0, AMOUNT_MAX):
                    problems.append(Msg("count_whole", line=n))
            elif item.startswith("s"):
                if not UINT_RE.fullmatch(item[1:]) or str(int(item[1:])) not in special_keys:
                    problems.append(Msg("no_chest_ref", line=n, item=item))
                if not _uint(e.count, 1, ITEM_COUNT_MAX):
                    problems.append(Msg("count", line=n, high=ITEM_COUNT_MAX))
            else:
                if not UINT_RE.fullmatch(item) or not item_exists(int(item)):
                    problems.append(Msg("no_item", line=n, item=item or "''"))
                high = AMOUNT_MAX if typ == "special" else ITEM_COUNT_MAX
                if not _uint(e.count, 1, high):
                    problems.append(Msg("count", line=n, high=high))
            high = 100 if typ == "pct" else WEIGHT_MAX
            if not _uint(e.prob, 0, high):
                problems.append(Msg("prob", line=n, high=high))
            else:
                total += int(e.prob)
                live += int(e.prob) > 0
            if e.rare != "" and not _uint(e.rare, 0, 100):
                problems.append(Msg("rare", line=n))
        if group.entries and live == 0:
            problems.append(Msg("all_zero"))
        if total > 2 ** 31 - 1:
            problems.append(Msg("sum"))
    else:
        if not _uint(f.get("mob", ""), 1, 2 ** 31 - 1) or not mob_exists(int(f["mob"])):
            problems.append(Msg("no_monster", mob=f.get("mob") or "''"))
        typ = f.get("type", "")
        if typ not in MOB_TYPES:
            problems.append(Msg("mob_type"))
        disabled = False
        if typ == "kill":
            if not _uint(f.get("kill_drop", ""), 0, KILL_DROP_MAX):
                problems.append(Msg("kill_drop", high=KILL_DROP_MAX))
            else:
                disabled = int(f["kill_drop"]) == 0
        if typ == "limit" and not _uint(f.get("level_limit", ""), 1, LEVEL_LIMIT_MAX):
            problems.append(Msg("level_limit", high=LEVEL_LIMIT_MAX))
        if not group.entries and not disabled:
            problems.append(Msg("mob_no_lines"))
        if len(group.entries) > MOB_MAX_ENTRIES:
            problems.append(Msg("too_many", n=MOB_MAX_ENTRIES))
        for n, e in enumerate(group.entries, start=1):
            item = e.item
            if typ == "drop" and item.startswith("s"):
                if not UINT_RE.fullmatch(item[1:]):
                    problems.append(Msg("bad_chest_number", line=n, item=item))
            elif not UINT_RE.fullmatch(item) or not item_exists(int(item)):
                problems.append(Msg("no_item", line=n, item=item or "''"))
            if not _uint(e.count, 1, ITEM_COUNT_MAX):
                problems.append(Msg("count", line=n, high=ITEM_COUNT_MAX))
            if typ == "kill":
                if not _uint(e.prob, 1, WEIGHT_MAX):
                    problems.append(Msg("weight", line=n, high=WEIGHT_MAX))
                if not _uint(e.rare or "", 0, 100):
                    problems.append(Msg("kill_rare", line=n))
            else:
                if not PERCENT_RE.fullmatch(e.prob or "") or not 0 <= float(e.prob) <= PERCENT_MAX:
                    problems.append(Msg("percent", line=n, high="%g" % PERCENT_MAX))
                if e.rare != "":
                    problems.append(Msg("only_kill_rare", line=n))
    for e in group.entries:
        if any(any(c in cell for c in " \t\"#{}") or any(ord(c) >= 128 for c in cell) for cell in e.as_tuple()):
            problems.append(Msg("cell"))
            break
    return problems


def chances(group):
    """Each line's chance in percent as the group rolls it (None where the
    line has no number to read): a share of the weights for a normal chest
    and a kill group, the line's own number for a Pct chest and the drop
    types (which the world's drop rate and the level difference then scale)."""
    if group.kind == "special":
        typ = (group.fields.get("type") or "").lower()
        probs = [int(e.prob) if UINT_RE.fullmatch(e.prob or "") else 0 for e in group.entries]
        if typ == "pct":
            return [float(min(p, 100)) for p in probs]
        total = sum(probs)
        return [(100.0 * p / total) if total else 0.0 for p in probs]
    if group.fields.get("type") == "kill":
        probs = [int(e.prob) if UINT_RE.fullmatch(e.prob or "") else 0 for e in group.entries]
        total = sum(probs)
        return [(100.0 * p / total) if total else 0.0 for p in probs]
    return [float(e.prob) if PERCENT_RE.fullmatch(e.prob or "") else None for e in group.entries]


# =============================================================================
#  A change, from the editor's groups to the override and its verdict
# =============================================================================
def apply_change(file_name, current, op, key, group=None, original_keys=()):
    """The override after one change of the editor. `current` is the
    Override saved before (None: none), `op` one of
        "edit"    the group under `key` becomes `group` (a game's own group
                  replaced, or an added one written again),
        "add"     a new group under `key`,
        "remove"  the group under `key` taken out of the game (the image's
                  own) or out of the override (one the operator added),
        "revert"  the image's own group under `key` again,
        "reset"   no override at all.
    Groups keep their place in the override; a new one goes last."""
    blocks = list(current.blocks) if current else []
    removes = list(current.removes) if current else []
    if op == "reset":
        return Override(file_name, [], [])
    if op in ("edit", "add"):
        lines = render_group(group)
        for i, (k, _l) in enumerate(blocks):
            if k == key:
                blocks[i] = (key, lines)
                break
        else:
            blocks.append((key, lines))
        removes = [k for k in removes if k != key]
    elif op == "remove":
        blocks = [(k, l) for k, l in blocks if k != key]
        if key in original_keys and key not in removes:
            removes.append(key)
    elif op == "revert":
        blocks = [(k, l) for k, l in blocks if k != key]
        removes = [k for k in removes if k != key]
    else:
        raise ValueError("unknown change %r" % op)
    return Override(file_name, removes, blocks)


class Verdict(object):
    def __init__(self):
        self.errors = []        # (key or "", Msg)
        self.warnings = []
        self.merged = b""
        self.counts = {"replaced": 0, "added": 0, "removed": 0}


def _loaded_key(file_name, group):
    if KIND[file_name] == "special":
        return str(group["vnum"])
    return "%d %s" % (group["mob"], group["type"])


def validate(file_name, original, override_raw, item_exists, mob_exists, original_groups=None):
    """Everything the panel checks before it writes an override: its shape,
    the merged file through the engine's own reader, and every group the
    operator touched through the strict rules. The game's own groups are
    taken as the image has them - a quirk the image boots with is not the
    operator's to fix - unless the operator's change breaks them.
    `original_groups` (key -> Group of the original) saves a parse when the
    caller has them."""
    v = Verdict()
    try:
        override = parse_override(file_name, override_raw)
    except OverrideError as exc:
        v.errors.append(("", Msg("ov_file", why=exc.msg)))
        return v
    v.merged = merge(file_name, original, override_raw)
    if original_groups is None:
        original_groups = dict((g.key, g) for g in logical_groups(file_name, original))
    for key in override.removes:
        if key in original_groups:
            v.counts["removed"] += 1
        else:
            v.warnings.append((key, Msg("nothing_to_remove", key=key)))
    for key in override.keys():
        v.counts["replaced" if key in original_groups else "added"] += 1
    loaded = read_engine(file_name, v.merged, item_exists)
    for _i, msg in loaded.fatal:
        v.errors.append(("", Msg("game_stops", why=msg)))
    # The splitter m2-drop-tables merges with and the engine have to see the
    # same groups, or the merge would cut where the game does not.
    parts = [p for p in split_blocks(file_name, v.merged) if p[0] != "text"]
    if not loaded.fatal:
        if len(parts) != len(loaded.groups) or any(
                p[0] != "block" or p[2] != _loaded_key(file_name, g) for p, g in zip(parts, loaded.groups)):
            v.errors.append(("", Msg("split", engine=len(loaded.groups), merge=len(parts))))
    merged_groups = logical_groups(file_name, v.merged)
    special_keys = set(g.key for g in merged_groups) if KIND[file_name] == "special" else set()
    touched = set(override.keys())
    for group in merged_groups:
        if group.key not in touched:
            continue
        is_new = group.key not in original_groups
        for msg in check_group(group, item_exists, mob_exists, special_keys, is_new):
            v.errors.append((group.key, msg))
        if group.blocks != 1:
            v.errors.append((group.key, Msg("written_twice", n=group.blocks)))
        before = original_groups.get(group.key)
        if before is not None and before.skipped:
            v.warnings.append((group.key, Msg("dropped_lines", n=len(before.skipped))))
        if before is not None and before.blocks > 1:
            v.warnings.append((group.key, Msg("one_of_many", n=before.blocks)))
        if KIND[file_name] == "special":
            number = int(group.fields["vnum"]) if UINT_RE.fullmatch(group.fields.get("vnum", "")) else 0
            if (group.fields.get("type") or "").lower() == "quest" or 0 < number < 30000:
                v.warnings.append((group.key, Msg("sig_use")))
    if KIND[file_name] == "special":
        gone = set(override.removes)
        for group in merged_groups:
            for e in group.entries:
                if e.item.startswith("s") and UINT_RE.fullmatch(e.item[1:]) and str(int(e.item[1:])) in gone:
                    v.warnings.append((group.key, Msg("names_removed", key=group.key, item=e.item)))
    for i, msg in loaded.hazards:
        owner = None
        for group in loaded.groups:
            if group["line"] <= i:
                owner = group
        key = _loaded_key(file_name, owner) if owner is not None else None
        if key in touched:
            v.errors.append((key, msg))
    return v


def group_diff(old, new, old_label="before", new_label="after"):
    """A unified diff of two group texts, for the preview."""
    a = old.decode("utf-8", "replace").replace("\r", "").splitlines()
    b = new.decode("utf-8", "replace").replace("\r", "").splitlines()
    return list(difflib.unified_diff(a, b, old_label, new_label, lineterm="", n=2))
