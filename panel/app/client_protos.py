#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""The game client's item and monster tables, built from this world's.

    python3 client_protos.py build --base <dir with gamedata.index/.data> --out <dir>
                                   [--report <file.json>]
    python3 client_protos.py check --base <dir>

Launcher report 7b1bc872 and Kordyl13, 7 October: Lostek's database editor
changes world.item_proto and world.mob_proto, the server takes the change at
its next start, and the client goes on showing the old item - its built-in
bonuses, its attack values, the price an NPC pays for it in the tooltip and in
the sell question. The client never asks the server what an item is: it reads
gamedata/item_proto and gamedata/mob_proto out of its own pack/gamedata
(LoadLocaleData, PythonApplication.cpp; the locale packs' item_proto are never
loaded, docs/notes/client.md), so this writes the world's two tables into a
copy of the client's own gamedata pack.

What a table is, measured on the shipped client (2.0.83, and 2.0.84 the same) and
not guessed:

  item_proto  "MIPX", version 1, stride 184 (TItemTable_r156, ItemData.h),
              the row count and the size of one CLZObject under
              s_adwItemProtoKey (ItemManager.cpp), plus the one DWORD more
              CLZObject::GetSize counts.
  mob_proto   "MMPT", the row count and the size of one CLZObject under
              s_adwMobProtoKey (PythonNonPlayer.cpp), rows of 256 bytes
              (TMobTable_r255: the fraction byte after bRevivePoint).

Both decode, re-encode and compare to the byte (tests/client_protos_test.py,
with python-lzo where it is installed), and so does the whole pack.

A row is the server's where the server has the field - the same columns the
db core reads (InitializeItemTableFromDB / InitializeMobTableFromDB,
ClientManagerBoot.cpp), cast to the client's field the way str_to_number casts
it for the server, plus mob_color and mount_capacity, which the db core leaves
alone and the client reads - and the client's own where it is the client's:

  * szName, the package's original (Korean) name, which no reader sees and the
    client hashes only to find a fallback icon (CItemManager::LoadItemTable);
  * the item sockets (0 in the client's table, -1 the world's default);
  * the item's vnum range, which is the server's rule anyway (99 for a Dragon
    Stone, ENABLE_AUTODETECT_VNUMRANGE, 0 for the rest);
  * the Polish name (szLocaleName) where the world's is no name at all
    ("NoNAme", empty) or the client's word for word without its Polish letters
    - the migrator writes the ItemShop's "Auto Lowy (8h)" in ASCII and protoify
    the client's "Auto Łowy (8h)", and the client should keep its letters.

Polish reads the names from these tables (there is no locale/pl/item_names.txt
or mob_names.txt), so an item renamed in the editor shows its new name to a
Polish reader. The other languages read locale/<lang>/item_names.txt and
mob_names.txt from the 91 MB locale pack, which this does not rewrite: they
keep their translation of the item, and the report lists the renamed vnums.

A row the client has and the world does not (the Easter rings) stays as it is:
the server cannot make the item. A row the world has and the client does not
(a new item) is added after the client's own rows, so no existing item's
fallback icon moves; it shows the icon of its +0 or of a bowl until
item_list.txt names one.

Every other file of the pack is carried byte for byte, its on-disk object
untouched, and a world whose tables say what the client's already say gives
back the base pack's two files unchanged. What is written is read back - the
index, every object's CRC, the two tables row by row against what was meant -
before anything else may install it, and the LZO here is the decoder the
client's lzo1x_decompress is (strict: the exact length, the end marker, every
byte of the stream consumed) and an LZO1X-1 style encoder, pure Python, so the
panel needs no compiled module. Only the published pack keys are used: our own
key (client_pack_key.py) is the private repository's and never in a package.
"""
import argparse
import hashlib
import io
import json
import os
import struct
import sys
import time
import unicodedata
import zipfile
import zlib

FORMAT = 1

# The mt2009 client's PackMakerLite keys (pack/PackMakerLite.json of every
# player's client; tools/eterpack.py's "mt2009" profile).
PACK_INDEX_KEY = (533489241, 64592187, 413438084, 181131063)
PACK_DATA_KEY = (183730646, 760506105, 952721118, 990624796)
# ItemManager.cpp s_adwItemProtoKey, PythonNonPlayer.cpp s_adwMobProtoKey.
ITEM_PROTO_KEY = (173217, 72619434, 408587239, 27973291)
MOB_PROTO_KEY = (4813894, 18955, 552631, 6822045)

ITEM_PROTO = "gamedata/item_proto"
MOB_PROTO = "gamedata/mob_proto"
PACK_FILES = ("gamedata.index", "gamedata.data")

FOURCC_LZO = b"MCOZ"
FOURCC_INDEX = b"EPKD"
INDEX_ENTRY = struct.Struct("<I161s3xIIIIIB3x")
MASK32 = 0xFFFFFFFF

ITEM_DS = 29            # item_length.h EItemTypes
NAME_LEN_ITEM = 32      # ITEM_NAME_MAX_LEN (the szName/szLocaleName arrays hold one more)
NAME_LEN_MOB = 24       # CHARACTER_NAME_MAX_LEN
FOLDER_LEN = 64

# A world whose table is this much smaller than the client's is not the world
# the client belongs to, or not a whole one.
MIN_ROW_SHARE = 0.5


class ProtoError(Exception):
    """A pack, a table or a world this refuses to build from; the message says why."""


# =============================================================================
#  LZO1X
# =============================================================================
def lzo1x_decompress(src, out_len):
    """lzo1x_decompress as the client runs it, but bounds-checked.

    Refuses anything the client's own decoder could not take: a short or long
    result, a stream that does not end on its marker exactly at its last byte
    (the client's lzo1x_decompress returns LZO_E_INPUT_NOT_CONSUMED for that and
    CLZObject::Decompress fails), a back reference before the start.
    """
    src = bytes(src)
    n = len(src)
    out = bytearray()
    ip = 0

    def need(k):
        if ip + k > n:
            raise ProtoError("lzo: the stream ends early")

    def literal(count):
        nonlocal ip
        need(count)
        out.extend(src[ip:ip + count])
        ip += count
        if len(out) > out_len:
            raise ProtoError("lzo: the result is longer than its header says")

    def copy(dist, length):
        if dist <= 0 or dist > len(out):
            raise ProtoError("lzo: a match reaches before the start")
        start = len(out) - dist
        if dist >= length:
            out.extend(out[start:start + length])
        else:
            pattern = bytes(out[start:])
            out.extend((pattern * (length // dist + 1))[:length])
        if len(out) > out_len:
            raise ProtoError("lzo: the result is longer than its header says")

    def extended(t, base):
        nonlocal ip
        while True:
            need(1)
            if src[ip] != 0:
                break
            t += 255
            ip += 1
        t += base + src[ip]
        ip += 1
        return t

    need(1)
    state = "top"
    t = 0
    if src[0] > 17:
        t = src[0] - 17
        ip = 1
        if t < 4:
            literal(t)
            need(1)
            t = src[ip]
            ip += 1
            state = "match"
        else:
            literal(t)
            state = "first"
    while True:
        if state == "top":
            need(1)
            t = src[ip]
            ip += 1
            if t < 16:
                if t == 0:
                    t = extended(0, 15)
                literal(t + 3)
                state = "first"
                continue
            state = "match"
        if state == "first":
            need(1)
            t = src[ip]
            ip += 1
            if t < 16:
                need(1)
                dist = 1 + 0x0800 + (t >> 2) + (src[ip] << 2)
                ip += 1
                copy(dist, 3)
                state = "done"
            else:
                state = "match"
        if state == "match":
            if t >= 64:
                need(1)
                dist = 1 + ((t >> 2) & 7) + (src[ip] << 3)
                ip += 1
                copy(dist, (t >> 5) + 1)
            elif t >= 32:
                t &= 31
                if t == 0:
                    t = extended(0, 31)
                need(2)
                dist = 1 + (src[ip] >> 2) + (src[ip + 1] << 6)
                ip += 2
                copy(dist, t + 2)
            elif t >= 16:
                high = (t & 8) << 11
                t &= 7
                if t == 0:
                    t = extended(0, 7)
                need(2)
                low = (src[ip] >> 2) + (src[ip + 1] << 6)
                ip += 2
                if high + low == 0:
                    if len(out) != out_len:
                        raise ProtoError("lzo: %d bytes, the header says %d" % (len(out), out_len))
                    if ip != n:
                        raise ProtoError("lzo: %d bytes after the end marker" % (n - ip))
                    return bytes(out)
                copy(high + low + 0x4000, t + 2)
            else:
                need(1)
                dist = 1 + (t >> 2) + (src[ip] << 2)
                ip += 1
                copy(dist, 2)
            state = "done"
        # match_done: the low two bits of the byte two back say how many
        # literals follow before the next instruction.
        trailing = src[ip - 2] & 3
        if trailing == 0:
            state = "top"
            continue
        literal(trailing)
        need(1)
        t = src[ip]
        ip += 1
        state = "match"


def lzo1x_compress(src):
    """An LZO1X stream of `src`: greedy matches from a table of the last
    position of every four bytes, LZO1X-1's skip over incompressible runs, and
    nothing but the M2/M3/M4 matches and literal runs lzo1x_decompress reads.
    Not the bytes python-lzo writes (its level 9 is lzo1x_999), the same data."""
    src = bytes(src)
    n = len(src)
    out = bytearray()
    last = [-1]                 # where the previous match's "two back" byte is

    def literals(start, end):
        count = end - start
        if count == 0:
            return
        if not out:
            # The stream's first instruction: a byte over 17 is a literal run
            # of that many less 17, of any length from one.
            if count <= 238:
                out.append(17 + count)
            else:
                rest = count - 18
                out.append(0)
                while rest > 255:
                    rest -= 255
                    out.append(0)
                out.append(rest)
        elif count <= 3:
            out[last[0]] |= count
        elif count <= 18:
            out.append(count - 3)
        else:
            rest = count - 18
            out.append(0)
            while rest > 255:
                rest -= 255
                out.append(0)
            out.append(rest)
        out.extend(src[start:end])

    def match(dist, length):
        if length <= 8 and dist <= 0x0800:
            d = dist - 1
            out.append(((length - 1) << 5) | ((d & 7) << 2))
            out.append(d >> 3)
        elif dist <= 0x4000:
            d = dist - 1
            if length <= 33:
                out.append(32 | (length - 2))
            else:
                out.append(32)
                rest = length - 33
                while rest > 255:
                    rest -= 255
                    out.append(0)
                out.append(rest)
            out.append((d << 2) & 0xFF)
            out.append(d >> 6)
        else:
            d = dist - 0x4000
            if length <= 9:
                out.append(16 | ((d >> 11) & 8) | (length - 2))
            else:
                out.append(16 | ((d >> 11) & 8))
                rest = length - 9
                while rest > 255:
                    rest -= 255
                    out.append(0)
                out.append(rest)
            out.append((d << 2) & 0xFF)
            out.append((d >> 6) & 0xFF)
        last[0] = len(out) - 2

    table = {}
    i = 0
    pending = 0
    stop = n - 4
    while i <= stop:
        key = src[i:i + 4]
        cand = table.get(key)
        table[key] = i
        if cand is None or i - cand > 0xBFFF:
            i += 1 + ((i - pending) >> 5)
            continue
        room = n - i
        length = 4
        while length + 32 <= room and src[cand + length:cand + length + 32] == src[i + length:i + length + 32]:
            length += 32
        while length < room and src[cand + length] == src[i + length]:
            length += 1
        literals(pending, i)
        match(i - cand, length)
        i += length
        pending = i
    literals(pending, n)
    out.extend(b"\x11\x00\x00")
    return bytes(out)


try:                                    # the m2-eterpack image and a developer's machine
    import lzo as _lzo                  # noqa: F401
except Exception:                       # noqa: BLE001 - the panel has none, and needs none
    _lzo = None


def compress(data, native=None):
    """LZO1X: python-lzo's level 9 where it is installed (the bytes protoify
    and eterpack write), the encoder above otherwise. Either way the result is
    decoded again by lzo1x_decompress before anything ships it."""
    use_native = (_lzo is not None) if native is None else native
    if use_native:
        if _lzo is None:
            raise ProtoError("python-lzo is not installed")
        return _lzo.compress(bytes(data), 9, False)
    return lzo1x_compress(data)


# =============================================================================
#  XTEA and the CLZObject
# =============================================================================
_DELTA = 0x9E3779B9


def xtea(data, key, encrypt):
    """The client's tea_encrypt/tea_decrypt (XTEA, 32 rounds) over whole
    eight-byte blocks; a tail shorter than a block is carried as it is."""
    data = bytes(data)
    whole = len(data) // 8
    words = list(struct.unpack_from("<%dI" % (whole * 2), data, 0))
    k0, k1, k2, k3 = key
    k = (k0, k1, k2, k3)
    out = []
    append = out.append
    if encrypt:
        for b in range(whole):
            v0 = words[2 * b]
            v1 = words[2 * b + 1]
            s = 0
            for _ in range(32):
                v0 = (v0 + ((((v1 << 4) ^ (v1 >> 5)) + v1) ^ (s + k[s & 3]))) & MASK32
                s = (s + _DELTA) & MASK32
                v1 = (v1 + ((((v0 << 4) ^ (v0 >> 5)) + v0) ^ (s + k[(s >> 11) & 3]))) & MASK32
            append(v0)
            append(v1)
    else:
        start = (_DELTA * 32) & MASK32
        for b in range(whole):
            v0 = words[2 * b]
            v1 = words[2 * b + 1]
            s = start
            for _ in range(32):
                v1 = (v1 - ((((v0 << 4) ^ (v0 >> 5)) + v0) ^ (s + k[(s >> 11) & 3]))) & MASK32
                s = (s - _DELTA) & MASK32
                v0 = (v0 - ((((v1 << 4) ^ (v1 >> 5)) + v1) ^ (s + k[s & 3]))) & MASK32
            append(v0)
            append(v1)
    return struct.pack("<%dI" % len(out), *out) + data[whole * 8:]


def lz_unpack(blob, key):
    """One CLZObject: "MCOZ", the encrypted size, the compressed size, the real
    size, then the ciphered "MCOZ" and stream (or the plain one)."""
    if len(blob) < 16:
        raise ProtoError("lzo object: too short")
    fourcc, enc, comp, real = struct.unpack_from("<4sIII", blob, 0)
    if fourcc != FOURCC_LZO:
        raise ProtoError("lzo object: no MCOZ header")
    if enc:
        if 16 + enc > len(blob) or enc < comp + 4:
            raise ProtoError("lzo object: its sizes do not fit")
        body = xtea(blob[16:16 + enc], key, False)
        if body[:4] != FOURCC_LZO:
            raise ProtoError("lzo object: not under the key this expects")
        return lzo1x_decompress(body[4:4 + comp], real)
    if blob[16:20] != FOURCC_LZO or 20 + comp > len(blob):
        raise ProtoError("lzo object: a plain object without its inner MCOZ")
    return lzo1x_decompress(blob[20:20 + comp], real)


def lz_pack(data, key, native=None):
    """The object CLZObject::Compress + Encrypt writes: the mt2009 client ciphers
    dwCompressedSize + 19 bytes rounded up to the block, the fourcc, the stream
    and the zeros after it (tools/eterpack.py's lzo_pack, packmakerlite)."""
    comp = compress(data, native)
    body = FOURCC_LZO + comp
    target = len(body) + 15
    body += bytes((-target) % 8 + (target - len(body)))
    return struct.pack("<4sIII", FOURCC_LZO, len(body), len(comp), len(data)) + xtea(body, key, True)


# =============================================================================
#  EterPack (the mt2009 client's PackMakerLite layout)
# =============================================================================
class Entry(object):
    __slots__ = ("id", "name", "name_crc", "slot", "size", "crc", "pos", "type", "blob")

    def key(self):
        return self.name.replace("\\", "/").lower()


def read_pack(index_bytes, data_bytes):
    """The index and every entry's object as it lies in the .data file."""
    index = lz_unpack(index_bytes, PACK_INDEX_KEY)
    if len(index) < 12:
        raise ProtoError("pack index: too short")
    fourcc, version, count = struct.unpack_from("<4sII", index, 0)
    if fourcc != FOURCC_INDEX or 12 + count * INDEX_ENTRY.size != len(index):
        raise ProtoError("pack index: not an EterPack index under the published key")
    entries = []
    for i in range(count):
        e = Entry()
        (e.id, name, e.name_crc, e.slot, e.size, e.crc, e.pos, e.type) = \
            INDEX_ENTRY.unpack_from(index, 12 + i * INDEX_ENTRY.size)
        e.name = name.split(b"\0", 1)[0].decode("latin-1")
        if e.pos + e.size > len(data_bytes):
            raise ProtoError("pack: %s lies past the end of the data file" % e.name)
        e.blob = bytes(data_bytes[e.pos:e.pos + e.size])
        if zlib.crc32(e.blob) & MASK32 != e.crc:
            raise ProtoError("pack: %s does not match its CRC" % e.name)
        entries.append(e)
    return version, entries


def entry_data(e):
    if e.type == 0:
        return e.blob
    if e.type == 2:
        return lz_unpack(e.blob, PACK_DATA_KEY)
    if e.type == 1:
        return lz_unpack(e.blob, None)
    raise ProtoError("pack: %s has type %d" % (e.name, e.type))


def entry_blob(data, typ, native=None):
    """An entry's object as PackMakerLite lays it: the object and the DWORD
    CLZObject::GetSize counts after it."""
    if typ == 2:
        return lz_pack(data, PACK_DATA_KEY, native) + bytes(4)
    if typ == 0:
        return bytes(data)
    raise ProtoError("pack: this writes types 0 and 2 only, not %d" % typ)


def write_pack(version, entries, native=None):
    """(index bytes, data bytes). Each object at a 256-byte slot, data_size its
    exact length, data_crc the CRC32 of those bytes (ENABLE_CRC32_CHECK)."""
    data = bytearray()
    rows = []
    for i, e in enumerate(entries):
        blob = e.blob
        slot = (len(blob) + 255) // 256 * 256
        pos = len(data)
        data += blob
        data += bytes(slot - len(blob))
        nm = e.name.encode("latin-1")
        rows.append(INDEX_ENTRY.pack(e.id if e.id is not None else i, nm, zlib.crc32(nm.lower()) & MASK32,
                                     slot, len(blob), zlib.crc32(blob) & MASK32, pos, e.type))
    index = struct.pack("<4sII", FOURCC_INDEX, version, len(entries)) + b"".join(rows)
    return lz_pack(index, PACK_INDEX_KEY, native), bytes(data)


# =============================================================================
#  The two tables
# =============================================================================
# (name, struct code); 'raw' fields are kept as bytes.
ITEM_FIELDS = (
    ("vnum", "I"), ("vnum_range", "I"), ("name", "33s"), ("locale_name", "33s"),
    ("type", "B"), ("subtype", "B"), ("weight", "B"), ("size", "B"), ("stack", "I"),
    ("antiflag", "I"), ("flag", "I"), ("wearflag", "I"), ("immuneflag", "I"),
    ("buy_price", "Q"), ("sell_price", "Q"),
    ("limittype0", "B"), ("limitvalue0", "I"), ("limittype1", "B"), ("limitvalue1", "I"),
    ("applytype0", "B"), ("applyvalue0", "I"), ("applytype1", "B"), ("applyvalue1", "I"),
    ("applytype2", "B"), ("applyvalue2", "I"),
    ("value0", "I"), ("value1", "I"), ("value2", "I"), ("value3", "I"), ("value4", "I"), ("value5", "I"),
    ("socket0", "I"), ("socket1", "I"), ("socket2", "I"),
    ("refined_vnum", "I"), ("refine_set", "H"), ("magic_pct", "B"), ("specular", "B"), ("socket_pct", "B"),
)
MOB_FIELDS = (
    ("vnum", "I"), ("name", "25s"), ("locale_name", "25s"),
    ("type", "B"), ("rank", "B"), ("battle_type", "B"), ("level", "B"), ("size", "B"),
    ("gold_min", "I"), ("gold_max", "I"), ("exp", "I"), ("max_hp", "I"),
    ("regen_cycle", "B"), ("regen_percent", "B"), ("def", "H"),
    ("ai_flag", "I"), ("race_flag", "I"), ("immune_flag", "I"),
    ("st", "B"), ("dx", "B"), ("ht", "B"), ("iq", "B"), ("damage_min", "I"), ("damage_max", "I"),
    ("attack_speed", "H"), ("move_speed", "H"), ("aggressive_hp_pct", "B"),
    ("aggressive_sight", "H"), ("attack_range", "H"),
    ("enchants", "6s"), ("resists", "11s"),
    ("resurrection_vnum", "I"), ("drop_item", "I"), ("mount_capacity", "B"), ("on_click", "B"),
    ("empire", "B"), ("folder", "65s"), ("dam_multiply", "f"), ("summon", "I"), ("drain_sp", "I"),
    ("mob_color", "I"), ("polymorph_item", "I"),
    ("skill_vnum0", "I"), ("skill_level0", "B"), ("skill_vnum1", "I"), ("skill_level1", "B"),
    ("skill_vnum2", "I"), ("skill_level2", "B"), ("skill_vnum3", "I"), ("skill_level3", "B"),
    ("skill_vnum4", "I"), ("skill_level4", "B"),
    ("sp_berserk", "B"), ("sp_stoneskin", "B"), ("sp_godspeed", "B"), ("sp_deathblow", "B"),
    ("sp_revive", "B"), ("fraction", "B"),
)
ITEM_STRUCT = struct.Struct("<" + "".join(code for _, code in ITEM_FIELDS))
MOB_STRUCT = struct.Struct("<" + "".join(code for _, code in MOB_FIELDS))
ITEM_STRIDE = 184
MOB_ROW = 256
assert ITEM_STRUCT.size == ITEM_STRIDE and MOB_STRUCT.size == MOB_ROW
ITEM_NAMES = tuple(name for name, _ in ITEM_FIELDS)
MOB_NAMES = tuple(name for name, _ in MOB_FIELDS)
ENCHANTS = ("enchant_curse", "enchant_slow", "enchant_poison", "enchant_stun", "enchant_critical",
            "enchant_penetrate")
RESISTS = ("resist_sword", "resist_twohand", "resist_dagger", "resist_bell", "resist_fan", "resist_bow",
           "resist_fire", "resist_elect", "resist_magic", "resist_wind", "resist_poison")


def decode_rows(raw, layout, names):
    if len(raw) % layout.size:
        raise ProtoError("table: %d bytes are no whole number of %d-byte rows" % (len(raw), layout.size))
    return [dict(zip(names, layout.unpack_from(raw, at))) for at in range(0, len(raw), layout.size)]


def encode_rows(rows, layout, names):
    return b"".join(layout.pack(*[row[name] for name in names]) for row in rows)


def read_item_proto(blob):
    if len(blob) < 20:
        raise ProtoError("item_proto: too short")
    fourcc, version, stride, count, size = struct.unpack_from("<4sIIII", blob, 0)
    if (fourcc, version, stride) != (b"MIPX", 1, ITEM_STRIDE):
        raise ProtoError("item_proto: %r version %d stride %d is not the client's table this knows "
                         "(MIPX 1, 184)" % (fourcc, version, stride))
    if 20 + size > len(blob):
        raise ProtoError("item_proto: its object runs past the file")
    raw = lz_unpack(blob[20:20 + size], ITEM_PROTO_KEY)
    if len(raw) != count * ITEM_STRIDE:
        raise ProtoError("item_proto: %d rows of %d bytes are not %d bytes" % (count, ITEM_STRIDE, len(raw)))
    return raw


def write_item_proto(raw, native=None):
    # The object and the one DWORD more that CLZObject::GetSize counts, as the
    # package's own table carries it (protoify.py).
    obj = lz_pack(raw, ITEM_PROTO_KEY, native) + bytes(4)
    return struct.pack("<4sIIII", b"MIPX", 1, ITEM_STRIDE, len(raw) // ITEM_STRIDE, len(obj)) + obj


def read_mob_proto(blob):
    if len(blob) < 12:
        raise ProtoError("mob_proto: too short")
    fourcc, count, size = struct.unpack_from("<4sII", blob, 0)
    if fourcc != b"MMPT" or 12 + size > len(blob):
        raise ProtoError("mob_proto: %r is not the client's monster table this knows" % fourcc)
    raw = lz_unpack(blob[12:12 + size], MOB_PROTO_KEY)
    if not count or len(raw) != count * MOB_ROW:
        raise ProtoError("mob_proto: rows of %d bytes expected, %d bytes for %d rows" % (MOB_ROW, len(raw), count))
    return raw


def write_mob_proto(raw, native=None):
    obj = lz_pack(raw, MOB_PROTO_KEY, native) + bytes(4)
    return struct.pack("<4sII", b"MMPT", len(raw) // MOB_ROW, len(obj)) + obj


# =============================================================================
#  The world's rows
# =============================================================================
ITEM_COLUMNS = ("vnum", "name", "locale_name", "type", "subtype", "weight", "size", "stack", "antiflag",
                "flag", "wearflag", "immuneflag", "gold", "shop_buy_price", "refined_vnum", "refine_set",
                "magic_pct", "specular", "socket_pct", "limittype0", "limitvalue0", "limittype1", "limitvalue1",
                "applytype0", "applyvalue0", "applytype1", "applyvalue1", "applytype2", "applyvalue2",
                "value0", "value1", "value2", "value3", "value4", "value5")
MOB_COLUMNS = ("vnum", "name", "locale_name", "rank", "type", "battle_type", "level", "size", "ai_flag",
               "mount_capacity", "setRaceFlag", "setImmuneFlag", "empire", "folder", "on_click", "st", "dx",
               "ht", "iq", "damage_min", "damage_max", "max_hp", "regen_cycle", "regen_percent", "gold_min",
               "gold_max", "exp", "def", "attack_speed", "move_speed", "aggressive_hp_pct", "aggressive_sight",
               "attack_range", "drop_item", "resurrection_vnum") + ENCHANTS + RESISTS + (
               "dam_multiply", "summon", "drain_sp", "mob_color", "polymorph_item",
               "skill_level0", "skill_vnum0", "skill_level1", "skill_vnum1", "skill_level2", "skill_vnum2",
               "skill_level3", "skill_vnum3", "skill_level4", "skill_vnum4",
               "sp_berserk", "sp_stoneskin", "sp_godspeed", "sp_deathblow", "sp_revive", "fraction")
# Text columns come back as their stored bytes (HEX), sets and enums as the
# numbers the db core reads (`+0`).
_TEXT = ("name", "locale_name", "folder")
_SETS = ("immuneflag", "size", "ai_flag", "setRaceFlag", "setImmuneFlag")


def _select_sql(table, columns, kinds):
    parts = []
    for col in columns:
        q = "`%s`" % col
        if col in _TEXT:
            parts.append("HEX(%s) AS %s" % (q, q))
        elif col in _SETS and (table, col) in kinds:
            parts.append("(%s+0) AS %s" % (q, q))
        else:
            parts.append(q)
    return "SELECT %s FROM world.`%s` ORDER BY `vnum`" % (", ".join(parts), table)


def fetch_world(conn):
    """world.item_proto and world.mob_proto as {vnum: row}, through a PyMySQL
    (or any DB-API) connection the caller owns. Refuses a world without the
    columns the client's rows are made of."""
    cur = conn.cursor()
    try:
        tables = {}
        for table, needed in (("item_proto", ITEM_COLUMNS), ("mob_proto", MOB_COLUMNS)):
            cur.execute("SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = 'world' AND TABLE_NAME = %s", (table,))
            have = {}
            for row in cur.fetchall():
                name, dtype = (row["COLUMN_NAME"], row["DATA_TYPE"]) if isinstance(row, dict) else row
                if isinstance(name, bytes):
                    name = name.decode("ascii", "replace")
                if isinstance(dtype, bytes):
                    dtype = dtype.decode("ascii", "replace")
                have[name] = str(dtype).lower()
            if not have:
                raise ProtoError("world.%s: there is no such table (the client's tables are built from the "
                                 "mt2009 line's world database)" % table)
            missing = [c for c in needed if c not in have]
            if missing:
                raise ProtoError("world.%s has no %s - not the table the client's rows are made of"
                                 % (table, ", ".join(missing)))
            kinds = set((table, c) for c, dt in have.items() if dt in ("set", "enum"))
            cur.execute(_select_sql(table, needed, kinds))
            rows = {}
            for row in cur.fetchall():
                if not isinstance(row, dict):
                    row = dict(zip(needed, row))
                rec = {}
                for col in needed:
                    value = row[col]
                    if isinstance(value, bytes) and col not in _TEXT:
                        value = value.decode("ascii")
                    if col in _TEXT:
                        if isinstance(value, bytes):
                            value = value.decode("ascii")
                        value = bytes.fromhex(value or "")
                    rec[col] = value
                rows[int(rec["vnum"])] = rec
            tables[table] = rows
        return tables["item_proto"], tables["mob_proto"]
    finally:
        cur.close()


def world_checksum(items, mobs):
    """A digest of what this reads from the world, to tell a stale build from a fresh one."""
    h = hashlib.sha256()
    for table, rows, cols in (("item", items, ITEM_COLUMNS), ("mob", mobs, MOB_COLUMNS)):
        h.update(table.encode())
        for vnum in sorted(rows):
            row = rows[vnum]
            h.update(repr([row[c] for c in cols]).encode("utf-8", "replace"))
    return h.hexdigest()


def _int(value):
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("ascii")
    if value is None or value == "":
        return 0
    if isinstance(value, float):
        return int(value)
    return int(str(value).strip())


def _cast(value, code, field, vnum, notes):
    """str_to_number's cast into the client's field, which is what the server's
    own copy of the field holds too; a value that does not fit is noted."""
    number = _int(value)
    bits = {"B": 8, "H": 16, "I": 32, "Q": 64}[code]
    cast = number & ((1 << bits) - 1)
    signed_ok = -(1 << (bits - 1)) <= number < (1 << bits)
    if not signed_ok:
        notes.append({"vnum": vnum, "field": field, "value": number, "client": cast})
    return cast


def _text(raw, size):
    return raw[:size - 1].ljust(size, b"\0")


def _cstr(raw):
    return bytes(raw).split(b"\0", 1)[0]


_POLISH = {ord(a): b for a, b in zip("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")}


def _fold(raw):
    text = raw.decode("cp1250", "replace").translate(_POLISH)
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold().strip()


def _keeps_client_name(world_name, client_name):
    """No name in the world ("NoNAme", empty), or the client's own name without
    its Polish letters: the client keeps the name it has."""
    if not world_name.strip() or world_name.strip().lower() == b"noname":
        return True
    return client_name != world_name and _fold(client_name) == _fold(world_name)


def item_row(db, base, notes):
    vnum = _int(db["vnum"])
    row = dict(base) if base else {"vnum": vnum, "name": _text(db["name"], 33), "locale_name": b"",
                                   "socket0": 0, "socket1": 0, "socket2": 0}
    c = lambda col, code, field=None: _cast(db[col], code, field or col, vnum, notes)  # noqa: E731
    for col in ("type", "subtype", "weight", "size", "magic_pct", "specular", "socket_pct",
                "limittype0", "limittype1", "applytype0", "applytype1", "applytype2"):
        row[col] = c(col, "B")
    for col in ("stack", "antiflag", "flag", "wearflag", "immuneflag", "refined_vnum",
                "limitvalue0", "limitvalue1", "applyvalue0", "applyvalue1", "applyvalue2",
                "value0", "value1", "value2", "value3", "value4", "value5"):
        row[col] = c(col, "I")
    row["refine_set"] = c("refine_set", "H")
    # CItemData's dwIBuyItemPrice is the shop's `gold`, dwISellItemPrice what
    # a shop pays (`shop_buy_price`): 5986 of the shipped client's rows say so.
    row["buy_price"] = c("gold", "Q", "buy_price")
    row["sell_price"] = c("shop_buy_price", "Q", "sell_price")
    row["vnum_range"] = 99 if row["type"] == ITEM_DS else 0
    world_name = _cstr(db["locale_name"])[:NAME_LEN_ITEM]
    client_name = _cstr(row["locale_name"])
    if not base or not _keeps_client_name(world_name, client_name):
        row["locale_name"] = _text(world_name, 33)
    return row


def mob_row(db, base, notes):
    vnum = _int(db["vnum"])
    row = dict(base) if base else {"vnum": vnum, "name": _text(db["name"], 25), "locale_name": b""}
    c = lambda col, code, field=None: _cast(db[col], code, field or col, vnum, notes)  # noqa: E731
    for col in ("type", "rank", "battle_type", "level", "regen_cycle", "regen_percent", "st", "dx", "ht", "iq",
                "aggressive_hp_pct", "mount_capacity", "empire", "sp_berserk", "sp_stoneskin", "sp_godspeed",
                "sp_deathblow", "sp_revive", "fraction"):
        row[col] = c(col, "B")
    row["on_click"] = c("on_click", "B")
    row["size"] = c("size", "B")
    for col in ("gold_min", "gold_max", "exp", "max_hp", "damage_min", "damage_max", "resurrection_vnum",
                "drop_item", "summon", "drain_sp", "mob_color", "polymorph_item"):
        row[col] = c(col, "I")
    row["ai_flag"] = c("ai_flag", "I")
    row["race_flag"] = c("setRaceFlag", "I", "race_flag")
    row["immune_flag"] = c("setImmuneFlag", "I", "immune_flag")
    for col in ("def", "attack_speed", "move_speed", "aggressive_sight", "attack_range"):
        row[col] = c(col, "H")
    for i in range(5):
        row["skill_vnum%d" % i] = c("skill_vnum%d" % i, "I")
        row["skill_level%d" % i] = c("skill_level%d" % i, "B")
    row["enchants"] = bytes(c(col, "B") for col in ENCHANTS)
    row["resists"] = bytes(c(col, "B") for col in RESISTS)
    mult = db["dam_multiply"]
    row["dam_multiply"] = struct.unpack("<f", struct.pack("<f", float(mult or 0)))[0]
    row["folder"] = _text(_cstr(db["folder"])[:FOLDER_LEN], 65)
    world_name = _cstr(db["locale_name"])[:NAME_LEN_MOB]
    client_name = _cstr(row["locale_name"])
    if not base or not _keeps_client_name(world_name, client_name):
        row["locale_name"] = _text(world_name, 25)
    return row


def _same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        return struct.pack("<f", a) == struct.pack("<f", b)
    return a == b


def merge_rows(base_rows, world, make_row, names):
    """The client's rows in their order with the world's values over them, then
    the world's new rows by number. Returns (rows, report)."""
    notes = []
    by_vnum = {}
    for row in base_rows:
        by_vnum.setdefault(row["vnum"], row)
    out = []
    changed = {}
    renamed = []
    for row in base_rows:
        db = world.get(row["vnum"])
        if db is None:
            out.append(row)
            continue
        new = make_row(db, row, notes)
        fields = [n for n in names if not _same(row[n], new[n])]
        if fields:
            changed[row["vnum"]] = fields
            if "locale_name" in fields:
                renamed.append(row["vnum"])
        out.append(new)
    added = sorted(v for v in world if v not in by_vnum)
    for vnum in added:
        out.append(make_row(world[vnum], None, notes))
    report = {
        "rows": len(out),
        "client_rows": len(base_rows),
        "world_rows": len(world),
        "changed": len(changed),
        "changed_vnums": sorted(changed)[:400],
        "changed_fields": _field_counts(changed),
        "added": added[:400],
        "added_count": len(added),
        "client_only": sorted(v for v in by_vnum if v not in world)[:400],
        "renamed": sorted(renamed)[:400],
        "out_of_range": notes[:100],
    }
    return out, report, changed


def _field_counts(changed):
    counts = {}
    for fields in changed.values():
        for f in fields:
            counts[f] = counts.get(f, 0) + 1
    return dict(sorted(counts.items()))


# =============================================================================
#  The build
# =============================================================================
def sha256(data):
    return hashlib.sha256(data).hexdigest()


def pack_sha(index_bytes, data_bytes):
    """One digest of a pack: the two files' digests side by side, as the
    launcher and the friend's installer compute it too."""
    return sha256((sha256(index_bytes) + sha256(data_bytes)).encode("ascii"))


def _base_tables(index_bytes, data_bytes, items, mobs):
    version, entries = read_pack(index_bytes, data_bytes)
    by_key = {}
    for e in entries:
        by_key.setdefault(e.key(), e)
    for name in (ITEM_PROTO, MOB_PROTO):
        if name not in by_key:
            raise ProtoError("the client's gamedata pack has no %s" % name)
        if by_key[name].type != 2:
            raise ProtoError("%s is stored as type %d, not the type 2 this writes" % (name, by_key[name].type))
    item_raw = read_item_proto(entry_data(by_key[ITEM_PROTO]))
    mob_raw = read_mob_proto(entry_data(by_key[MOB_PROTO]))
    base_items = decode_rows(item_raw, ITEM_STRUCT, ITEM_NAMES)
    base_mobs = decode_rows(mob_raw, MOB_STRUCT, MOB_NAMES)
    for label, world, base in (("item_proto", items, base_items), ("mob_proto", mobs, base_mobs)):
        if len(world) < MIN_ROW_SHARE * len(base):
            raise ProtoError("world.%s has %d rows against the client's %d - refusing to make the client's "
                             "table from a world that is not whole" % (label, len(world), len(base)))
    return version, entries, item_raw, mob_raw, base_items, base_mobs


def diff(index_bytes, data_bytes, items, mobs):
    """What a build would change, without writing anything: the two reports
    and, per changed vnum, the fields (for the panel's page)."""
    _v, _e, _ir, _mr, base_items, base_mobs = _base_tables(index_bytes, data_bytes, items, mobs)
    _rows, item_report, item_changed = merge_rows(base_items, items, item_row, ITEM_NAMES)
    _rows, mob_report, mob_changed = merge_rows(base_mobs, mobs, mob_row, MOB_NAMES)
    return {"items": item_report, "mobs": mob_report, "item_fields": item_changed, "mob_fields": mob_changed,
            "changed": bool(item_changed or mob_changed or item_report["added_count"] or mob_report["added_count"]),
            "world": world_checksum(items, mobs)}


def build(index_bytes, data_bytes, items, mobs, native=None, clock=time.time):
    """The client's gamedata pack with this world's tables: (index, data, report).

    Raises ProtoError when the pack is not the client's this knows, or the
    world's tables are not ones a client table can be made from; never returns
    a pack it has not read back."""
    version, entries, item_raw, mob_raw, base_items, base_mobs = _base_tables(index_bytes, data_bytes, items, mobs)
    item_rows, item_report, _ = merge_rows(base_items, items, item_row, ITEM_NAMES)
    mob_rows, mob_report, _ = merge_rows(base_mobs, mobs, mob_row, MOB_NAMES)
    new_item_raw = encode_rows(item_rows, ITEM_STRUCT, ITEM_NAMES)
    new_mob_raw = encode_rows(mob_rows, MOB_STRUCT, MOB_NAMES)

    replaced = {}
    if new_item_raw != item_raw:
        replaced[ITEM_PROTO] = write_item_proto(new_item_raw, native)
    if new_mob_raw != mob_raw:
        replaced[MOB_PROTO] = write_mob_proto(new_mob_raw, native)
    if replaced:
        out_entries = []
        for e in entries:
            if e.key() in replaced:
                n = Entry()
                n.id, n.name, n.type = e.id, e.name, e.type
                n.blob = entry_blob(replaced[e.key()], e.type, native)
                out_entries.append(n)
            else:
                out_entries.append(e)
        out_index, out_data = write_pack(version, out_entries, native)
    else:
        out_index, out_data = bytes(index_bytes), bytes(data_bytes)
    verify(out_index, out_data, entries, {ITEM_PROTO: new_item_raw, MOB_PROTO: new_mob_raw})
    report = {
        "format": FORMAT,
        "built_at": int(clock()),
        "changed": bool(replaced),
        "items": item_report,
        "mobs": mob_report,
        "world": world_checksum(items, mobs),
        "base": {"index_sha256": sha256(index_bytes), "data_sha256": sha256(data_bytes),
                 "sha256": pack_sha(index_bytes, data_bytes)},
        "out": {"index_sha256": sha256(out_index), "data_sha256": sha256(out_data),
                "sha256": pack_sha(out_index, out_data)},
    }
    return out_index, out_data, report


def verify(index_bytes, data_bytes, base_entries, tables):
    """Read a written pack back as the client would, and hold it to what was meant."""
    version, entries = read_pack(index_bytes, data_bytes)
    if [(e.name, e.type) for e in entries] != [(e.name, e.type) for e in base_entries]:
        raise ProtoError("verify: the pack's files are not the base pack's")
    base = dict((e.key(), e) for e in base_entries)
    for e in entries:
        nm = e.name.encode("latin-1")
        if e.name_crc != zlib.crc32(nm.lower()) & MASK32:
            raise ProtoError("verify: %s has a wrong name CRC" % e.name)
        if e.slot < e.size or e.slot % 256 or e.pos % 256:
            raise ProtoError("verify: %s does not sit in a 256-byte slot" % e.name)
        if e.key() in tables:
            raw = tables[e.key()]
            data = entry_data(e)
            got = read_item_proto(data) if e.key() == ITEM_PROTO else read_mob_proto(data)
            if got != raw:
                raise ProtoError("verify: %s does not read back as written" % e.name)
        elif e.blob != base[e.key()].blob:
            raise ProtoError("verify: %s was not carried byte for byte" % e.name)
    return True


def build_files(base_dir, items, mobs, out_dir=None, native=None):
    """build() over <base_dir>/gamedata.index and .data; writes into out_dir when given."""
    paths = [os.path.join(base_dir, name) for name in PACK_FILES]
    for p in paths:
        if not os.path.isfile(p):
            raise ProtoError("no %s" % p)
    with open(paths[0], "rb") as f:
        index_bytes = f.read()
    with open(paths[1], "rb") as f:
        data_bytes = f.read()
    out_index, out_data, report = build(index_bytes, data_bytes, items, mobs, native)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        for name, blob in zip(PACK_FILES, (out_index, out_data)):
            tmp = os.path.join(out_dir, name + ".tmp")
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, os.path.join(out_dir, name))
    return out_index, out_data, report


# =============================================================================
#  The friend's package
# =============================================================================
README_PL = """Dane swiata dla klienta gry (Metin2 Singleplayer)
=================================================

Ten plik przygotowal panel serwera, na ktorym grasz. Zawiera tabele
przedmiotow i potworow tego swiata (statystyki, bonusy, ceny u NPC, poziomy,
polskie nazwy), zeby Twoj klient pokazywal to samo, co liczy serwer.

Jak wgrac:
 1. Zamknij gre.
 2. Rozpakuj CALE archiwum do folderu klienta - tam, gdzie lezy
    metin2client.exe (pojawia sie DaneSwiata.bat, DaneSwiata.ps1 i folder
    world-data; zaden plik gry nie zostaje przy tym nadpisany).
 3. Uruchom DaneSwiata.bat.

Program sprawdza, czy Twoj klient to ta sama wersja, dla ktorej plik
powstal ({client_version}), robi kopie oryginalnych plikow
pack\\gamedata.index i pack\\gamedata.data (world-data\\stock) i dopiero
wtedy je podmienia.

Po aktualizacji klienta (Aktualizuj.bat) uruchom DaneSwiata.bat jeszcze raz.
Jesli powie, ze wersja klienta sie nie zgadza, popros gospodarza o nowy plik
z panelu (strona "Dane dla klienta").

Powrot do oryginalu: DaneSwiata.bat przywroc

Swiat: {world}
Zbudowano: {built}
"""

README_EN = """World data for the game client (Metin2 Singleplayer)
====================================================

The panel of the server you play on made this file. It holds this world's
item and monster tables (stats, bonuses, NPC prices, levels, Polish names), so
that your client shows what the server counts.

How to install:
 1. Close the game.
 2. Extract the WHOLE archive into the client folder - where metin2client.exe
    is (DaneSwiata.bat, DaneSwiata.ps1 and a world-data folder appear; no game
    file is overwritten by the extraction).
 3. Run DaneSwiata.bat.

It checks that your client is the version this file was made for
({client_version}), backs up the original pack\\gamedata.index and
pack\\gamedata.data (world-data\\stock) and only then replaces them.

After a client update (Aktualizuj.bat) run DaneSwiata.bat again. If it says
the client version does not match, ask the host for a new file from the panel
(the "Client data" page).

Back to the original: DaneSwiata.bat restore

World: {world}
Built: {built}
"""

INSTALLER_BAT = (b"@echo off\r\n"
                 b"cd /d \"%~dp0\"\r\n"
                 b"powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0DaneSwiata.ps1\" %*\r\n"
                 b"echo.\r\n"
                 b"pause\r\n")


def installer_script():
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "client_protos_install.ps1"),):
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    raise ProtoError("client_protos_install.ps1 is missing beside client_protos.py")


def make_zip(out_index, out_data, report, base_info=None, world_label="", clock=time.time):
    """The friend's zip: world-data\\ with the pack, its manifest and the stock
    pack's identity, the installer and the two readmes. Nothing in it lands on
    a game file when it is extracted; DaneSwiata.ps1 checks before it copies."""
    base_info = dict(base_info or {})
    manifest = {
        "format": FORMAT,
        "kind": "metin2-world-data",
        "client_version": base_info.get("client_version", ""),
        "world": world_label,
        "built_at": report.get("built_at", int(clock())),
        "base": report["base"],
        "out": report["out"],
        "items_changed": report["items"]["changed"],
        "items_added": report["items"]["added_count"],
        "mobs_changed": report["mobs"]["changed"],
        "mobs_added": report["mobs"]["added_count"],
    }
    built = time.strftime("%Y-%m-%d %H:%M", time.localtime(manifest["built_at"]))
    fill = {"client_version": manifest["client_version"] or "?", "world": world_label or "-", "built": built}
    buf = io.BytesIO()
    stamp = time.localtime(manifest["built_at"])[:6]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def put(name, data):
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
        put("world-data/gamedata.index", out_index)
        put("world-data/gamedata.data", out_data)
        put("world-data/world-data.json", json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"))
        put("DaneSwiata.ps1", installer_script())
        put("DaneSwiata.bat", INSTALLER_BAT)
        put("Dane swiata - instrukcja.txt", README_PL.format(**fill).replace("\n", "\r\n").encode("cp1250"))
        put("World data - instructions.txt", README_EN.format(**fill).replace("\n", "\r\n").encode("cp1250"))
    return buf.getvalue(), manifest


# =============================================================================
#  Command line (the launcher runs it in the panel container)
# =============================================================================
def load_world_json(path):
    """A world written as JSON - {"items": {vnum: row}, "mobs": {vnum: row}},
    text columns as hex - for a build without a database (the tests)."""
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    out = []
    for key in ("items", "mobs"):
        rows = {}
        for vnum, row in doc[key].items():
            rec = dict(row)
            for col in _TEXT:
                if col in rec:
                    rec[col] = bytes.fromhex(rec[col])
            rows[int(vnum)] = rec
        out.append(rows)
    return out[0], out[1]


def dump_world_json(items, mobs):
    def plain(rows):
        doc = {}
        for vnum, row in rows.items():
            rec = {}
            for col, value in row.items():
                rec[col] = value.hex() if isinstance(value, (bytes, bytearray)) else value
            doc[str(vnum)] = rec
        return doc
    return json.dumps({"items": plain(items), "mobs": plain(mobs)}, sort_keys=True)


def _env_connection():
    import pymysql  # the panel's own dependency
    return pymysql.connect(host=os.environ.get("M2_DB_HOST", "mariadb"),
                           port=int(os.environ.get("M2_DB_PORT", "3306") or 3306),
                           user=os.environ.get("M2_DB_USER", "metin2"),
                           password=os.environ.get("M2_DB_PASSWORD", ""),
                           charset="utf8mb4", init_command="SET character_set_results = binary",
                           cursorclass=pymysql.cursors.DictCursor)


def main(argv=None):
    parser = argparse.ArgumentParser(description="The client's gamedata pack with this world's item and monster tables.")
    sub = parser.add_subparsers(dest="cmd")
    b = sub.add_parser("build")
    b.add_argument("--base", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--report")
    b.add_argument("--world-json", help="the world from a JSON file instead of the database")
    c = sub.add_parser("check")
    c.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "check":
            with open(os.path.join(args.base, PACK_FILES[0]), "rb") as f:
                index_bytes = f.read()
            with open(os.path.join(args.base, PACK_FILES[1]), "rb") as f:
                data_bytes = f.read()
            version, entries = read_pack(index_bytes, data_bytes)
            keys = dict((e.key(), e) for e in entries)
            items = decode_rows(read_item_proto(entry_data(keys[ITEM_PROTO])), ITEM_STRUCT, ITEM_NAMES)
            mobs = decode_rows(read_mob_proto(entry_data(keys[MOB_PROTO])), MOB_STRUCT, MOB_NAMES)
            print(json.dumps({"ok": True, "files": len(entries), "items": len(items), "mobs": len(mobs),
                              "sha256": pack_sha(index_bytes, data_bytes)}))
            return 0
        if args.cmd != "build":
            parser.print_help()
            return 2
        if args.world_json:
            items, mobs = load_world_json(args.world_json)
        else:
            conn = _env_connection()
            try:
                items, mobs = fetch_world(conn)
            finally:
                conn.close()
        out_index, out_data, report = build_files(args.base, items, mobs, args.out)
        report["ok"] = True
        text = json.dumps(report, indent=2, sort_keys=True)
        if args.report:
            with open(args.report, "w", encoding="utf-8") as f:
                f.write(text)
        print(json.dumps({"ok": True, "changed": report["changed"], "out": report["out"],
                          "items_changed": report["items"]["changed"], "mobs_changed": report["mobs"]["changed"],
                          "items_added": report["items"]["added_count"], "mobs_added": report["mobs"]["added_count"],
                          "world": report["world"]}))
        return 0
    except ProtoError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 3


if __name__ == "__main__":
    sys.exit(main())
