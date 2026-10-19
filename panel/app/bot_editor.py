"""The bot editor on a bot's card, "Edytuj bota" (Iwakura's Patch 20, point 4C).

A registered bot's character, skills, worn pieces, Dragon Stones, bag and
storeroom edited by the operator, written by the panel itself into
player.player, player.item and player.quest - and only while no core holds
the bot. The order is the hold's (playerbot_bot_hold.h in the core):

1. "Zapisz" validates the whole edit (nothing is written on an error) and
   queues BOTHOLD (player.web_admin_queue: player_id the bot, arg1 the hold's
   end, at most ten minutes, status 'await') with a job row of
   player.web_m2p_bot_edit_job holding the edit's operations.
2. Every core reads the open holds once a second: the core holding the bot
   logs it out as a session ends and answers 'done'; for a bot no core holds
   one core answers 'done' after 40 s (a load sent just before the hold has
   entered or timed out by then). Before its answer the core has the db core
   write out and forget its cache of the character, so what the panel writes
   is what the next load reads.
3. The page polls the job; once BOTHOLD is 'done' and no status file shows
   the bot (90 s at most) the panel checks that every row is still what the
   edit was built against and writes the operations, the history and the
   protection marks. player.player and player.item are MyISAM on this game,
   so there is no rollback: a statement that fails is undone by writing the
   rows' before-images back, and the job says so.
4. BOTHOLD is set 'released' and BOTRELEASE queued: the core holding the bot
   again fills its health and mana after a level change and writes the gear
   history line of every marked piece ("Zmiana przez operatora").

The history (player.web_m2p_bot_edit_history, made here) keeps every
operation's before and after, and "Cofnij" makes the inverse a new edit,
through the same hold, refused when a row changed since.

Only a registered bot (common.playerbot_seed_state and the playerbot_ login),
never a person or a GM; a player's companion with its owner named. One edit
at a time over the whole world; a second gets "edycja w toku". mt2009 only.

The horse's level is shown and not edited: no hand sets a bot's horse
(Tieru, 16 October; a GM's /horse_level and F9 refuse a bot too) - Patch 20
asks for it, and that is the operator's to decide. Nothing is added out of
nowhere either: a new item needs an item id the db core hands out, so a new
piece is "Wyslij przedmiot"'s (point 4A), and the editor changes, moves and
deletes what the bot has.
"""
import json
import re
import time

from flask import abort, jsonify, request, session, Response

EDIT_HOLD_SECONDS = 600
EDIT_WAIT_SECONDS = 90
EDIT_STALE_SECONDS = 660
GOLD_MAX = 2000000000
STAT_MAX = 90
STACK_MAX = 200
ARROW_STACK_MAX = 5000
EDIT_MARK_SLOTS = 8
PROTECT_SECONDS = 24 * 3600
# The windows player.item keeps the edited items in.
WINDOWS = ("EQUIPMENT", "INVENTORY", "SAFEBOX", "DRAGON_SOUL_INVENTORY")
BAG_CELLS = 180        # four pages of 5 x 9
SAFEBOX_CELLS = 270    # the storeroom's three pages of 5 x 18 at most
BAG_COLUMNS = 5
# A worn slot and the wear flag a piece needs for it (item_proto.wearflag).
WEAR_FLAG_OF_SLOT = {0: 1, 1: 2, 2: 4, 3: 8, 4: 16, 5: 32, 6: 64, 10: 256}
# A worn slot and item_attr's column for the lines it may roll.
ATTR_COLUMN_OF_SLOT = {0: "body", 1: "head", 2: "foots", 3: "wrist", 4: "weapon",
                       5: "neck", 6: "ear", 10: "shield"}
# An armour's subtype and its column; a weapon is "weapon".
ATTR_COLUMN_OF_ARMOR = {0: "body", 1: "head", 2: "shield", 3: "wrist", 4: "foots", 5: "neck", 6: "ear"}
ITEM_TYPE_WEAPON, ITEM_TYPE_ARMOR = 1, 2
WEAPON_ARROW = 6
LIMIT_LEVEL = 1
# Each class starts with sixteen points of its four stats and earns three a
# level up to ninety (char.cpp's PointChange of POINT_LEVEL).
STAT_START = 16
STAT_PER_LEVEL = 3
STAT_LEVELS = 90
SKILL_LEVEL_MAX = 40
PLAYER_COLUMNS = ("gold", "level", "exp", "st", "ht", "dx", "iq", "stat_point", "skill_point")
ITEM_COLUMNS = (("window", "pos", "count", "vnum", "socket0", "socket1", "socket2") +
                tuple("attrtype%d" % i for i in range(7)) + tuple("attrvalue%d" % i for i in range(7)))
PB18_SLOT_FLAGS = r"^s[0-9]+_"

TEXTS = {
    "busy": ("Edycja w toku - poczekaj, az skonczy sie poprzednia.", "An edit is in progress - wait for it to finish."),
    "not_bot": ("To nie jest bot.", "This is not a bot."),
    "changed": ("Postac zmienila sie od otwarcia edytora - otworz go jeszcze raz.",
                "The character changed since the editor opened - open it again."),
    "nothing": ("Nic sie nie zmienilo.", "Nothing changed."),
    "wait_hold": ("Czekam, az bot wyjdzie z gry...", "Waiting for the bot to leave the game..."),
    "timeout": ("Bot nie wyszedl z gry w 90 s - nic nie zapisano.", "The bot did not leave the game in 90 s - nothing was saved."),
    "saved": ("Zapisano. Bot wroci do gry wedlug swojego harmonogramu.", "Saved. The bot comes back by its usual schedule."),
    "failed": ("Blad zapisu - przywrocono stan sprzed edycji: ", "Write failed - the state before the edit was restored: "),
    "undo_changed": ("Tego nie da sie cofnac: wiersz zmienil sie od tamtej pory.", "This cannot be undone: the row changed since."),
}


def stat_allowance(level):
    """The four stats and the free points together at this level."""
    return STAT_START + STAT_PER_LEVEL * (min(int(level), STAT_LEVELS) - 1)


def master_type_of(level):
    level = int(level)
    return 0 if level < 20 else 1 if level < 30 else 2 if level < 40 else 3


def pack_skills(raw, levels):
    """The engine's packed TPlayerSkill array (six bytes a skill: master
    type, level, next read) with `levels` {vnum: level} written into it and
    every other byte kept."""
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    elif isinstance(raw, str):
        raw = raw.encode("latin-1", "ignore")
    data = bytearray(raw or b"")
    for vnum, level in levels.items():
        offset = int(vnum) * 6
        if offset + 2 > len(data):
            data.extend(b"\0" * (offset + 6 - len(data)))
        data[offset] = master_type_of(level)
        data[offset + 1] = int(level)
    return bytes(data)


def item_cells(pos, size, columns=BAG_COLUMNS):
    """The cells an item of `size` rows covers from `pos`."""
    return [pos + row * columns for row in range(max(1, int(size or 1)))]


def free_cell(occupied, size, cells, page_rows=9, columns=BAG_COLUMNS):
    """The first cell a piece of `size` rows fits in, on one page."""
    for pos in range(cells):
        row = (pos // columns) % page_rows
        if row + size > page_rows:
            continue
        covered = item_cells(pos, size, columns)
        if all(c < cells and c not in occupied for c in covered):
            return pos
    return None


def attr_column(item_proto_row, wear_pos=None):
    if wear_pos is not None and wear_pos in ATTR_COLUMN_OF_SLOT:
        return ATTR_COLUMN_OF_SLOT[wear_pos]
    if not item_proto_row:
        return None
    if int(item_proto_row.get("type") or 0) == ITEM_TYPE_WEAPON:
        return "weapon"
    if int(item_proto_row.get("type") or 0) == ITEM_TYPE_ARMOR:
        return ATTR_COLUMN_OF_ARMOR.get(int(item_proto_row.get("subtype") or 0))
    return None


def stack_limit(proto):
    """What a stack of this item may hold: 1 for a piece that never stacks."""
    if not proto:
        return 1
    if int(proto.get("type") or 0) == ITEM_TYPE_WEAPON and int(proto.get("subtype") or 0) == WEAPON_ARROW:
        return ARROW_STACK_MAX
    return STACK_MAX if int(proto.get("flag") or 0) & 4 else 1


def proto_level(proto):
    for i in (0, 1):
        if int(proto.get("limittype%d" % i) or 0) == LIMIT_LEVEL:
            return int(proto.get("limitvalue%d" % i) or 0)
    return 0


def validate_item(after, proto, attrs, wear_pos, bot_level, bot_job, warnings, errors, label):
    """Errors stop the save; warnings are shown and let it go (Patch 20, 4C)."""
    if not proto:
        errors.append("%s: vnum %s nie istnieje w item_proto / does not exist" % (label, after["vnum"]))
        return
    if wear_pos is not None and after["window"] == "EQUIPMENT":
        need = WEAR_FLAG_OF_SLOT.get(wear_pos)
        if need and not int(proto.get("wearflag") or 0) & need:
            errors.append("%s: przedmiot nie pasuje do slotu / does not fit the slot" % label)
    limit = stack_limit(proto)
    if not 1 <= int(after["count"]) <= limit:
        errors.append("%s: ilosc 1-%d / count 1-%d" % (label, limit, limit))
    column = attr_column(proto, wear_pos if after["window"] == "EQUIPMENT" else None)
    for i in range(7):
        kind, value = int(after["attrtype%d" % i] or 0), int(after["attrvalue%d" % i] or 0)
        if not kind and not value:
            continue
        rows = attrs.get(kind)
        allowed = rows and column and rows.get(column)
        if not allowed:
            errors.append("%s: bonus %d niedozwolony dla slotu / not allowed on the slot" % (label, kind))
        elif value <= 0:
            errors.append("%s: wartosc bonusu > 0 / a line's value > 0" % label)
        elif value > rows["top"]:
            warnings.append("%s: bonus %d = %d ponad zwykle maksimum %d / over the usual top" %
                            (label, kind, value, rows["top"]))
    need_level = proto_level(proto)
    if need_level > int(bot_level):
        warnings.append("%s: wymaga poziomu %d / needs level %d" % (label, need_level, need_level))
    anti = int(proto.get("antiflag") or 0)
    # ITEM_ANTIFLAG_WARRIOR..SHAMAN are 1 << 3..6, by the job's class.
    if int(proto.get("type") or 0) == ITEM_TYPE_WEAPON and anti & (1 << (3 + int(bot_job) % 4)):
        warnings.append("%s: bron innej klasy / another class's weapon" % label)


def register(app, db, login_required, csrf_token, lang=lambda: "pl", is_registered_bot=None,
             live_status=lambda: {}, skills_of=None, item_name=None, max_level=120,
             gear_hows=None, spool_dir="/opt/m2spool"):
    """The editor's routes and the card's button script.

    `is_registered_bot(cur, pid)` - the panel's bot identity test;
    `live_status()` - {pid: row} of the cores' status files;
    `skills_of(raw, job, group, language)` - the panel's skill decoder;
    `item_name(vnum, language)` - an item's name for the reader;
    `gear_hows` - the gear history's how->label table, which the editor's
    line "Zmiana przez operatora" joins."""

    if gear_hows is not None:
        gear_hows.setdefault("PLAYERBOT_OPERATOR_EDIT", ("gift_in", {
            "pl": "Zmiana przez operatora", "en": "Changed by the operator",
            "de": "Vom Betreiber geändert", "tr": "Operatör tarafından değiştirildi"}))

    def tr(key):
        pl, en = TEXTS[key]
        return pl if lang() == "pl" else en

    def ensure_tables(cur):
        cur.execute("CREATE TABLE IF NOT EXISTS player.web_m2p_bot_edit_job ("
                    "id INT AUTO_INCREMENT PRIMARY KEY, pid INT NOT NULL, created DATETIME DEFAULT CURRENT_TIMESTAMP, "
                    "state VARCHAR(16) NOT NULL, hold_queue INT, who VARCHAR(64), undo_of INT, "
                    "ops MEDIUMTEXT, result TEXT, KEY state_idx (state)) ENGINE=InnoDB")
        cur.execute("CREATE TABLE IF NOT EXISTS player.web_m2p_bot_edit_history ("
                    "id INT AUTO_INCREMENT PRIMARY KEY, job_id INT NOT NULL, at DATETIME DEFAULT CURRENT_TIMESTAMP, "
                    "who VARCHAR(64), pid INT NOT NULL, field VARCHAR(64), before_val MEDIUMTEXT, after_val MEDIUMTEXT, "
                    "undone_by INT, KEY pid_idx (pid), KEY job_idx (job_id)) ENGINE=InnoDB")

    def check_bot(cur, pid):
        cur.execute("SELECT p.id, p.name, p.job, p.level, a.login FROM player.player p "
                    "JOIN account.account a ON a.id = p.account_id WHERE p.id = %s", (pid,))
        row = cur.fetchone()
        if not row or not str(row.get("login") or "").startswith("playerbot_"):
            return None
        if is_registered_bot is not None and not is_registered_bot(cur, pid):
            return None
        # Never a GM, whatever its account.
        try:
            cur.execute("SELECT 1 AS n FROM common.gmlist WHERE mName = %s LIMIT 1", (row["name"],))
            if cur.fetchone():
                return None
        except Exception:  # noqa: BLE001 - no gmlist: nobody is a GM there
            pass
        return row

    def protos(cur, vnums):
        vnums = sorted({int(v) for v in vnums if int(v or 0) > 0})
        if not vnums:
            return {}
        marks = ",".join(["%s"] * len(vnums))
        for table in ("world.item_proto", "player.item_proto"):
            try:
                cur.execute("SELECT vnum, type, subtype, size, flag, antiflag, wearflag, "
                            "limittype0, limitvalue0, limittype1, limitvalue1 FROM " + table +
                            " WHERE vnum IN (" + marks + ")", tuple(vnums))
                return {int(r["vnum"]): r for r in cur.fetchall()}
            except Exception:  # noqa: BLE001 - the other world's table
                continue
        return {}

    def attr_rows(cur):
        """{apply: {column: allowed, 'top': the table's highest roll}}."""
        result = {}
        for table in ("world.item_attr", "world.item_attr_rare"):
            try:
                cur.execute("SELECT apply+0 AS p, GREATEST(lv1,lv2,lv3,lv4,lv5) AS top, "
                            "weapon, body, wrist, foots, neck, head, shield, ear FROM " + table)
            except Exception:  # noqa: BLE001
                continue
            for r in cur.fetchall():
                point = int(r.get("p") or 0)
                if not point:
                    continue
                entry = result.setdefault(point, {"top": 0})
                entry["top"] = max(entry["top"], int(r.get("top") or 0))
                for column in ATTR_COLUMN_OF_SLOT.values():
                    if int(r.get(column) or 0) > 0:
                        entry[column] = True
        return result

    def read_state(cur, pid):
        cur.execute("SELECT id, name, job, level, exp, gold, st, ht, dx, iq, stat_point, skill_point, "
                    "skill_group, skill_level, horse_level FROM player.player WHERE id = %s", (pid,))
        player = cur.fetchone()
        cur.execute("SELECT id, `window`, pos, `count`, vnum, socket0, socket1, socket2, " +
                    ", ".join("attrtype%d, attrvalue%d" % (i, i) for i in range(7)) +
                    " FROM player.item WHERE owner_id = %s AND `window` IN (" +
                    ",".join(["%s"] * len(WINDOWS)) + ") ORDER BY `window`, pos", (pid,) + WINDOWS)
        items = {}
        for r in cur.fetchall():
            r["window"] = str(r["window"])
            items[int(r["id"])] = {k: (r[k] if k == "window" else int(r[k] or 0)) for k in ITEM_COLUMNS}
        cur.execute("SELECT szState, lValue FROM player.quest WHERE dwPID = %s AND szName = 'playerbot' "
                    "AND szState IN ('persona_lock_lv','exp_unlocked')", (pid,))
        flags = {r["szState"]: int(r["lValue"] or 0) for r in cur.fetchall()}
        return player, items, flags

    def player_image(player):
        image = {k: int(player.get(k) or 0) for k in PLAYER_COLUMNS}
        raw = player.get("skill_level")
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        image["skill_level"] = (raw or b"").hex() if isinstance(raw, (bytes, bytearray)) else ""
        return image

    def hold_open(cur):
        cur.execute("SELECT id, pid, state FROM player.web_m2p_bot_edit_job WHERE state IN ('hold','apply') "
                    "AND created > NOW() - INTERVAL %s SECOND ORDER BY id DESC LIMIT 1", (EDIT_STALE_SECONDS,))
        return cur.fetchone()

    def who():
        return str(session.get("user") or session.get("username") or "admin")[:64]

    def build_ops(cur, pid, edit):
        """The operations an edit makes, each with the before-image it was
        built against, and the errors and warnings of its validation."""
        player, items, flags = read_state(cur, pid)
        errors, warnings, ops = [], [], []
        if edit.get("opened") and edit["opened"] != fingerprint(player, items, flags):
            return None, [tr("changed")], []
        before = player_image(player)
        after = dict(before)
        changes = edit.get("player") or {}
        for key in PLAYER_COLUMNS:
            if key in changes:
                try:
                    after[key] = int(changes[key])
                except (TypeError, ValueError):
                    errors.append("%s: liczba / a number" % key)
        if not 0 <= after["gold"] <= GOLD_MAX:
            errors.append("Yang 0-%d" % GOLD_MAX)
        if not 1 <= after["level"] <= int(max_level):
            errors.append("Poziom / level 1-%d" % int(max_level))
        if after["level"] != before["level"]:
            after["exp"] = 0
        if after["exp"] < 0 or after["skill_point"] < 0 or after["stat_point"] < 0:
            errors.append("exp / punkty >= 0")
        stats = [after[k] for k in ("st", "ht", "dx", "iq")]
        if any(not 1 <= s <= STAT_MAX for s in stats):
            errors.append("SIL/ZRC/INT/WIT 1-%d" % STAT_MAX)
        if sum(stats) + after["stat_point"] > stat_allowance(after["level"]):
            errors.append("Statystyki ponad dostepne na poziomie %d (%d) / stats over the level's %d" %
                          (after["level"], stat_allowance(after["level"]), stat_allowance(after["level"])))
        skills = {int(k): int(v) for k, v in (edit.get("skills") or {}).items()}
        allowed_skills = {s["vnum"] for s in (skills_of(player.get("skill_level"), player.get("job"),
                                                           player.get("skill_group"), "en") if skills_of else [])}
        for vnum, level in skills.items():
            if vnum not in allowed_skills or not 0 <= level <= SKILL_LEVEL_MAX:
                errors.append("Umiejetnosc / skill %d: 0-%d" % (vnum, SKILL_LEVEL_MAX))
        if skills:
            after["skill_level"] = pack_skills(bytes.fromhex(before["skill_level"]), skills).hex()
        if after != before:
            ops.append({"kind": "player", "before": before, "after": after})
        # The level lock and the operator's override, as their quest flags.
        for state, value in (("persona_lock_lv", edit.get("lock_level")), ("exp_unlocked", edit.get("exp_unlocked"))):
            if value is None:
                continue
            value = int(value)
            new = (value + 1 if value > 0 else 0) if state == "persona_lock_lv" else (1 if value else 0)
            old = flags.get(state, 0)
            if new != old:
                ops.append({"kind": "flag", "state": state, "before": old, "after": new})
        # The items: changed, moved, deleted.
        attrs = attr_rows(cur)
        wanted = edit.get("items") or {}
        changed_protos = protos(cur, [i["vnum"] for i in items.values()] +
                                [(c or {}).get("vnum", 0) for c in wanted.values()])
        occupied = {w: set() for w in WINDOWS}
        for row in items.values():
            proto = changed_protos.get(row["vnum"])
            size = int(proto.get("size") or 1) if proto else 1
            cols = BAG_COLUMNS if row["window"] in ("INVENTORY", "SAFEBOX") else 1
            occupied[row["window"]].update(item_cells(row["pos"], size if cols > 1 else 1, cols))
        for key, change in wanted.items():
            item_id = int(key)
            old = items.get(item_id)
            if not old:
                errors.append("Przedmiot #%d: nie nalezy do bota / not the bot's" % item_id)
                continue
            label = "#%d" % item_id
            if change is None or change.get("delete"):
                ops.append({"kind": "item", "id": item_id, "before": old, "after": None})
                continue
            new = dict(old)
            for column in ITEM_COLUMNS:
                if column in change and column not in ("window", "pos"):
                    try:
                        new[column] = int(change[column])
                    except (TypeError, ValueError):
                        errors.append("%s: %s" % (label, column))
            move = change.get("move")
            if move in ("INVENTORY", "SAFEBOX") and move != old["window"]:
                proto = changed_protos.get(new["vnum"])
                size = int(proto.get("size") or 1) if proto else 1
                cells = BAG_CELLS if move == "INVENTORY" else SAFEBOX_CELLS
                pos = free_cell(occupied[move], size, cells, 9 if move == "INVENTORY" else 18)
                if pos is None:
                    errors.append("%s: brak miejsca / no room in %s" % (label, move))
                    continue
                occupied[move].update(item_cells(pos, size))
                new["window"], new["pos"] = move, pos
            wear_pos = old["pos"] if old["window"] == "EQUIPMENT" else None
            if new["window"] != "DRAGON_SOUL_INVENTORY":
                validate_item(new, changed_protos.get(new["vnum"]), attrs, wear_pos,
                              after["level"], player.get("job") or 0, warnings, errors, label)
            elif new["vnum"] not in changed_protos:
                errors.append("%s: vnum %d" % (label, new["vnum"]))
            if new != old:
                ops.append({"kind": "item", "id": item_id, "before": old, "after": new})
        return ops, errors, warnings

    def fingerprint(player, items, flags):
        text = json.dumps([player_image(player), sorted(items.items()), sorted(flags.items())], sort_keys=True)
        return "%08x" % (hash_text(text) & 0xffffffff)

    def hash_text(text):
        h = 2166136261
        for byte in text.encode("utf-8"):
            h = ((h ^ byte) * 16777619) & 0xffffffff
        return h

    def queue_hold(cur, pid, name, ops, undo_of=None):
        until = int(time.time()) + EDIT_HOLD_SECONDS
        cur.execute("INSERT INTO player.web_admin_queue (player_id, player_name, cmd, arg1, arg2, status) "
                    "VALUES (%s, %s, 'BOTHOLD', %s, 'panel', 'await')", (pid, name, str(until)))
        hold = cur.lastrowid
        cur.execute("INSERT INTO player.web_m2p_bot_edit_job (pid, state, hold_queue, who, undo_of, ops) "
                    "VALUES (%s, 'hold', %s, %s, %s, %s)", (pid, hold, who(), undo_of, json.dumps(ops)))
        return cur.lastrowid

    def matches(cur, pid, op):
        """Whether the row is still the before-image the operation expects."""
        player, items, flags = read_state(cur, pid)
        if op["kind"] == "player":
            return player_image(player) == op["before"]
        if op["kind"] == "flag":
            return flags.get(op["state"], 0) == op["before"]
        return items.get(op["id"]) == op["before"]

    def write_op(cur, pid, op, image):
        if op["kind"] == "player":
            cur.execute("UPDATE player.player SET " + ", ".join("%s = %%s" % k for k in PLAYER_COLUMNS) +
                        ", skill_level = %s WHERE id = %s",
                        tuple(image[k] for k in PLAYER_COLUMNS) + (bytes.fromhex(image["skill_level"]), pid))
        elif op["kind"] == "flag":
            cur.execute("DELETE FROM player.quest WHERE dwPID = %s AND szName = 'playerbot' AND szState = %s",
                        (pid, op["state"]))
            if image:
                cur.execute("INSERT INTO player.quest (dwPID, szName, szState, lValue) VALUES (%s, 'playerbot', %s, %s)",
                            (pid, op["state"], image))
        elif image is None:
            cur.execute("DELETE FROM player.item WHERE id = %s AND owner_id = %s", (op["id"], pid))
        else:
            cur.execute("REPLACE INTO player.item (id, owner_id, " + ", ".join("`%s`" % c for c in ITEM_COLUMNS) +
                        ") VALUES (%s, %s, " + ", ".join(["%s"] * len(ITEM_COLUMNS)) + ")",
                        (op["id"], pid) + tuple(image[c] for c in ITEM_COLUMNS))

    def mark_items(cur, pid, item_ids, protect):
        """The operator_edit marks: playerbot.op_edit<N> the item id and
        playerbot.op_edit_until<N> its end (0 for good); the oldest gives way."""
        cur.execute("SELECT szState, lValue FROM player.quest WHERE dwPID = %s AND szName = 'playerbot' "
                    "AND szState LIKE 'op\\_edit%%'", (pid,))
        marks = {r["szState"]: int(r["lValue"] or 0) for r in cur.fetchall()}
        slots = [(marks.get("op_edit%d" % i, 0), marks.get("op_edit_until%d" % i, 0)) for i in range(EDIT_MARK_SLOTS)]
        until = 0 if protect else int(time.time()) + PROTECT_SECONDS
        for item_id in item_ids:
            slots = [s for s in slots if s[0] and s[0] != item_id] + [(item_id, until)]
        slots = ([(0, 0)] * EDIT_MARK_SLOTS + slots)[-EDIT_MARK_SLOTS:]
        cur.execute("DELETE FROM player.quest WHERE dwPID = %s AND szName = 'playerbot' AND szState LIKE 'op\\_edit%%'",
                    (pid,))
        for i, (item_id, end) in enumerate(slots):
            if item_id:
                cur.execute("INSERT INTO player.quest (dwPID, szName, szState, lValue) VALUES "
                            "(%s, 'playerbot', %s, %s), (%s, 'playerbot', %s, %s)",
                            (pid, "op_edit%d" % i, item_id, pid, "op_edit_until%d" % i, end))

    def apply_job(con, cur, job):
        """The edit's one write, with the before-images put back on a failure."""
        pid, ops = int(job["pid"]), json.loads(job["ops"] or "[]")
        meta = ops[0] if ops and ops[0].get("kind") == "meta" else {"kind": "meta"}
        ops = [op for op in ops if op.get("kind") != "meta"]
        for op in ops:
            if not matches(cur, pid, op):
                return "failed", tr("undo_changed" if job.get("undo_of") else "changed")
        done = []
        try:
            for op in ops:
                write_op(cur, pid, op, op["after"])
                done.append(op)
            level_changed = any(op["kind"] == "player" and op["before"]["level"] != op["after"]["level"] for op in ops)
            marked = [op["id"] for op in ops if op["kind"] == "item" and op["after"] is not None]
            if marked:
                mark_items(cur, pid, marked, bool(meta.get("protect")))
            # Patch 18's plan starts again at its first review.
            cur.execute("DELETE FROM player.quest WHERE dwPID = %s AND szName = 'pb18' AND szState REGEXP %s",
                        (pid, PB18_SLOT_FLAGS))
            for op in ops:
                field = op["kind"] if op["kind"] != "item" else "item:%d" % op["id"]
                if op["kind"] == "flag":
                    field = "flag:" + op["state"]
                cur.execute("INSERT INTO player.web_m2p_bot_edit_history (job_id, who, pid, field, before_val, after_val) "
                            "VALUES (%s, %s, %s, %s, %s, %s)",
                            (job["id"], job["who"], pid, field, json.dumps(op["before"]), json.dumps(op["after"])))
            if job.get("undo_of"):
                cur.execute("UPDATE player.web_m2p_bot_edit_history SET undone_by = %s WHERE job_id = %s",
                            (job["id"], job["undo_of"]))
            con.commit()
            return "applied", ("L" if level_changed else "-")
        except Exception as error:  # noqa: BLE001 - put the before-images back
            for op in reversed(done):
                try:
                    write_op(cur, pid, op, op["before"])
                except Exception:  # noqa: BLE001
                    pass
            try:
                con.commit()
            except Exception:  # noqa: BLE001
                pass
            return "failed", tr("failed") + str(error)[:200]

    def release(cur, job, flags):
        cur.execute("UPDATE player.web_admin_queue SET status = 'released' WHERE id = %s AND cmd = 'BOTHOLD'",
                    (job["hold_queue"],))
        if flags is not None:
            cur.execute("SELECT name FROM player.player WHERE id = %s", (job["pid"],))
            row = cur.fetchone()
            cur.execute("INSERT INTO player.web_admin_queue (player_id, player_name, cmd, arg1, arg2, status) "
                        "VALUES (%s, %s, 'BOTRELEASE', %s, 'panel', 'await')",
                        (job["pid"], row["name"] if row else "", flags))

    def advance(con, cur, job):
        """One look at a job: waiting for the hold, written, or given up."""
        if job["state"] != "hold":
            return job
        cur.execute("SELECT status, TIMESTAMPDIFF(SECOND, created, NOW()) AS age FROM player.web_admin_queue "
                    "WHERE id = %s", (job["hold_queue"],))
        hold = cur.fetchone() or {"status": "gone", "age": 9999}
        online = int(job["pid"]) in live_status()
        if hold["status"] == "done" and not online:
            cur.execute("UPDATE player.web_m2p_bot_edit_job SET state = 'apply' WHERE id = %s AND state = 'hold'",
                        (job["id"],))
            con.commit()
            if cur.rowcount != 1:
                return job
            state, result = apply_job(con, cur, job)
            release(cur, job, result if state == "applied" else None)
            cur.execute("UPDATE player.web_m2p_bot_edit_job SET state = %s, result = %s WHERE id = %s",
                        (state, tr("saved") if state == "applied" else result, job["id"]))
            con.commit()
        elif int(hold["age"] or 0) > EDIT_WAIT_SECONDS or hold["status"] not in ("await", "done"):
            release(cur, job, None)
            cur.execute("UPDATE player.web_m2p_bot_edit_job SET state = 'timeout', result = %s WHERE id = %s",
                        (tr("timeout"), job["id"]))
            con.commit()
        cur.execute("SELECT * FROM player.web_m2p_bot_edit_job WHERE id = %s", (job["id"],))
        return cur.fetchone()

    def answer_job(job):
        return jsonify({"ok": True, "job": int(job["id"]), "state": job["state"],
                        "text": job.get("result") or tr("wait_hold")})

    def alone_pids():
        """The companions the cores report playing without their owner."""
        import glob
        import os
        pids = set()
        for path in glob.glob(os.path.join(spool_dir, "playerbot_sidekick_alone_ch*.tsv")):
            try:
                if time.time() - os.path.getmtime(path) > 120:
                    continue
                with open(path, encoding="ascii", errors="replace") as stream:
                    lines = stream.read().splitlines()
                if not lines or not lines[0].startswith("#PB20A1"):
                    continue
                for line in lines[1:]:
                    parts = line.split("\t")
                    if parts and parts[0].isdigit():
                        pids.add(int(parts[0]))
            except OSError:
                continue
        return pids

    @app.route("/bot_editor/editor.js")
    @login_required
    def bot_editor_script():
        return Response(EDITOR_JS, mimetype="application/javascript")

    @app.route("/bot_editor/<int:pid>/data")
    @login_required
    def bot_editor_data(pid):
        language = lang()
        with db() as con, con.cursor() as cur:
            ensure_tables(cur)
            bot = check_bot(cur, pid)
            if not bot:
                return jsonify({"ok": False, "error": tr("not_bot")})
            player, items, flags = read_state(cur, pid)
            companion = None
            try:
                cur.execute("SELECT s.owner_pid, o.name, s.solo FROM player.playerbot_sidekick s "
                            "JOIN player.player o ON o.id = s.owner_pid WHERE s.sidekick_pid = %s", (pid,))
                row = cur.fetchone()
                if row:
                    companion = {"owner": row["name"], "solo": bool(row.get("solo")), "alone": pid in alone_pids()}
            except Exception:  # noqa: BLE001 - no companion table on this world
                companion = None
            item_protos = protos(cur, [i["vnum"] for i in items.values()])
            out_items = []
            for item_id, row in items.items():
                proto = item_protos.get(row["vnum"]) or {}
                entry = dict(row)
                entry["id"] = item_id
                entry["name"] = item_name(row["vnum"], language) if item_name else "#%d" % row["vnum"]
                entry["stack"] = stack_limit(proto)
                base = row["vnum"] - row["vnum"] % 10
                entry["family"] = sorted(v for v in protos(cur, range(base, base + 10)).keys()) \
                    if row["window"] != "DRAGON_SOUL_INVENTORY" else [row["vnum"]]
                column = attr_column(proto, row["pos"] if row["window"] == "EQUIPMENT" else None)
                entry["attr_column"] = column
                out_items.append(entry)
            attrs = attr_rows(cur)
            cur.execute("SELECT h.id, h.job_id, h.at, h.who, h.field, h.before_val, h.after_val, h.undone_by "
                        "FROM player.web_m2p_bot_edit_history h WHERE h.pid = %s ORDER BY h.id DESC LIMIT 100", (pid,))
            history = [{"id": r["id"], "job": r["job_id"], "at": str(r["at"]), "who": r["who"], "field": r["field"],
                        "before": r["before_val"], "after": r["after_val"], "undone": bool(r["undone_by"])}
                       for r in cur.fetchall()]
            lock = flags.get("persona_lock_lv", 0)
            return jsonify({
                "ok": True, "csrf": csrf_token(), "opened": fingerprint(player, items, flags),
                "max_level": int(max_level), "stat_allowance": stat_allowance(player["level"]),
                "player": {k: int(player.get(k) or 0) for k in PLAYER_COLUMNS + ("job", "skill_group", "horse_level")},
                "name": bot["name"], "lock_level": lock - 1 if lock > 1 else 0,
                "exp_unlocked": bool(flags.get("exp_unlocked")), "companion": companion,
                "online": pid in live_status(),
                "skills": skills_of(player.get("skill_level"), player.get("job"), player.get("skill_group"),
                                    language) if skills_of else [],
                "items": out_items,
                "stones": [{"vnum": v, "name": item_name(v, language) if item_name else "#%d" % v}
                           for v in sorted(protos(cur, range(28000, 28500)))],
                "attrs": {str(k): sorted(c for c in v if c != "top") + ["top:%d" % v["top"]] for k, v in attrs.items()},
                "history": history})

    @app.route("/bot_editor/<int:pid>/save", methods=["POST"])
    @login_required
    def bot_editor_save(pid):
        # The host panel's before_request checks the form's CSRF token.
        try:
            edit = json.loads(request.form.get("edit") or "{}")
        except ValueError:
            abort(400)
        with db() as con, con.cursor() as cur:
            ensure_tables(cur)
            bot = check_bot(cur, pid)
            if not bot:
                return jsonify({"ok": False, "error": tr("not_bot")})
            if hold_open(cur):
                return jsonify({"ok": False, "error": tr("busy")})
            ops, errors, warnings = build_ops(cur, pid, edit)
            if errors:
                return jsonify({"ok": False, "error": "; ".join(errors), "warnings": warnings})
            if not ops:
                return jsonify({"ok": False, "error": tr("nothing")})
            if warnings and not edit.get("accept_warnings"):
                return jsonify({"ok": False, "warnings": warnings, "confirm": True})
            ops.insert(0, {"kind": "meta", "protect": bool(edit.get("protect"))})
            job = queue_hold(cur, pid, bot["name"], ops)
            con.commit()
            return jsonify({"ok": True, "job": job, "state": "hold", "text": tr("wait_hold"), "warnings": warnings})

    @app.route("/bot_editor/job/<int:job_id>")
    @login_required
    def bot_editor_job(job_id):
        with db() as con, con.cursor() as cur:
            ensure_tables(cur)
            cur.execute("SELECT * FROM player.web_m2p_bot_edit_job WHERE id = %s", (job_id,))
            job = cur.fetchone()
            if not job:
                abort(404)
            return answer_job(advance(con, cur, job))

    @app.route("/bot_editor/undo/<int:job_id>", methods=["POST"])
    @login_required
    def bot_editor_undo(job_id):
        with db() as con, con.cursor() as cur:
            ensure_tables(cur)
            cur.execute("SELECT * FROM player.web_m2p_bot_edit_job WHERE id = %s AND state = 'applied'", (job_id,))
            job = cur.fetchone()
            if not job:
                abort(404)
            bot = check_bot(cur, int(job["pid"]))
            if not bot:
                return jsonify({"ok": False, "error": tr("not_bot")})
            if hold_open(cur):
                return jsonify({"ok": False, "error": tr("busy")})
            cur.execute("SELECT 1 AS n FROM player.web_m2p_bot_edit_history WHERE job_id = %s AND undone_by IS NOT NULL "
                        "LIMIT 1", (job_id,))
            if cur.fetchone():
                return jsonify({"ok": False, "error": tr("nothing")})
            inverse = [{"kind": "meta", "protect": False}]
            for op in json.loads(job["ops"] or "[]"):
                if op.get("kind") == "meta":
                    continue
                back = dict(op)
                back["before"], back["after"] = op["after"], op["before"]
                inverse.append(back)
            for op in inverse[1:]:
                if not matches(cur, int(job["pid"]), op):
                    return jsonify({"ok": False, "error": tr("undo_changed")})
            new_job = queue_hold(cur, int(job["pid"]), bot["name"], inverse, undo_of=job_id)
            con.commit()
            return jsonify({"ok": True, "job": new_job, "state": "hold", "text": tr("wait_hold")})

    @app.after_request
    def bot_editor_inject(response):
        # The card is drawn by the map page's script: the editor's script joins
        # every page that carries the card, nothing of the page is rewritten.
        try:
            if (response.mimetype == "text/html" and not response.direct_passthrough and
                    response.status_code == 200):
                body = response.get_data(as_text=True)
                if 'id="botModal"' in body and "/bot_editor/editor.js" not in body and "</body>" in body:
                    response.set_data(body.replace("</body>", '<script src="/bot_editor/editor.js"></script></body>', 1))
        except Exception:  # noqa: BLE001 - a page without the button, never a broken page
            pass
        return response


# The card's button and the editor's window. Plain DOM, no library: it rides
# on the map page, whatever theme draws the card.
EDITOR_JS = r"""
(function(){
  var PL = (document.documentElement.lang || 'pl').indexOf('pl') === 0;
  function T(pl, en){ return PL ? pl : en; }
  function esc(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); }
  var SLOT = {0:T('Zbroja','Armour'),1:T('Helm','Helmet'),2:T('Buty','Shoes'),3:T('Bransoleta','Bracelet'),
              4:T('Bron','Weapon'),5:T('Naszyjnik','Necklace'),6:T('Kolczyki','Earrings'),10:T('Tarcza','Shield')};
  var state = null;
  var css=document.createElement('style');
  css.textContent='#botEditorBox{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);width:min(960px,95vw);max-height:80vh;z-index:10050;box-sizing:border-box;display:flex;flex-direction:column;overflow:hidden;color:var(--txt,#222);border:1px solid var(--line,#aaa);border-radius:6px;padding:14px;font-size:12px;box-shadow:0 12px 60px #0006}#botEditorBox .be-head,#botEditorBox .be-footer,#botEditorBox .be-tabs{flex:none}#botEditorBox .be-content{min-height:0;overflow:auto;padding:4px 2px;flex:1 1 auto}#botEditorBox .be-footer{padding-top:10px;border-top:1px solid var(--line,#aaa)}#botEditorBox details[data-item]{border-bottom:1px solid var(--line,#aaa);padding:4px 0}#botEditorBox summary{display:flex;align-items:center;gap:8px;cursor:pointer}#botEditorBox summary img{width:28px;height:28px;object-fit:contain}#botEditorBox .be-item-form{padding:8px 6px}#botEditorBox .be-attr{display:flex;gap:5px;margin:3px 0}#botEditorBox .be-attr select{max-width:72%}#botEditorBox input,#botEditorBox select{background:var(--card2,var(--card,#fff));color:inherit;border:1px solid var(--line,#aaa)}.bot-card-heading{display:flex;align-items:center;gap:8px;flex-wrap:wrap}';
  document.head.appendChild(css);

  function addButton(){
    var content = document.getElementById('botModalContent');
    var data = window.g_currentInvData;
    if (!content || !data || !data.player || !data.player.is_bot) return;
    if (content.querySelector('.bot-editor-open')) return;
    var head = content.querySelector('h3');
    if (!head) return;
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'btn btn-sm m2ex-btn bot-editor-open';
    b.style.marginLeft = '8px';
    b.textContent = T('Edytuj bota', 'Edit bot');
    b.onclick = function(){ openEditor(data.player.id); };
    head.appendChild(b);
    head.classList.add('bot-card-heading');
    var badge=content.querySelector('.bot-badge');if(badge)head.appendChild(badge);
    var bar=content.querySelector('#p20Bar');
    if(bar){bar.style.display='contents';head.insertBefore(bar,b.nextSibling);}
    // Patch 20, point 9: a companion that plays on without its owner.
    fetch('/bot_editor/' + data.player.id + '/data', {cache:'no-store'}).then(function(r){ return r.json(); })
      .then(function(d){
        if (d && d.ok && d.companion && d.companion.alone && !content.querySelector('.bot-editor-alone')) {
          var s = document.createElement('span'); s.className = 'bot-editor-alone';
          s.style.cssText = 'margin-left:8px;font-size:11px;color:#facc15';
          s.textContent = T('Gra sam (bez wlasciciela)', 'Playing alone (owner away)');
          head.appendChild(s);
        }
      }).catch(function(){});
  }

  function field(label, name, value, extra){
    return '<label style="display:inline-block;margin:3px 10px 3px 0">' + esc(label) +
      ' <input data-f="' + name + '" value="' + esc(value) + '" style="width:110px" ' + (extra || '') + '></label>';
  }

  function render(d){
    var p = d.player, h = '';
    h += '<div class="be-head" style="display:flex;justify-content:space-between;align-items:center"><h3 style="margin:0">' +
         T('Edycja bota','Bot editor') + ': ' + esc(d.name) + '</h3><button type="button" class="btn btn-sm" id="beClose">X</button></div>';
    if (d.companion) h += '<p style="color:#facc15">' + T('Uwaga: to Towarzysz gracza ','Note: this is the companion of ') +
         esc(d.companion.owner) + '.</p>';
    if (d.online) h += '<p class="muted">' + T('Bot jest w grze: zapis najpierw go wyloguje (do 90 s).',
         'The bot is in the game: saving logs it out first (up to 90 s).') + '</p>';
    var tabs = [['char',T('Postać','Character')],['skills',T('Umiejętności','Skills')],['eq',T('Ekwipunek','Equipment')],
                ['ds',T('Alchemia','Alchemy')],['bag',T('Torba i magazyn','Bag and storeroom')],['hist',T('Historia','History')]];
    h += '<div class="be-tabs m2-tabs" style="margin:8px 0">' + tabs.map(function(t){ return '<button type="button" class="btn btn-sm m2-tab-btn'+(t[0]==='char'?' active':'')+'" data-tab="' +
         t[0] + '" style="margin-right:4px">' + t[1] + '</button>'; }).join('') + '</div>';
    h += '<div class="be-content"><div data-pane="char">' + field('Yang','gold',p.gold) + field(T('Poziom','Level'),'level',p.level,'type="number" min="1" max="' + d.max_level + '"') +
         field('Exp','exp',p.exp) + '<br>' + field(T('SIL','STR'),'st',p.st) + field(T('ZRC','DEX'),'dx',p.dx) + field('INT','iq',p.iq) +
         field(T('WIT','VIT'),'ht',p.ht) + field(T('Wolne','Free'),'stat_point',p.stat_point) +
         '<span class="muted"> ' + T('suma na tym poziomie','total at this level') + ': ' + d.stat_allowance + '</span><br>' +
         field(T('Punkty umiejetnosci','Skill points'),'skill_point',p.skill_point) +
         '<label> ' + T('Kon','Horse') + ': ' + p.horse_level + ' <span class="muted">(' +
         T('poziomu konia bota nie zmienia nikt - decyzja Tieru z 16.10','no hand sets a bot\'s horse - Tieru, 16 October') + ')</span></label><br>' +
         field(T('Blokada poziomu (0 = brak)','Level lock (0 = none)'),'lock_level',d.lock_level) +
         '<label><input type="checkbox" data-f="exp_unlocked"' + (d.exp_unlocked ? ' checked' : '') + '> exp_unlocked</label>' +
         '<p class="muted">' + T('Osobowość: przycisk "Wymuś osobowość" na karcie.','Personality: the card\'s "Force personality".') + '</p></div>';
    h += '<div data-pane="skills" style="display:none">' + (d.skills || []).map(function(s){
           var opts = '';
           for (var l = 0; l <= 40; ++l) {
             var name = l < 20 ? String(l) : l < 30 ? 'M' + (l - 19) : l < 40 ? 'G' + (l - 29) : 'P';
             opts += '<option value="' + l + '"' + (l == s.level ? ' selected' : '') + '>' + name + '</option>';
           }
           return '<label style="display:inline-block;width:46%;margin:2px">' + esc(s.name) + ' <select data-skill="' + s.vnum + '">' + opts + '</select></label>';
         }).join('') + '</div>';
    function itemRows(filter){
      return d.items.filter(filter).map(function(it){
        var where = it.window === 'EQUIPMENT' ? (SLOT[it.pos] || ('#' + it.pos)) : it.window + ' ' + it.pos;
        var plus = it.family.map(function(v){ return '<option value="' + v + '"' + (v == it.vnum ? ' selected' : '') + '>+' + (v % 10) + ' (' + v + ')</option>'; }).join('');
        var attrs = '';
        for (var i = 0; i < 7; ++i){
          var current=Number(it['attrtype'+i]),kinds=Object.keys(d.attrs||{}).filter(function(k){return (d.attrs[k]||[]).indexOf(it.attr_column)>=0;}).map(Number);
          if(kinds.indexOf(0)<0)kinds.unshift(0);if(kinds.indexOf(current)<0)kinds.push(current);
          attrs+='<div class="be-attr"><select data-a="t'+i+'">'+kinds.map(function(kind){return '<option value="'+kind+'"'+(kind===current?' selected':'')+'>'+esc(kind&&window.formatApply?formatApply(kind,0):T('Brak','None'))+'</option>';}).join('')+'</select><input data-a="v'+i+'" value="'+it['attrvalue'+i]+'" style="width:65px"></div>';
        }
        var icon=window.getItemIconUrl?getItemIconUrl(it.vnum):'/static/icons/'+('00000'+it.vnum).slice(-5)+'.png';
        return '<details data-item="' + it.id + '"><summary><img alt="" src="'+esc(icon)+'"><b>' + esc(where) + '</b> ' + esc(it.name) + ' ×'+it.count+' <span class="btn btn-sm">'+T('Edytuj','Edit')+'</span></summary><div class="be-item-form">'+
          ' vnum <input data-a="vnum" value="' + it.vnum + '" style="width:70px"> <select data-a="plus">' + plus + '</select>' +
          (it.stack > 1 ? ' ' + T('ilosc','count') + ' <input data-a="count" value="' + it.count + '" style="width:50px"> /' + it.stack : '') +
          '<br>' + T('Bonusy','Lines') + ': ' + attrs + '<br>' + T('Gniazda','Sockets') + ': ' +
          [0,1,2].map(function(k){
            if(it.attr_column!=='weapon' && it.attr_column!=='body')return '<input data-a="s'+k+'" value="'+it['socket'+k]+'" style="width:90px">';
            var current=Number(it['socket'+k]), stones=[{vnum:0,name:T('Brak gniazda','No socket')},{vnum:1,name:T('Wolne gniazdo','Free socket')},{vnum:2,name:T('Wolne złote gniazdo','Free golden socket')},{vnum:28960,name:T('Pęknięty Kamień','Broken Stone')}].concat(d.stones||[]);
            if(!stones.some(function(s){return s.vnum===current;}))stones.push({vnum:current,name:'#'+current});
            return '<select data-a="s'+k+'">'+stones.map(function(s){return '<option value="'+s.vnum+'"'+(s.vnum===current?' selected':'')+'>'+esc(s.name)+'</option>';}).join('')+'</select>';
          }).join(' ') +
          ' <label><input type="checkbox" data-a="del"> ' + T('Usuń','Delete') + '</label>' +
          (it.window === 'EQUIPMENT' || it.window === 'SAFEBOX' ? ' <label><input type="checkbox" data-a="toBag"> ' + T('Do torby','To the bag') + '</label>' : '') +
          (it.window === 'INVENTORY' ? ' <label><input type="checkbox" data-a="toBox"> ' + T('Do magazynu','To the storeroom') + '</label>' : '') + '</div></details>';
      }).join('') || '<p class="muted">-</p>';
    }
    h += '<div data-pane="eq" style="display:none">' + itemRows(function(it){ return it.window === 'EQUIPMENT'; }) + '</div>';
    h += '<div data-pane="ds" style="display:none">' + itemRows(function(it){ return it.window === 'DRAGON_SOUL_INVENTORY'; }) + '</div>';
    h += '<div data-pane="bag" style="display:none">' + itemRows(function(it){ return it.window === 'INVENTORY' || it.window === 'SAFEBOX'; }) + '</div>';
    h += '<div data-pane="hist" style="display:none">' + (d.history.length ? d.history.map(function(r){
           return '<div style="font-size:11px;border-bottom:1px solid #332814">' + esc(r.at) + ' ' + esc(r.who) + ' <b>' + esc(r.field) + '</b>: ' +
             esc(String(r.before).slice(0, 160)) + ' &rarr; ' + esc(String(r.after).slice(0, 160)) +
             (r.undone ? ' <i>(' + T('cofniete','undone') + ')</i>' : ' <button type="button" class="btn btn-sm" data-undo="' + r.job + '">' + T('Cofnij','Undo') + '</button>') + '</div>';
         }).join('') : '<p class="muted">-</p>') + '</div>';
    h += '</div><div class="be-footer"><label><input type="checkbox" id="beProtect"> ' + T('Chroń na stałe (inaczej 24 h)','Protect for good (else 24 h)') + '</label> ' +
         '<button type="button" class="btn" id="beSave">' + T('Zapisz','Save') + '</button> <span id="beStatus"></span></div>';
    return h;
  }

  function collect(box){
    var d = state, edit = {opened: d.opened, player: {}, skills: {}, items: {}};
    box.querySelectorAll('[data-f]').forEach(function(el){
      var f = el.getAttribute('data-f');
      if (f === 'exp_unlocked') { if (el.checked !== d.exp_unlocked) edit.exp_unlocked = el.checked ? 1 : 0; return; }
      if (f === 'lock_level') { if (String(el.value) !== String(d.lock_level)) edit.lock_level = parseInt(el.value, 10) || 0; return; }
      if (String(el.value) !== String(d.player[f])) edit.player[f] = el.value;
    });
    box.querySelectorAll('[data-skill]').forEach(function(el){
      var s = d.skills.filter(function(x){ return String(x.vnum) === el.getAttribute('data-skill'); })[0];
      if (s && String(s.level) !== el.value) edit.skills[s.vnum] = parseInt(el.value, 10);
    });
    box.querySelectorAll('[data-item]').forEach(function(row){
      var id = row.getAttribute('data-item');
      var it = d.items.filter(function(x){ return String(x.id) === id; })[0];
      var g = function(a){ var el = row.querySelector('[data-a="' + a + '"]'); return el; };
      if (g('del').checked) { edit.items[id] = {'delete': true}; return; }
      var c = {}, vnum = g('vnum').value;
      if (g('plus') && g('plus').value !== String(it.vnum) && vnum === String(it.vnum)) vnum = g('plus').value;
      if (vnum !== String(it.vnum)) c.vnum = vnum;
      if (g('count') && g('count').value !== String(it.count)) c.count = g('count').value;
      for (var i = 0; i < 7; ++i) {
        if (g('t' + i).value !== String(it['attrtype' + i])) c['attrtype' + i] = g('t' + i).value;
        if (g('v' + i).value !== String(it['attrvalue' + i])) c['attrvalue' + i] = g('v' + i).value;
      }
      for (var k = 0; k < 3; ++k) if (g('s' + k).value !== String(it['socket' + k])) c['socket' + k] = g('s' + k).value;
      if (g('toBag') && g('toBag').checked) c.move = 'INVENTORY';
      if (g('toBox') && g('toBox').checked) c.move = 'SAFEBOX';
      if (Object.keys(c).length) edit.items[id] = c;
    });
    edit.protect = box.querySelector('#beProtect').checked;
    return edit;
  }

  function post(url, edit){
    var form = new FormData();
    form.append('_csrf', state.csrf);
    if (edit) form.append('edit', JSON.stringify(edit));
    return fetch(url, {method:'POST', body: form, credentials:'same-origin'}).then(function(r){ return r.json(); });
  }

  function follow(box, job){
    var status = box.querySelector('#beStatus');
    var tries = 0;
    (function poll(){
      fetch('/bot_editor/job/' + job, {cache:'no-store'}).then(function(r){ return r.json(); }).then(function(a){
        status.textContent = (a.state === 'hold' ? '⏳ ' : '') + a.text;
        if (a.state === 'hold' && ++tries < 120) setTimeout(poll, 2000);
        else if (a.state === 'applied') setTimeout(function(){ openEditor(state.pid); }, 1500);
      }).catch(function(){ if (++tries < 120) setTimeout(poll, 3000); });
    })();
  }

  function openEditor(pid){
    fetch('/bot_editor/' + pid + '/data', {cache:'no-store'}).then(function(r){ return r.json(); }).then(function(d){
      if (!d.ok) { alert(d.error); return; }
      d.pid = pid; state = d;
      var box = document.getElementById('botEditorBox');
      if (!box) {
        box = document.createElement('div'); box.id = 'botEditorBox'; box.className = 'modal-box be-editor';
        document.body.appendChild(box);
      }
      box.innerHTML = render(d);
      box.querySelector('#beClose').onclick = function(){ box.remove(); };
      box.querySelectorAll('[data-tab]').forEach(function(b){ b.onclick = function(){
        box.querySelectorAll('[data-tab]').forEach(function(t){t.classList.toggle('active',t===b);});
        box.querySelectorAll('[data-pane]').forEach(function(p){ p.style.display = p.getAttribute('data-pane') === b.getAttribute('data-tab') ? '' : 'none'; });
      }; });
      box.querySelectorAll('[data-undo]').forEach(function(b){ b.onclick = function(){
        if (!confirm(T('Cofnac te zmiane? Bot zostanie na chwile wylogowany.','Undo this edit? The bot is logged out for a moment.'))) return;
        post('/bot_editor/undo/' + b.getAttribute('data-undo')).then(function(a){
          if (!a.ok) { alert(a.error); return; } follow(box, a.job); });
      }; });
      box.querySelector('#beSave').onclick = function(){
        var edit = collect(box);
        post('/bot_editor/' + pid + '/save', edit).then(function(a){
          if (!a.ok && a.confirm) {
            if (!confirm(T('Ostrzezenia:\n','Warnings:\n') + a.warnings.join('\n') + T('\n\nZapisac mimo to?','\n\nSave anyway?'))) return;
            edit.accept_warnings = true;
            return post('/bot_editor/' + pid + '/save', edit);
          }
          return a;
        }).then(function(a){
          if (!a) return;
          if (!a.ok) { alert(a.error); return; }
          follow(box, a.job);
        });
      };
    });
  }

  var observer = new MutationObserver(addButton);
  function watch(){
    var content = document.getElementById('botModalContent');
    if (content) observer.observe(content, {childList:true, subtree:false});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watch); else watch();
})();
"""
