# =============================================================================
#  /editsql -- the editor's two languages (the operator, 7 October).
#
#  Lostek wrote the editor in Polish, and a reader of Polish gets it exactly as
#  he wrote it, byte for byte. Every other reader gets English: German and
#  Turkish are not translated yet, and half a translation reads worse than
#  either language (docs/notes/panels.md).
#
#  The language is the panel's own (admin_panel.lang(): the header's switch,
#  the m2lang cookie, Polish by default), asked for every request - never once
#  at import, because the module tables below are built when the panel starts
#  and are read by readers of both languages. So a text the editor keeps in a
#  table is a pair, P(pl, en), resolved when it is shown; a text written where
#  it is used is T(pl, en).
#
#  What is not the editor's words stays as the database holds it: a recipe's
#  comment, the labels an operator gave, the rows of the history. The editor
#  edits exactly what is there.
#
#  Item and monster names are the one exception, and only where they are
#  shown or searched (Blind and Tieru, 8 October): a reader of English reads
#  the official English name of an item or a monster - the core's own names
#  file, through the panel's english_game_name - wherever the world still
#  calls the vnum what that file matched. The column (locale_name) is still
#  the Polish name: the form shows it and an edit writes it.
# =============================================================================

from . import db

# The languages the editor is written in. A panel language outside them reads
# English.
LANGUAGES = ("pl", "en")
NOT_READY = ("de", "tr")


def lang():
    """'pl' or 'en' for the request being served; Polish outside a request."""
    try:
        code = db.ns().lang()
    except Exception:                              # noqa: BLE001 - no request, no panel
        return "pl"
    return "pl" if code == "pl" else "en"


def T(pl, en):
    """The text in the reader's language."""
    return pl if lang() == "pl" else en


class P(object):
    """A text of the editor's in both languages, resolved when it is shown.

    str() (and so "%s" and render._esc) gives the reader's language. It is not
    a str subclass on purpose: a join or a concatenation that forgot to
    resolve it fails loudly instead of quietly printing Polish to an English
    reader.
    """
    __slots__ = ("pl", "en")

    def __init__(self, pl, en):
        self.pl = pl
        self.en = en

    def __str__(self):
        return self.pl if lang() == "pl" else self.en

    def __repr__(self):
        return "P(%r, %r)" % (self.pl, self.en)

    def __eq__(self, other):
        return isinstance(other, P) and (self.pl, self.en) == (other.pl, other.en)

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.pl, self.en))


def tr(value):
    """A P in the reader's language; anything else as it is."""
    return str(value) if isinstance(value, P) else value


def bilingual(text, en):
    """A message the editor has always said in both languages, "pl / en".

    A Polish reader keeps it whole, as it always read; an English reader gets
    the English half alone.
    """
    return text if lang() == "pl" else en


def plural(n, pl_forms, en_forms):
    """The word for n things: pl_forms = (one, few, many), en_forms = (one, many)."""
    if lang() != "pl":
        return en_forms[0] if abs(int(n)) == 1 else en_forms[1]
    n = abs(int(n))
    if n == 1:
        return pl_forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return pl_forms[1]
    return pl_forms[2]


_KINDS = {"item": "i", "mob": "m"}


def english_name(kind, vnum, polish, codec="cp1250"):
    """The official English name of an item or a monster ("item"/"mob") the
    world calls `polish`, or None: no line, a line matched to another name
    (the item was renamed), no names file, or a panel that has none of this.
    `polish` is the name as the editor decoded it; it is held against the
    line's hash as the engine holds it, in CP1250, whatever the column's own
    charset (bytes are taken as CP1250 already)."""
    if polish in (None, "", b""):
        return None
    try:
        lookup = db.ns().get("english_game_name")
    except Exception:                              # noqa: BLE001 - no panel
        return None
    if lookup is None:
        return None
    try:
        return lookup(_KINDS.get(kind, kind), vnum, polish, codec or "cp1250")
    except Exception:                              # noqa: BLE001 - a name is a nicety
        return None


def game_name(kind, vnum, polish, codec="cp1250"):
    """An item's or a monster's name as this reader reads it: the official
    English one for a reader of English where there is one, else the name
    the world holds. Display only - never what is written."""
    if lang() == "pl":
        return polish
    return english_name(kind, vnum, polish, codec) or polish


def english_candidates(kind, text):
    """{vnum: hash} of the official English names holding `text`, for a
    search; each still has to be held against the world's own name."""
    try:
        lookup = db.ns().get("english_game_candidates")
        return (lookup(_KINDS.get(kind, kind), text) if lookup else {}) or {}
    except Exception:                              # noqa: BLE001
        return {}


def english_hash_ok(digest, polish, codec="cp1250"):
    try:
        check = db.ns().get("english_game_hash_ok")
        return bool(check and check(digest, polish, codec or "cp1250"))
    except Exception:                              # noqa: BLE001
        return False


def js(text):
    """A text for a single-quoted JavaScript string in an inline script."""
    return (str(text).replace("\\", "\\\\").replace("'", "\\'")
            .replace("</", "<\\/").replace("\n", "\\n"))
