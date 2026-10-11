# =============================================================================
#  /market -- the item icons (Iwakura's Patch 13, point 6, 9 October:
#  "ikony przedmiotow wyswietlaja sie zle, nawet dla tych samych przedmiotow").
#
#  Why the same item showed a right, a wrong or no icon: the page asked
#  item_icons.json alone, per card, for the vnum and then for vnum - vnum % 10.
#  That json is port/iconify.py's list of the vnums whose picture is NOT their
#  own number (a plus's +0, item_list.txt's other names) - a vnum whose
#  picture is its own 5-digit file is not in it at all. So every +0 piece (and
#  most items) found nothing and drew a letter, its +4 found the +0's picture,
#  and a non-gear vnum not ending in 0 borrowed whatever its round ten mapped
#  to: another item's picture, or nothing. A file missing on disk was the
#  browser's broken image, and /static's answers ask the browser to revalidate,
#  so scrolling back fetched them again.
#
#  Now one map vnum -> file is made with every snapshot, never per card: a
#  piece of gear by its family's +0 (the pluses share the picture), anything
#  else by its own vnum; each candidate by item_icons.json, then its own
#  5-digit file, then a TGA or DDS of that number - in files/static/icons or a
#  directory M2PANEL_ICON_SOURCE names (an extracted client icon/item) -
#  turned into a PNG here, once, into a cache on disk beside the panel's files
#  (the browser never sees a game format). The URL carries the set's version
#  in the file name and is answered as immutable for a year; a vnum with no
#  picture gets "" and the page draws the grey "?" frame - never an empty
#  square, nor a broken image (the page swaps one that fails to load too).
#
#  Pure Python: no Flask here, and no Pillow (the panel's image has neither
#  PIL nor anything to decode a TGA or a DDS with), so the two decoders and
#  the PNG writer are below. tests/market_preview_test.py tests all of it.
# =============================================================================

import hashlib
import json
import os
import re
import struct
import threading
import zlib

ITEM_WEAPON, ITEM_ARMOR = 1, 2
CACHE_DIR = "market_icons"            # beside downloads.db (M2PANEL_DIR)
URL_PREFIX = "/market/icons/"
CONVERTED_PREFIX = "c-"               # a converted picture never shadows a client PNG
SOURCE_EXTENSIONS = (".tga", ".dds")
MAX_SOURCE_BYTES = 4 * 1024 * 1024    # an icon is 32x32..64x96; anything bigger is no icon
MAX_SIDE = 1024
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
URL_RE = re.compile(r"^(" + re.escape(CONVERTED_PREFIX) + r")?([A-Za-z0-9_-]{1,64})\.([0-9a-f]{8})\.png$")


# -----------------------------------------------------------------------------
#  PNG out
# -----------------------------------------------------------------------------
def png_bytes(width, height, rgba):
    """An RGBA image (bytes, rows top to bottom) as a PNG file."""
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("bad image")

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def png_size(data):
    """(width, height) of a PNG file, or None for anything that is not one."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


# -----------------------------------------------------------------------------
#  TGA in: the client's icon/item/*.tga (truecolor 24 or 32 bits, raw or RLE)
# -----------------------------------------------------------------------------
def tga_to_rgba(data):
    """(width, height, rgba) of a truecolor TGA; ValueError for anything else."""
    if len(data) < 18:
        raise ValueError("short tga")
    id_len, cmap_type, img_type = data[0], data[1], data[2]
    width, height = struct.unpack("<HH", data[12:16])
    bpp, desc = data[16], data[17]
    if cmap_type != 0 or img_type not in (2, 10) or bpp not in (24, 32):
        raise ValueError("unsupported tga")
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
        raise ValueError("bad tga size")
    px = bpp // 8
    pos = 18 + id_len
    total = width * height
    out = bytearray(total * 4)

    def put(i, b, g, r, a):
        out[i * 4:i * 4 + 4] = bytes((r, g, b, a))
    if img_type == 2:
        need = pos + total * px
        if len(data) < need:
            raise ValueError("short tga")
        for i in range(total):
            o = pos + i * px
            put(i, data[o], data[o + 1], data[o + 2], data[o + 3] if px == 4 else 255)
    else:
        i = 0
        while i < total:
            if pos >= len(data):
                raise ValueError("short tga")
            head = data[pos]
            pos += 1
            run = (head & 0x7F) + 1
            if i + run > total:
                raise ValueError("bad tga run")
            if head & 0x80:
                if pos + px > len(data):
                    raise ValueError("short tga")
                b, g, r = data[pos], data[pos + 1], data[pos + 2]
                a = data[pos + 3] if px == 4 else 255
                pos += px
                for _ in range(run):
                    put(i, b, g, r, a)
                    i += 1
            else:
                if pos + run * px > len(data):
                    raise ValueError("short tga")
                for _ in range(run):
                    put(i, data[pos], data[pos + 1], data[pos + 2], data[pos + 3] if px == 4 else 255)
                    pos += px
                    i += 1
    # Bit 5 of the descriptor: rows top to bottom; without it the file is
    # stored bottom to top, as the client's icons mostly are.
    if not desc & 0x20:
        stride = width * 4
        out = bytearray(b"".join(bytes(out[y * stride:(y + 1) * stride]) for y in range(height - 1, -1, -1)))
    if desc & 0x10:                                   # right to left: rare, but cheap to honour
        stride = width * 4
        rows = []
        for y in range(height):
            row = out[y * stride:(y + 1) * stride]
            rows.append(b"".join(bytes(row[x * 4:x * 4 + 4]) for x in range(width - 1, -1, -1)))
        out = bytearray(b"".join(rows))
    return width, height, bytes(out)


# -----------------------------------------------------------------------------
#  DDS in: DXT1, DXT3, DXT5 and plain 32-bit BGRA
# -----------------------------------------------------------------------------
def _rgb565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31


def _color_block(block, dxt1):
    c0, c1, bits = struct.unpack("<HHI", block)
    p0, p1 = _rgb565(c0), _rgb565(c1)
    if c0 > c1 or not dxt1:
        p2 = tuple((2 * a + b) // 3 for a, b in zip(p0, p1))
        p3 = tuple((a + 2 * b) // 3 for a, b in zip(p0, p1))
        palette = (p0 + (255,), p1 + (255,), p2 + (255,), p3 + (255,))
    else:
        p2 = tuple((a + b) // 2 for a, b in zip(p0, p1))
        palette = (p0 + (255,), p1 + (255,), p2 + (255,), (0, 0, 0, 0))
    return [palette[(bits >> (2 * k)) & 3] for k in range(16)]


def _alpha_dxt5(block):
    a0, a1 = block[0], block[1]
    bits = int.from_bytes(block[2:8], "little")
    if a0 > a1:
        table = [a0, a1] + [((6 - k) * a0 + (k + 1) * a1) // 7 for k in range(6)]
    else:
        table = [a0, a1] + [((4 - k) * a0 + (k + 1) * a1) // 5 for k in range(4)] + [0, 255]
    return [table[(bits >> (3 * k)) & 7] for k in range(16)]


def _alpha_dxt3(block):
    bits = int.from_bytes(block, "little")
    return [((bits >> (4 * k)) & 15) * 17 for k in range(16)]


def dds_to_rgba(data):
    """(width, height, rgba) of the first level of a DDS; ValueError otherwise."""
    if len(data) < 128 or data[:4] != b"DDS ":
        raise ValueError("no dds")
    height, width = struct.unpack("<II", data[12:20])
    if not (0 < width <= MAX_SIDE and 0 < height <= MAX_SIDE):
        raise ValueError("bad dds size")
    pf_flags, fourcc, rgb_bits = struct.unpack("<I4sI", data[80:92])
    masks = struct.unpack("<IIII", data[92:108])
    pos = 128
    out = bytearray(width * height * 4)
    if pf_flags & 0x4:                                 # DDPF_FOURCC
        kind = fourcc
        if kind not in (b"DXT1", b"DXT3", b"DXT5"):
            raise ValueError("unsupported dds")
        size = 8 if kind == b"DXT1" else 16
        bw, bh = (width + 3) // 4, (height + 3) // 4
        if len(data) < pos + bw * bh * size:
            raise ValueError("short dds")
        for by in range(bh):
            for bx in range(bw):
                block = data[pos:pos + size]
                pos += size
                if kind == b"DXT1":
                    texels = _color_block(block, True)
                else:
                    alpha = _alpha_dxt5(block[:8]) if kind == b"DXT5" else _alpha_dxt3(block[:8])
                    texels = [c[:3] + (alpha[k],) for k, c in enumerate(_color_block(block[8:], False))]
                for k, texel in enumerate(texels):
                    x, y = bx * 4 + k % 4, by * 4 + k // 4
                    if x < width and y < height:
                        o = (y * width + x) * 4
                        out[o:o + 4] = bytes(texel)
        return width, height, bytes(out)
    if pf_flags & 0x40 and rgb_bits == 32:             # DDPF_RGB, 32 bits a pixel
        if len(data) < pos + width * height * 4:
            raise ValueError("short dds")

        def channel(value, mask):
            if not mask:
                return None
            shift = (mask & -mask).bit_length() - 1
            top = mask >> shift
            return ((value & mask) >> shift) * 255 // top
        rmask, gmask, bmask, amask = masks
        has_alpha = bool(pf_flags & 0x1)
        for i in range(width * height):
            value = struct.unpack("<I", data[pos + i * 4:pos + i * 4 + 4])[0]
            a = channel(value, amask) if has_alpha else None
            out[i * 4:i * 4 + 4] = bytes((channel(value, rmask) or 0, channel(value, gmask) or 0,
                                          channel(value, bmask) or 0, 255 if a is None else a))
        return width, height, bytes(out)
    raise ValueError("unsupported dds")


def convert_to_png(path):
    """A TGA or DDS file's PNG bytes; ValueError for anything it cannot read."""
    if os.path.getsize(path) > MAX_SOURCE_BYTES:
        raise ValueError("too big for an icon")
    with open(path, "rb") as fh:
        data = fh.read()
    width, height, rgba = (dds_to_rgba(data) if path.lower().endswith(".dds") else tga_to_rgba(data))
    return png_bytes(width, height, rgba)


# -----------------------------------------------------------------------------
#  The set: one map vnum -> URL a snapshot
# -----------------------------------------------------------------------------
def family_base(vnum, proto):
    """The vnum whose picture a piece shows: a weapon's or armour's family's
    +0 (the pluses share it), anything else its own."""
    vnum = int(vnum)
    if proto is not None and int(getattr(proto, "type", 0)) in (ITEM_WEAPON, ITEM_ARMOR):
        return vnum - vnum % 10
    return vnum


class IconSet(object):
    """The panel's icons: files/static/icons with item_icons.json, a cache of
    converted pictures, and the directories a TGA or DDS may come from."""

    def __init__(self, static_dir, cache_dir, source_dirs=()):
        self.static_dir = static_dir
        self.icons_dir = os.path.join(static_dir, "icons") if static_dir else ""
        self.cache_dir = cache_dir
        self.source_dirs = tuple(d for d in source_dirs if d)
        self.lock = threading.Lock()
        self.mapping, self.files, self.cached, self.sources = {}, set(), set(), {}
        self.version = "00000000"
        self.failed = set()
        self.converted = 0

    def reload(self):
        """Read the set again: cheap (one json and two listings), done with
        every snapshot so an update's new icons are seen without a restart."""
        mapping, files, cached, sources = {}, set(), set(), {}
        try:
            with open(os.path.join(self.static_dir, "item_icons.json"), encoding="utf-8") as fh:
                raw = json.load(fh)
            mapping = {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}
        except Exception:                            # noqa: BLE001 - no json: own numbers only
            mapping = {}
        for folder, keep in ((self.icons_dir, files), (self.cache_dir, cached)):
            try:
                keep.update(n for n in os.listdir(folder) if n.lower().endswith(".png"))
            except OSError:
                pass
        for folder in (self.icons_dir,) + self.source_dirs:
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for n in names:
                stem, ext = os.path.splitext(n)
                if ext.lower() in SOURCE_EXTENSIONS and NAME_RE.match(stem) and stem not in sources:
                    sources[stem] = os.path.join(folder, n)
        digest = hashlib.sha1()
        digest.update(json.dumps(mapping, sort_keys=True).encode("utf-8"))
        digest.update("\n".join(sorted(files)).encode("utf-8"))
        digest.update("\n".join(sorted(sources)).encode("utf-8"))
        with self.lock:
            self.mapping, self.files, self.cached, self.sources = mapping, files, cached, sources
            self.version = digest.hexdigest()[:8]
        return self

    def _converted(self, stem):
        """The cache's PNG of a TGA or DDS of this stem, made now if need be;
        None when there is no such source or it cannot be read."""
        name = CONVERTED_PREFIX + stem + ".png"
        if name in self.cached:
            return name
        source = self.sources.get(stem)
        if not source or stem in self.failed or not self.cache_dir:
            return None
        try:
            data = convert_to_png(source)
            os.makedirs(self.cache_dir, exist_ok=True)
            tmp = os.path.join(self.cache_dir, name + ".tmp")
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, os.path.join(self.cache_dir, name))
        except (OSError, ValueError, struct.error):
            self.failed.add(stem)
            return None
        self.cached.add(name)
        self.converted += 1
        return name

    def file_for(self, vnum, proto=None):
        """The picture's file name (a static PNG, or "c-" and a converted one)
        of a vnum, or None. A piece of gear asks its family's +0 first and
        then the family's pluses in order, so every plus of one family gets
        the one answer whichever plus is asked."""
        vnum = int(vnum)
        base = family_base(vnum, proto)
        gear = proto is not None and int(getattr(proto, "type", 0)) in (ITEM_WEAPON, ITEM_ARMOR)
        for key in (range(base, base + 10) if gear else (vnum,)):
            mapped = self.mapping.get(str(key))
            if mapped and mapped in self.files and NAME_RE.match(mapped[:-4] if mapped.endswith(".png") else ""):
                return mapped
            own = "%05d.png" % key
            if own in self.files:
                return own
            for stem in (os.path.splitext(mapped)[0] if mapped else None, "%05d" % key):
                if stem and NAME_RE.match(stem):
                    converted = self._converted(stem)
                    if converted:
                        return converted
        return None

    def url_of(self, name):
        stem = name[:-4]
        return URL_PREFIX + stem + "." + self.version + ".png"

    def build_map(self, protos, vnums):
        """{vnum: URL, or "" for none} of the given vnums: one lookup a kind,
        the same URL for every plus of a family."""
        out, by_family = {}, {}
        for vnum in vnums:
            proto = protos.get(vnum)
            key = family_base(vnum, proto)
            if key not in by_family:
                name = self.file_for(vnum, proto)
                by_family[key] = self.url_of(name) if name else ""
            out[int(vnum)] = by_family[key]
        return out

    def path_of(self, url_name):
        """(path, current) of a /market/icons/<name> request, or (None, False):
        the version in the name must be of a known form, the file one of the
        set's or the cache's, and `current` says whether it is this set's."""
        m = URL_RE.match(url_name or "")
        if not m:
            return None, False
        converted, stem, version = m.group(1), m.group(2), m.group(3)
        if converted:
            name = CONVERTED_PREFIX + stem + ".png"
            folder, known = self.cache_dir, self.cached
        else:
            name = stem + ".png"
            folder, known = self.icons_dir, self.files
        if name not in known or not folder:
            return None, False
        return os.path.join(folder, name), version == self.version
