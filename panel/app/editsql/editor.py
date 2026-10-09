# =============================================================================
#  /editsql -- silnik edytora.
#
#  Jeden generyczny edytor obsluguje wszystkie moduly "tabelkowe". Deskryptor
#  mowi TYLKO:
#
#      * ktorej tabeli dotyczy (i z ktorej bazy),
#      * ktore kolumny pokazac na liscie i jak je sformatowac,
#      * po czym szukac, filtrowac i sortowac,
#      * jak pogrupowac pola w sekcje formularza.
#
#  Nie mowi, jak czytac schemat - to wie schema.py - ani jak zapisywac - to wie
#  safety.py. Kolumna, ktorej w tej bazie nie ma, po prostu nie pojawia sie ani
#  na liscie, ani w formularzu (deskryptor jest filtrowany przez metamodel).
#  Znaczenie kolumn (etykiety, czy vnum to przedmiot czy potwor) jest w fields.py.
#
#  Listy chodza z LIMIT i wyszukiwaniem po stronie SQL.
# =============================================================================

import urllib.parse

from . import db, fields, i18n, labels, render, safety, schema
from .i18n import P, T, tr

PER_PAGE = 50
PER_PAGE_MAX = 500
INT_TYPES = ("tinyint", "smallint", "mediumint", "int", "bigint")


# -----------------------------------------------------------------------------
#  Deskryptory modulow
# -----------------------------------------------------------------------------
#  list: (kolumna albo krotka kolumn, naglowek, rodzaj)
#        rodzaj: key, key_item, name, text, int, num, money, item, mob, itemtype,
#                itemsubtype, rank, mobtype, empire, bonus, range, materials,
#                levels, slot, enum, pct, code
#  search: kolumny przeszukiwane (LIKE dla tekstu, = dla liczby)
#  order: domyslne sortowanie
#  filters: (kolumna, naglowek, rodzaj) - listy wyboru z DISTINCT w bazie
#  sections: (tytul, podpowiedz, [kolumny]) - formularz edycji
# -----------------------------------------------------------------------------
_RANGE_DMG = (("damage_min", "damage_max"), P("Obrażenia", "Damage"), "range")
_RANGE_GOLD = (("gold_min", "gold_max"), "Yang", "range")

MODULES = {
    "items": {
        "db": "world", "table": "item_proto", "title": P("Przedmioty", "Items"),
        "pk": ("vnum",), "order": ("vnum", "asc"),
        "search": ("vnum", "locale_name", "name"),
        "search_hint": P("VNUM albo fragment nazwy, np. Miecz", "VNUM or part of a name, e.g. Sword"),
        "list": (("vnum", "VNUM", "key_item"), ("locale_name", P("Nazwa", "Name"), "name"),
                 ("type", P("Typ", "Type"), "itemtype"),
                 ("subtype", P("Podtyp", "Subtype"), "itemsubtype"),
                 ("limitvalue0", P("Wym. poz.", "Req. lv."), "int"),
                 ("gold", P("Cena", "Price"), "money"),
                 ("shop_buy_price", P("Skup", "Sells for"), "money"),
                 ("stack", P("Stos", "Stack"), "int"),
                 ("refine_set", P("Przepis", "Recipe"), "refine"),
                 ("refined_vnum", P("Po ulepszeniu", "Refines into"), "item")),
        "filters": (("type", P("Typ", "Type"), "itemtype"),
                    ("subtype", P("Podtyp", "Subtype"), "itemsubtype")),
        "sections": (
            (P("Podstawowe", "Basics"),
             P("Nazwa w grze to locale_name. Nazwa wewnętrzna to koreańska "
               "nazwa z plików klienta - tylko do odczytu.",
               "The name in the game is locale_name. The internal name is the Korean "
               "name from the client's files - read only."),
             ("vnum", "locale_name", "name", "type", "subtype", "stack", "size", "weight",
              "specular")),
            (P("Handel", "Trade"),
             P("Cena kupna to cena w sklepie NPC, skup - ile NPC płaci graczowi. "
               "Serwer od razu liczy nową cenę, ale okno gry (opis przedmiotu, "
               "pytanie przy sprzedaży) pokazuje cenę z plików klienta, czyli starą.",
               "The buying price is the price in an NPC shop, the selling price what the "
               "NPC pays a player. The server uses a new price at once, but the game's "
               "window (the item's tooltip, the question when selling) shows the price "
               "from the client's files, the old one."),
             ("gold", "shop_buy_price")),
            (P("Wymagania", "Requirements"),
             P("Najczęściej wymaganie 1 to poziom postaci.",
               "Requirement 1 is usually the character's level."),
             ("limittype0", "limitvalue0", "limittype1", "limitvalue1")),
            (P("Bonusy wpisane w przedmiot", "Bonuses built into the item"),
             P("Stałe bonusy przedmiotu. Nazwy pochodzą z world.locale_point.",
               "The item's fixed bonuses. The names come from world.locale_point."),
             ("applytype0", "applyvalue0", "applytype1", "applyvalue1",
              "applytype2", "applyvalue2")),
            (P("Wartości silnika", "Engine values"),
             P("value0–value5 silnik czyta zależnie od typu (np. obrona "
               "zbroi, obrażenia broni, czas działania mikstury).",
               "The engine reads value0–value5 by the item's type (e.g. an armour's "
               "defence, a weapon's damage, how long a potion lasts)."),
             ("value0", "value1", "value2", "value3", "value4", "value5")),
            (P("Ulepszanie i gniazda", "Refining and sockets"),
             P("Przepis wskazuje world.refine_proto, a przedmiot po "
               "ulepszeniu - kolejny stopień (to nie zawsze vnum+1).",
               "The recipe points at world.refine_proto, and the item after refining "
               "is the next grade (not always vnum+1)."),
             ("refine_set", "refined_vnum", "magic_pct", "socket_pct", "addon_type",
              "socket0", "socket1", "socket2", "socket3", "socket4", "socket5")),
            (P("Flagi", "Flags"),
             P("Maski bitowe - pod polem jest ich rozpisanie.",
               "Bit masks - the bits set are spelled out under the field."),
             ("flag", "antiflag", "wearflag", "immuneflag")),
        ),
        "related": ("refine_from_item", "item_usage", "shop_usage", "etc_drop"),
    },
    "mobs": {
        "db": "world", "table": "mob_proto", "title": P("Potwory i bossowie", "Monsters and bosses"),
        "pk": ("vnum",), "order": ("vnum", "asc"),
        "search": ("vnum", "locale_name", "name"),
        "search_hint": P("VNUM albo fragment nazwy, np. Wilk", "VNUM or part of a name, e.g. Wolf"),
        "list": (("vnum", "VNUM", "key"), ("locale_name", P("Nazwa", "Name"), "name"),
                 ("level", P("Poz.", "Lv."), "int"), ("rank", P("Ranga", "Rank"), "rank"),
                 ("type", P("Typ", "Type"), "mobtype"),
                 ("max_hp", P("PŻ", "HP"), "num"), _RANGE_DMG,
                 ("def", P("Obrona", "Defence"), "num"),
                 ("exp", "EXP", "num"), _RANGE_GOLD,
                 ("drop_item", P("Drop specjalny", "Special drop"), "item")),
        "filters": (("rank", P("Ranga", "Rank"), "rank"), ("type", P("Typ", "Type"), "mobtype"),
                    ("empire", P("Królestwo", "Kingdom"), "empire")),
        "sections": (
            (P("Podstawowe", "Basics"), "", ("vnum", "locale_name", "name", "type", "rank", "level",
                                             "battle_type", "size", "empire", "fraction", "folder")),
            (P("Siła potwora", "Strength"),
             P("PŻ to punkty życia; im wyższa obrona, tym mniej obrażeń dochodzi do celu.",
               "HP is hit points; the higher the defence, the less damage gets through."),
             ("max_hp", "damage_min", "damage_max", "def", "dam_multiply",
              "regen_cycle", "regen_percent")),
            (P("Atrybuty", "Attributes"),
             P("ST/HT/DX/IQ wpływają na trafienia, uniki i obrażenia.",
               "ST/HT/DX/IQ affect hits, dodges and damage."),
             ("st", "dx", "ht", "iq", "summon", "drain_sp")),
            (P("Nagroda za zabicie", "Reward for the kill"),
             P("Wartości przed mnożnikami serwera (strona Mnożniki).",
               "Values before the server's multipliers (the Rates page)."),
             ("exp", "gold_min", "gold_max", "drop_item", "resurrection_vnum",
              "polymorph_item")),
            (P("Zachowanie", "Behaviour"),
             P("Zasięg wzroku agresji działa tylko z flagą AGGR. "
               "Szybkość 100 = jak w oryginalnej grze.",
               "The aggression sight range works only with the AGGR flag. "
               "Speed 100 = as in the original game."),
             ("ai_flag", "setRaceFlag", "setImmuneFlag", "aggressive_hp_pct",
              "aggressive_sight", "attack_range", "attack_speed", "move_speed",
              "on_click", "mount_capacity", "mob_color")),
            (P("Odporności", "Resistances"),
             P("W procentach: 20 to 20% mniej obrażeń danego rodzaju; "
               "wartość ujemna oznacza większe obrażenia.",
               "In percent: 20 is 20% less damage of that kind; "
               "a negative value means more damage."),
             ("resist_sword", "resist_twohand", "resist_dagger", "resist_bell",
              "resist_fan", "resist_bow", "resist_fire", "resist_elect",
              "resist_magic", "resist_wind", "resist_poison")),
            (P("Efekty nakładane na gracza", "Effects on the player"),
             P("Szansa (%) na efekt przy trafieniu.", "Chance (%) of the effect on a hit."),
             ("enchant_curse", "enchant_slow", "enchant_poison", "enchant_stun",
              "enchant_critical", "enchant_penetrate", "enchant_fire", "enchant_root")),
            (P("Umiejętności specjalne", "Special skills"),
             P("Szansa (%) na użycie umiejętności specjalnej.",
               "Chance (%) of using the special skill."),
             ("sp_berserk", "sp_stoneskin", "sp_godspeed", "sp_deathblow", "sp_revive")),
            (P("Umiejętności potwora", "Monster skills"),
             P("Do pięciu umiejętności z poziomami.", "Up to five skills with their levels."),
             ("skill_vnum0", "skill_level0", "skill_vnum1", "skill_level1",
              "skill_vnum2", "skill_level2", "skill_vnum3", "skill_level3",
              "skill_vnum4", "skill_level4")),
        ),
        "related": ("mob_drop", "shop_of_npc"),
    },
    "drops": {
        # Drop specjalny to KOLUMNA mob_proto (vnum przedmiotu), wiec modul jest
        # lista potworow, ktore go maja - edycja idzie po kluczu glownym moba.
        "db": "world", "table": "mob_proto", "title": P("Drop specjalny", "Special drop"),
        "pk": ("vnum",), "order": ("vnum", "asc"),
        "filter_sql": "`drop_item` <> 0",
        "search": ("vnum", "locale_name", "drop_item"),
        "search_hint": P("VNUM potwora, nazwa albo VNUM przedmiotu",
                         "Monster VNUM, name or item VNUM"),
        "list": (("vnum", "VNUM", "key"), ("locale_name", P("Potwór", "Monster"), "name"),
                 ("level", P("Poz.", "Lv."), "int"), ("rank", P("Ranga", "Rank"), "rank"),
                 ("type", P("Typ", "Type"), "mobtype"),
                 ("drop_item", P("Drop specjalny", "Special drop"), "item")),
        "filters": (("rank", P("Ranga", "Rank"), "rank"), ("type", P("Typ", "Type"), "mobtype")),
        "sections": (
            (P("Drop specjalny tego potwora", "This monster's special drop"),
             P("To pojedynczy przedmiot przypisany do potwora. Pełne grupy dropu "
               "(mob_drop_item.txt) i skrzynki (special_item_group.txt) są w plikach "
               "serwera - zmienisz je w edytorze „Skrzynki i drop” panelu.",
               "A single item given to the monster. The full drop groups "
               "(mob_drop_item.txt) and the chests (special_item_group.txt) are in the "
               "server's files - change them in the panel's \"Chests and drops\" editor."),
             ("vnum", "locale_name", "level", "drop_item")),
        ),
        "related": ("mob_drop",),
    },
    "refine": {
        "db": "world", "table": "refine_proto", "title": P("Ulepszenia", "Refining"),
        "pk": ("id",), "order": ("id", "asc"),
        "search": ("id", "vnum0", "vnum1", "vnum2", "vnum3", "vnum4"),
        "search_hint": P("Numer przepisu albo VNUM materiału", "Recipe number or material VNUM"),
        "list": (("id", P("Przepis", "Recipe"), "key"), ("cost", P("Koszt", "Cost"), "money"),
                 ("prob", P("Szansa", "Chance"), "pct"),
                 (("vnum0", "count0", "vnum1", "count1", "vnum2", "count2", "vnum3", "count3",
                   "vnum4", "count4"), P("Materiały", "Materials"), "materials"),
                 ("id", P("Używany przez", "Used by"), "refineusers")),
        "sections": (
            (P("Przepis", "Recipe"),
             P("Wynik i źródło czyta się z item_proto (refine_set → ten przepis, "
               "refined_vnum → wynik); kolumny src_vnum/result_vnum są w tej bazie puste.",
               "The result and the source are read from item_proto (refine_set → this "
               "recipe, refined_vnum → the result); src_vnum/result_vnum are empty in "
               "this database."),
             ("id", "cost", "prob")),
            (P("Materiały", "Materials"),
             P("Pięć par przedmiot/ilość; 0 oznacza brak materiału.",
               "Five item/count pairs; 0 means no material."),
             ("vnum0", "count0", "vnum1", "count1", "vnum2", "count2",
              "vnum3", "count3", "vnum4", "count4")),
        ),
        # Gdzie przepis jest uzywany stoi NAD formularzem: zmiana kosztu, szansy
        # albo materialow dotyczy wszystkich tych przedmiotow naraz.
        "related_top": ("refine_items",),
        "related": (),
    },
    "bonuses": {
        "db": "world", "table": "item_attr", "title": P("Bonusy", "Bonuses"),
        "pk": (), "order": ("apply", "asc"),
        "search": ("apply",),
        "search_hint": P("np. MAX_HP albo CRITICAL", "e.g. MAX_HP or CRITICAL"),
        "list": (("apply", "Bonus", "bonus"), ("prob", P("Waga", "Weight"), "int"),
                 (("lv1", "lv2", "lv3", "lv4", "lv5"),
                  P("Wartości (stopnie 1–5)", "Values (grades 1–5)"), "levels"),
                 ("weapon", P("Broń", "Weapon"), "slot"), ("body", P("Zbroja", "Armour"), "slot"),
                 ("head", P("Hełm", "Helmet"), "slot"), ("shield", P("Tarcza", "Shield"), "slot"),
                 ("wrist", P("Bransol.", "Bracelet"), "slot"), ("foots", P("Buty", "Shoes"), "slot"),
                 ("neck", P("Naszyj.", "Necklace"), "slot"), ("ear", P("Kolcz.", "Earrings"), "slot")),
        "sections": (
            ("Bonus", P("Polska nazwa pochodzi z world.locale_point.",
                        "The name comes from world.locale_point, which holds Polish names; "
                        "an English page shows the bonus's technical name."),
             ("apply", "prob")),
            (P("Wartości na stopnie", "Values by grade"),
             P("lv1–lv5: wartość bonusu na kolejnym stopniu.",
               "lv1–lv5: the bonus's value at each grade."),
             ("lv1", "lv2", "lv3", "lv4", "lv5")),
            (P("Na jakim slocie może się wylosować", "Which slots it can roll on"),
             P("0 = bonus nie wchodzi na ten slot. Liczba to waga przy losowaniu.",
               "0 = the bonus never rolls on that slot. The number is its weight in the roll."),
             ("weapon", "body", "wrist", "foots", "neck", "head", "shield", "ear",
              "costume_body", "costume_hair", "costume_weapon", "pendant", "glove")),
        ),
        "siblings": ("item_attr_rare",),
        "related": ("bonus_points",),
    },
    "chests": {
        "db": "world", "table": "item_proto", "title": P("Skrzynki", "Chests"),
        "pk": ("vnum",), "order": ("vnum", "asc"),
        "filter_sql": "`type` IN (20, 23)",
        "search": ("vnum", "locale_name"),
        "search_hint": P("VNUM albo nazwa skrzynki", "VNUM or the chest's name"),
        "list": (("vnum", "VNUM", "key_item"), ("locale_name", P("Nazwa", "Name"), "name"),
                 ("type", P("Typ", "Type"), "itemtype"), ("stack", P("Stos", "Stack"), "int"),
                 ("gold", P("Cena", "Price"), "money")),
        "filters": (("type", P("Typ", "Type"), "itemtype"),),
        "sections": (
            (P("Skrzynka", "Chest"),
             P("Zawartości skrzynki NIE ma w bazie: silnik czyta ją z pliku "
               "special_item_group.txt (klucz to vnum tego przedmiotu) - zmienisz "
               "ją w edytorze „Skrzynki i drop” panelu. Tutaj zmienisz nazwę, cenę "
               "i stos samej skrzynki.",
               "What a chest holds is NOT in the database: the engine reads it from "
               "special_item_group.txt (keyed by this item's vnum) - change it in the "
               "panel's \"Chests and drops\" editor. Here you change the chest's own "
               "name, price and stack."),
             ("vnum", "locale_name", "name", "type", "subtype", "stack", "gold",
              "shop_buy_price")),
        ),
        "detail_module": "items",
    },
    "shops": {
        "db": "world", "table": "shop", "title": P("Sklepy NPC", "NPC shops"),
        "pk": ("vnum",), "order": ("vnum", "asc"),
        "search": ("vnum", "name", "npc_vnum"),
        "search_hint": P("Numer sklepu, nazwa albo VNUM NPC", "Shop number, name or NPC VNUM"),
        "list": (("vnum", P("Sklep", "Shop"), "key"), ("name", P("Nazwa", "Name"), "name"),
                 ("npc_vnum", "NPC", "mob"), ("vnum", P("Pozycji", "Items"), "shopcount")),
        "sections": (
            (P("Sklep", "Shop"),
             P("NPC to potwór/NPC z world.mob_proto, który otwiera ten sklep. "
               "Pozycje sklepu są niżej.",
               "The NPC is the monster/NPC of world.mob_proto who opens this shop. "
               "What the shop sells is below."),
             ("vnum", "name", "npc_vnum")),
        ),
        "related": ("shop_npc",),
    },
    "spawns": {
        "db": "world", "table": "land", "title": P("Działki gildii", "Guild land"),
        "pk": ("id",), "order": ("id", "asc"),
        "search": ("id", "map_index"),
        "search_hint": P("Numer działki albo numer mapy", "Plot number or map number"),
        "list": (("id", P("Działka", "Plot"), "key"), ("map_index", P("Mapa", "Map"), "int"),
                 ("x", "X", "int"), ("y", "Y", "int"),
                 (("width", "height"), P("Rozmiar", "Size"), "size"),
                 ("guild_level_limit", P("Min. poz. gildii", "Min. guild lv."), "int"),
                 ("price", P("Cena", "Price"), "money"),
                 ("enable", P("Dostępna", "Available"), "yesno")),
        "filters": (("map_index", P("Mapa", "Map"), "map"),
                    ("enable", P("Dostępna", "Available"), "yesno")),
        "sections": (
            (P("Położenie", "Position"),
             P("X/Y to lewy górny róg działki liczony od lewego górnego rogu mapy "
               "(nie bezwzględne współrzędne świata).",
               "X/Y is the plot's top left corner, counted from the map's top left "
               "corner (not the world's absolute coordinates)."),
             ("id", "map_index", "x", "y", "width", "height")),
            (P("Warunki zakupu", "Purchase conditions"), "",
             ("guild_level_limit", "price", "enable")),
        ),
        "related": (),
    },
    "skills": {
        "db": "world", "table": "skill_proto", "title": P("Umiejętności", "Skills"),
        "pk": ("dwVnum",), "order": ("dwVnum", "asc"),
        "search": ("dwVnum", "szName"),
        "search_hint": P("Numer albo nazwa techniczna", "Number or technical name"),
        "list": (("dwVnum", P("Nr", "No."), "key"),
                 ("szName", P("Nazwa techniczna", "Technical name"), "name"),
                 ("bType", P("Klasa", "Class"), "skillgroup"),
                 ("eSkillType", P("Rodzaj", "Kind"), "enum"),
                 ("bMaxLevel", P("Maks. poz.", "Max. lv."), "int"),
                 ("bLevelLimit", "Limit", "int"),
                 ("szCooldownPoly", "Cooldown", "code"),
                 ("dwTargetRange", P("Zasięg", "Range"), "int")),
        "filters": (("bType", P("Klasa", "Class"), "skillgroup"),
                    ("eSkillType", P("Rodzaj", "Kind"), "enum")),
        "sections": (
            (P("Podstawowe", "Basics"),
             P("Nazwa techniczna jest VARBINARY - silnik trzyma tam nazwę z kodu.",
               "The technical name is VARBINARY - the engine keeps the name from its code there."),
             ("dwVnum", "szName", "bType", "eSkillType", "bMaxLevel", "bLevelStep",
              "bLevelLimit", "iMaxHit", "dwTargetRange", "dwSplashRange")),
            (P("Efekty", "Effects"),
             P("To WZORY tekstowe: k to poziom umiejętności, atk/str/dex/con/iq "
               "to statystyki postaci.",
               "These are text FORMULAS: k is the skill's level, atk/str/dex/con/iq "
               "are the character's statistics."),
             ("szPointOn", "szPointPoly", "setAffectFlag", "szPointOn2", "szPointPoly2",
              "szDurationPoly2", "setAffectFlag2", "szPointOn3", "szPointPoly3",
              "szDurationPoly3", "setAffectFlag3")),
            (P("Koszt, czas i cooldown", "Cost, duration and cooldown"), "",
             ("szSPCostPoly", "szDurationPoly", "szDurationSPCostPoly", "szCooldownPoly",
              "szGrandMasterAddSPCostPoly", "szMasterBonusPoly", "szAttackGradePoly",
              "szSplashAroundDamageAdjustPoly")),
            (P("Flagi i wymagania", "Flags and requirements"),
             P("Odznaczenie wszystkich flag czyści zbiór.",
               "Unticking every flag empties the set."),
             ("setFlag", "prerequisiteSkillVnum", "prerequisiteSkillLevel")),
        ),
    },
    "exp": {
        "db": "common", "table": "exp_table", "title": P("Doświadczenie", "Experience"),
        "pk": ("level",), "order": ("level", "asc"),
        "search": ("level",),
        "search_hint": P("Poziom, np. 75", "Level, e.g. 75"),
        "per_page": 100,
        "list": (("level", P("Poziom", "Level"), "key"),
                 ("exp", P("Doświadczenie do awansu", "Experience to level up"), "num"),
                 ("exp", P("Zmiana wobec poprzedniego", "Change from the level before"),
                  "expdelta")),
        "sections": (
            (P("Poziom", "Level"),
             P("To koszt awansu z tego poziomu na następny (osobno dla każdego "
               "poziomu, nie suma narastająca).",
               "This is what it takes to go from this level to the next (for each "
               "level on its own, not a running total)."),
             ("level", "exp")),
        ),
    },
    "crafting": {
        "db": "world", "table": "crafting_proto", "title": P("Wytwarzanie", "Crafting"),
        "pk": ("vnum",), "order": ("vnum", "asc"),
        "search": ("vnum", "item_vnum", "comment"),
        "search_hint": P("Numer przepisu, VNUM wyniku albo komentarz",
                         "Recipe number, result VNUM or comment"),
        "list": (("vnum", P("Przepis", "Recipe"), "key"), ("item_vnum", P("Wynik", "Result"), "item"),
                 ("count", P("Ilość", "Count"), "int"), ("price", "Yang", "money"),
                 ("chance", P("Szansa", "Chance"), "pct"),
                 ("recipe", P("Składniki", "Ingredients"), "recipe"),
                 ("req_level", P("Wym. poz.", "Req. lv."), "int")),
        "sections": (
            (P("Przepis", "Recipe"),
             P("Szansa 1–100 (%); ilość to sztuki wyniku z jednego udanego wytworzenia.",
               "Chance 1–100 (%); the count is how many of the result one success makes."),
             ("vnum", "item_vnum", "count", "price", "chance", "comment")),
            (P("Składniki i wymagania", "Ingredients and requirements"),
             P("Składniki to pary vnum,ilość rozdzielone przecinkami, np. 50901,5,50721,10 "
               "(najwyżej 10 par, każdy przedmiot musi istnieć). Receptura to numer postępu "
               "nauki z ksiąg receptur, a wymagany postęp - ile razy trzeba ją przeczytać "
               "(0 i 0 = bez receptury). Wymagany poziom 0–255.",
               "The ingredients are vnum,count pairs separated by commas, e.g. "
               "50901,5,50721,10 (10 pairs at most, every item must exist). The recipe "
               "book is the number of the learning progress from recipe books, and the "
               "required progress how many times it has to be read (0 and 0 = no recipe "
               "book). Required level 0–255."),
             ("recipe", "recipe_vnum", "req_progress", "req_level")),
        ),
        # Cale przepisy mozna dodawac i usuwac (writes.py, sciezka crafting).
        "rows": True,
        "related": ("crafting_window",),
    },
    "quests": {
        "db": "world", "table": "quest_reward_proto", "title": P("Nagrody questów", "Quest rewards"),
        "pk": ("quest_name",), "order": ("quest_name", "asc"),
        "search": ("quest_name", "comment"),
        "search_hint": P("Nazwa questa", "Quest name"),
        "list": (("quest_name", "Quest", "key"), ("exp", "EXP", "num"),
                 ("gold", "Yang", "money"), ("alignment", P("Ranga", "Rank"), "int"),
                 ("items", P("Przedmioty", "Items"), "recipe")),
        "sections": (
            (P("Nagroda", "Reward"),
             P("Przedmioty to pary vnum,ilość.", "Items are vnum,count pairs."),
             ("quest_name", "exp", "gold", "alignment", "items", "comment")),
            (P("Nagrody dla klas", "Rewards by class"),
             P("Osobne listy dla wojownika, ninja, sury i szamana.",
               "Separate lists for the warrior, ninja, sura and shaman."),
             ("warrior_items", "assassin_items", "sura_items", "shaman_items")),
        ),
    },
    "itemshop": {
        "db": "common", "table": "itemshop_items", "title": "ItemShop",
        "pk": ("index",), "order": ("index", "asc"),
        "search": ("index", "vnum"),
        "search_hint": P("Pozycja albo VNUM przedmiotu", "Position or item VNUM"),
        "list": (("index", P("Poz.", "Pos."), "key"), ("vnum", P("Przedmiot", "Item"), "item"),
                 ("count", P("Ilość", "Count"), "int"), ("price", P("Cena", "Price"), "num"),
                 ("currency", P("Waluta", "Currency"), "enum"),
                 ("minLevel", P("Min. poz.", "Min. lv."), "int")),
        "filters": (("currency", P("Waluta", "Currency"), "enum"),),
        "sections": (
            (P("Pozycja", "Position"),
             P("DRAGON_COIN to smocze monety (account.cash), DRAGON_MARK - "
               "smocze znaki (account.cash_mark). Przedmiot musi być w item_proto, ilość - "
               "od 1 do stosu przedmiotu, cena od 0, a min. poziom nie wyższy niż najwyższy "
               "poziom serwera. Pozycję zdejmuje się ze sklepu usunięciem, nie zerem "
               "w przedmiocie albo w ilości.",
               "DRAGON_COIN is Dragon Coins (account.cash), DRAGON_MARK "
               "Dragon Marks (account.cash_mark). The item must be in item_proto, the count "
               "from 1 to the item's stack, the price from 0, and the min. level no higher "
               "than the server's highest level. An offer comes off the shop by deleting it, "
               "not with a 0 in its item or its count."),
             ("index", "vnum", "count", "price", "currency", "minLevel",
              "socket0", "socket1", "socket2")),
        ),
        # Whole offers are added and deleted (writes.py's ItemShop path): with
        # no delete Drip zeroed them instead, and the core died (7 October).
        "rows": True,
        "related": ("itemshop_page",),
    },
    "gm": {
        "db": "common", "table": "gmlist", "title": P("Prawa GM", "GM rights"),
        "pk": ("mID",), "order": ("mID", "asc"),
        "search": ("mAccount", "mName"),
        "search_hint": P("Konto albo postać", "Account or character"),
        "list": (("mID", "ID", "key"), ("mAccount", P("Konto", "Account"), "name"),
                 ("mName", P("Postać", "Character"), "text"),
                 ("mAuthority", P("Uprawnienia", "Authority"), "enum"),
                 ("mServerIP", P("IP serwera", "Server IP"), "text")),
        "sections": (
            (P("Uprawnienia", "Authority"),
             P("Liczy się nazwa postaci. Dostępne są tylko wartości z listy.",
               "The character's name is what counts. Only the values on the list are available."),
             ("mID", "mAccount", "mName", "mContactIP", "mServerIP", "mAuthority")),
        ),
    },
}


def module_spec(module_id):
    spec = MODULES.get(module_id)
    if spec is None:
        return None
    resolved = _resolve(spec)
    # Identyfikator modulu jedzie w deskryptorze: dwie strony moga czytac te
    # sama tabele (Drop czyta mob_proto z filtrem), wiec modulu nie zgadujemy.
    resolved["id"] = module_id
    return resolved


def _cols_of(entry):
    cols = entry[0]
    return cols if isinstance(cols, tuple) else (cols,)


def _resolve(spec):
    """Dopasowuje deskryptor do TEJ bazy: brakujace kolumny wypadaja."""
    out = dict(spec)
    table = schema.table(spec["db"], spec["table"]) or schema.find_table(spec["table"])
    if table is None:
        out["available"] = False
        return out
    out["available"] = True
    out["tbl"] = table
    out["db"] = table["db"]
    out["table"] = table["name"]
    cols = table["by_name"]

    def keep(name):
        return name in cols

    out["list"] = tuple(row for row in spec["list"] if all(keep(c) for c in _cols_of(row)))
    out["search"] = tuple(name for name in spec.get("search", ()) if keep(name))
    out["filters"] = tuple(f for f in spec.get("filters", ()) if keep(f[0]))
    sections = []
    used = set()
    for title, hint, names in spec["sections"]:
        present = tuple(name for name in names if keep(name))
        used.update(present)
        sections.append((title, hint, present))
    # Kolumny, ktorych deskryptor nie wymienia (inna wersja schematu), nie moga
    # zniknac z formularza - trafiaja do sekcji "Pozostale kolumny".
    if spec.get("show_rest", True):
        rest = tuple(c["name"] for c in table["columns"] if c["name"] not in used)
        if rest:
            sections.append((P("Pozostałe kolumny", "Other columns"),
                             P("Kolumny tej tabeli bez opisu w edytorze.",
                               "This table's columns the editor has no description for."),
                             rest))
    out["sections"] = tuple(sections)
    out["pk"] = tuple(name for name in spec["pk"] if keep(name)) or tuple(table["pk"])
    logical = tuple(name for name in (schema.logical_key(table["db"], table["name"]) or ())
                    if keep(name))
    out["key"] = out["pk"] or logical
    out["readonly"] = not out["key"] or not schema.writable(
        table['db'], table['name'], out['key'] if not out['pk'] else None)[0]
    order_col, order_dir = spec.get("order", (None, "asc"))
    out["order"] = (order_col if keep(order_col) else
                    (out["pk"][0] if out["pk"] else table["columns"][0]["name"]), order_dir)
    out["siblings"] = tuple(name for name in spec.get("siblings", ())
                            if schema.table(spec["db"], name))
    return out


# -----------------------------------------------------------------------------
#  Names in the reader's language (Blind and Tieru, 8 October)
#
#  item_proto and mob_proto name a vnum in Polish (locale_name). A reader of
#  English reads the official English name where the world still calls the
#  vnum what the core's names file matched (i18n.english_name), and a search
#  finds a row by either name in every language. The column stays Polish:
#  the form shows and writes what the table holds.
# -----------------------------------------------------------------------------
_NAME_KINDS = {"item_proto": "item", "mob_proto": "mob"}
# How many rows an English search may find by its English names alone; a
# term short enough to match more says little anyway.
ENGLISH_SEARCH_MAX = 2000


def name_kind(spec, column):
    """'item' or 'mob' when `column` is the game name of a proto table."""
    if column != "locale_name":
        return None
    return _NAME_KINDS.get(spec.get("table"))


def game_name(spec, column, row, value):
    """A proto's name as this reader reads it (i18n.game_name); anything else
    as it is."""
    kind = name_kind(spec, column)
    if kind is None or value in (None, ""):
        return value
    if isinstance(value, (bytes, bytearray)):
        col = spec["tbl"]["by_name"].get(column) or {}
        value = db.decode(value, col.get("charset"))
    return i18n.game_name(kind, row.get("vnum"), value)


def english_hits(spec, search):
    """The vnums of the rows whose official English name holds `search`,
    each held against the world's own name as it is stored now - a row the
    editor renamed is no longer found by the English of what it was."""
    kind = _NAME_KINDS.get(spec.get("table"))
    table = spec.get("tbl") or {}
    cols = table.get("by_name") or {}
    if kind is None or "locale_name" not in spec.get("search", ()) or "vnum" not in cols:
        return []
    candidates = i18n.english_candidates(kind, search)
    if not candidates or len(candidates) > ENGLISH_SEARCH_MAX:
        return []
    charset = cols["locale_name"].get("charset")
    found = []
    numbers = sorted(candidates)
    try:
        for start in range(0, len(numbers), 400):
            chunk = numbers[start:start + 400]
            for row in db.query("SELECT `vnum` AS v, `locale_name` AS n FROM %s WHERE `vnum` IN (%s)"
                                % (db.qt(table["db"], table["name"]), ",".join(["%s"] * len(chunk))),
                                tuple(chunk)):
                number = int(row["v"])
                if i18n.english_hash_ok(candidates.get(number), db.decode(row["n"], charset)):
                    found.append(number)
    except Exception:                              # noqa: BLE001 - the Polish search still runs
        return []
    return found


# -----------------------------------------------------------------------------
#  Lista
# -----------------------------------------------------------------------------
def _like_escape(text):
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Kolumny listy wyliczane poza tabela (albo z wielu kolumn) - bez sortowania.
_UNSORTED_KINDS = ("materials", "expdelta", "shopcount", "refineusers")


def sortable_columns(spec):
    out = []
    for entry in spec["list"]:
        if entry[2] in _UNSORTED_KINDS:
            continue
        out.append(_cols_of(entry)[0])
    return out


def build_list_query(spec, search="", filters=None, sort=None, page=1, per_page=PER_PAGE,
                     filter_sql=None, direction=None):
    """Sklada SELECT z LIMIT. Zwraca (sql, count_sql, params, order, per_page, offset)."""
    table = spec["tbl"]
    where, params = [], []
    if spec.get("filter_sql"):
        where.append("(" + spec["filter_sql"] + ")")
    if filter_sql:
        where.append("(" + filter_sql + ")")

    search = (search or "").strip()
    if search:
        parts = []
        number = search.lstrip("#")
        is_number = number.lstrip("-").isdigit()
        for name in spec["search"]:
            col = table["by_name"][name]
            if col["data_type"] in INT_TYPES:
                if is_number:
                    parts.append("%s = %%s" % db.qi(name))
                    params.append(int(number))
            elif col["enum"]:
                parts.append("%s LIKE %%s" % db.qi(name))
                params.append("%" + _like_escape(search.upper()) + "%")
            else:
                parts.append("%s LIKE %%s" % db.qi(name))
                params.append("%" + _like_escape(search) + "%")
        if not is_number:
            hits = english_hits(spec, search)
            if hits:
                parts.append("%s IN (%s)" % (db.qi("vnum"), ",".join(["%s"] * len(hits))))
                params.extend(hits)
        if parts:
            where.append("(" + " OR ".join(parts) + ")")
        else:
            where.append("1=0")

    for name, value in (filters or {}).items():
        if name not in table["by_name"] or value in ("", None):
            continue
        col = table["by_name"][name]
        if col["data_type"] in INT_TYPES:
            if str(value).lstrip("-").isdigit():
                where.append("%s = %%s" % db.qi(name))
                params.append(int(value))
        else:
            where.append("%s = %%s" % db.qi(name))
            params.append(value)

    clause = (" WHERE " + " AND ".join(where)) if where else ""

    order_col, order_dir = spec["order"]
    if sort and sort in table["by_name"] and sort in sortable_columns(spec) + list(spec["key"]):
        order_col = sort
        order_dir = direction or "asc"
    elif direction:
        order_dir = direction
    sql_dir = "DESC" if str(order_dir).lower() == "desc" else "ASC"
    order = "ORDER BY %s %s" % (db.qi(order_col), sql_dir)
    # Remis po kolumnie sortowania rozstrzyga klucz - bez tego strony moglyby
    # pokazywac te same wiersze dwa razy albo gubic je przy przechodzeniu dalej.
    for key_name in spec.get("key") or ():
        if key_name != order_col:
            order += ", %s ASC" % db.qi(key_name)

    page = max(1, int(page or 1))
    per_page = max(1, min(int(per_page or PER_PAGE), PER_PAGE_MAX))
    offset = (page - 1) * per_page

    select = "SELECT * FROM %s%s %s LIMIT %%s OFFSET %%s" % (db.qt(spec["db"], spec["table"]),
                                                             clause, order)
    count = "SELECT COUNT(*) AS n FROM %s%s" % (db.qt(spec["db"], spec["table"]), clause)
    return select, count, params, (order_col, sql_dir.lower()), per_page, offset


def list_rows(spec, search="", filters=None, sort=None, page=1, per_page=None,
              filter_sql=None, direction=None):
    per_page = per_page or spec.get("per_page") or PER_PAGE
    select, count, params, order, per_page, offset = build_list_query(
        spec, search, filters, sort, page, per_page, filter_sql, direction)
    total = int(db.scalar(count, tuple(params), 0) or 0)
    rows = db.query(select, tuple(params) + (per_page, offset))
    return [safety.decode_row(spec["tbl"], row) for row in rows], total, order, per_page


def _prefetch(spec, rows):
    """Nazwy przedmiotow i potworow z calej strony - po jednym zapytaniu."""
    items, mobs = [], []
    for entry in spec["list"]:
        cols, kind = _cols_of(entry), entry[2]
        for row in rows:
            if kind in ("item", "key_item") or (kind == "key" and spec["table"] == "item_proto"):
                items.append(row.get(cols[0]))
            elif kind == "mob":
                mobs.append(row.get(cols[0]))
            elif kind == "materials":
                items.extend(row.get(c) for c in cols[0::2])
            elif kind == "recipe":
                items.extend(_pairs(row.get(cols[0]))[0::2])
    if items:
        render.prefetch_names("item", items)
    if mobs:
        render.prefetch_names("mob", mobs)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pairs(text):
    """'27001,5,27002,3' -> [27001, 5, 27002, 3] (tylko liczby)."""
    out = []
    for part in str(text or "").replace(";", ",").replace("/", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return out


def format_cell(spec, entry, row, href=None, context=None):
    """(klasa_td, html) komorki listy."""
    cols, kind = _cols_of(entry), entry[2]
    value = row.get(cols[0])
    esc = render._esc
    if kind == "key":
        text = esc(value)
        return ("esq-c-key", ('<a href="%s">%s</a>' % (esc(href), text)) if href else text)
    if kind == "key_item":
        inner = render.icon_img(value) + '<span>%s</span>' % esc(value)
        return ("esq-c-key", ('<a class="esq-keyicon" href="%s">%s</a>' % (esc(href), inner))
                if href else inner)
    if kind == "name":
        value = game_name(spec, cols[0], row, value)
        text = esc(value) if value not in (None, "") else (
            '<span class="esq-dim">%s</span>' % esc(T("(bez nazwy)", "(no name)")))
        return ("esq-c-name", ('<a href="%s">%s</a>' % (esc(href), text)) if href else text)
    if kind == "item":
        return ("esq-c-ref", render.link_item(value) if value else '<span class="esq-dim">—</span>')
    if kind == "mob":
        return ("esq-c-ref", render.link_mob(value) if value else '<span class="esq-dim">—</span>')
    if kind == "refine":
        if not value:
            return ("esq-c-num", '<span class="esq-dim">—</span>')
        return ("esq-c-num", '<a href="/editsql/refine/world/%s">#%s</a>' % (esc(value), esc(value)))
    if kind == "itemtype":
        text, hint = labels.item_type_text(value)
        return ("", '<span class="esq-tag" title="%s">%s</span>' % (esc(hint), esc(text)))
    if kind == "itemsubtype":
        return ("", esc(labels.item_subtype_text(row.get("type"), value)))
    if kind == "rank":
        text, hint = labels.mob_rank_text(value)
        try:
            level = int(value or 0)
        except (TypeError, ValueError):
            level = 0
        return ("", '<span class="esq-tag esq-rank-%d" title="%s">%s</span>'
                % (max(0, min(level, 5)), esc(hint), esc(text)))
    if kind == "mobtype":
        text, hint = labels.mob_type_text(value)
        return ("", '<span title="%s">%s</span>' % (esc(hint), esc(text)))
    if kind == "empire":
        return ("", esc(labels.empire_text(value)[0]))
    if kind == "skillgroup":
        return ("", esc(labels.SKILL_GROUPS.get(_int(value), value)))
    if kind == "bonus":
        text, code = labels.bonus_text(value)
        return ("esq-c-name", ('<a href="%s" title="%s">%s</a>' % (esc(href), esc(code), esc(text)))
                if href else esc(text))
    if kind in ("money", "num"):
        return ("esq-c-num", render.num(value) if value is not None else "")
    if kind == "int":
        return ("esq-c-num", esc(value))
    if kind == "pct":
        return ("esq-c-num", "%s%%" % esc(value) if value is not None else "")
    if kind == "range":
        low, high = row.get(cols[0]), row.get(cols[1])
        if low == high:
            return ("esq-c-num", render.num(low))
        return ("esq-c-num", "%s&ndash;%s" % (render.num(low), render.num(high)))
    if kind == "size":
        return ("esq-c-num", "%s &times; %s" % (render.num(row.get(cols[0])),
                                                render.num(row.get(cols[1]))))
    if kind == "levels":
        values = [row.get(c) for c in cols]
        return ("esq-c-mono", " / ".join(esc(v) for v in values))
    if kind == "slot":
        try:
            weight = int(value or 0)
        except (TypeError, ValueError):
            weight = 0
        return ("esq-c-slot", ('<span class="esq-slot-on" title="%s">%d</span>'
                               % (esc(T("waga %d", "weight %d") % weight), weight))
                if weight else '<span class="esq-slot-off">·</span>')
    if kind == "materials":
        parts = []
        for vnum_col, count_col in zip(cols[0::2], cols[1::2]):
            vnum = row.get(vnum_col)
            if vnum:
                parts.append('<span class="esq-mat">%s<b>&times;%s</b></span>'
                             % (render.link_item(vnum, show_vnum=False), esc(row.get(count_col) or 0)))
        return ("esq-c-ref", "".join(parts) or
                '<span class="esq-dim">%s</span>' % esc(T("bez materiałów", "no materials")))
    if kind == "recipe":
        numbers = _pairs(value)
        if len(numbers) >= 2 and len(numbers) % 2 == 0:
            parts = ['<span class="esq-mat">%s<b>&times;%s</b></span>'
                     % (render.link_item(v, show_vnum=False), c)
                     for v, c in zip(numbers[0::2], numbers[1::2])]
            return ("esq-c-ref", "".join(parts))
        return ("", esc(value))
    if kind == "yesno":
        text = str(value or "")
        return ("", render.badge(T("tak", "yes"), "ok") if text.upper() in ("YES", "1")
                else render.badge(T("nie", "no")))
    if kind == "enum":
        return ("", '<span class="esq-tag">%s</span>' % esc(value) if value not in (None, "") else "")
    if kind == "code":
        return ("esq-c-mono", esc(value))
    if kind == "expdelta":
        previous = (context or {}).get("prev_exp", {}).get(row.get("level"))
        if previous in (None, 0) or value is None:
            return ("esq-c-num", '<span class="esq-dim">—</span>')
        try:
            change = 100.0 * (float(value) - float(previous)) / float(previous)
        except (TypeError, ValueError, ZeroDivisionError):
            return ("esq-c-num", "")
        cls = "esq-up" if change > 0 else ("esq-down" if change < 0 else "esq-dim")
        return ("esq-c-num", '<span class="%s">%+.1f%%</span>' % (cls, change))
    if kind == "shopcount":
        return ("esq-c-num", esc((context or {}).get("shop_counts", {}).get(value, 0)))
    if kind == "refineusers":
        total, sample = (context or {}).get("refine_users", {}).get(value, (0, []))
        if not total:
            return ("esq-c-ref", '<span class="esq-dim">%s</span>' % esc(T("żaden przedmiot", "no item")))
        parts = [render.link_item(vnum, show_vnum=False) for vnum in sample]
        if total > len(sample):
            parts.append('<span class="esq-dim">%s</span>'
                         % esc(T("i %d więcej", "and %d more") % (total - len(sample))))
        return ("esq-c-ref esq-c-users", " ".join(parts))
    return ("", esc(value))


def detail_href(spec, row):
    key_values = [row.get(name) for name in spec.get("key", ())]
    if not key_values or any(v is None for v in key_values):
        return None
    module_id = spec.get("detail_module") or spec.get("id") or _module_id_for(spec)
    return "/editsql/%s/%s/%s" % (module_id, spec["db"],
                                  "/".join(urllib.parse.quote(str(v), safe="") for v in key_values))


def query_string(params, drop=()):
    """Sklada 'a=1&b=2&' z niepustych parametrow (do linkow paginacji/sortowania)."""
    parts = []
    for name, value in params.items():
        if name in drop or value in (None, ""):
            continue
        parts.append("%s=%s" % (urllib.parse.quote(str(name)), urllib.parse.quote(str(value), safe="")))
    return ("&".join(parts) + "&") if parts else ""


def _context(spec, rows):
    context = {}
    kinds = {entry[2] for entry in spec["list"]}
    if "expdelta" in kinds and rows:
        levels = [row.get("level") for row in rows if row.get("level") is not None]
        try:
            prev = db.query("SELECT `level` AS l, `exp` AS e FROM %s WHERE `level` IN (%s)"
                            % (db.qt(spec["db"], spec["table"]), ",".join(["%s"] * len(levels))),
                            tuple(int(l) - 1 for l in levels)) if levels else []
            context["prev_exp"] = {int(r["l"]) + 1: r["e"] for r in prev}
        except Exception:                          # noqa: BLE001
            context["prev_exp"] = {}
    if "shopcount" in kinds and rows:
        child = schema.table("world", "shop_item")
        shops = [row.get("vnum") for row in rows]
        counts = {}
        if child is not None and shops:
            try:
                for r in db.query("SELECT `shop_vnum` AS s, COUNT(*) AS n FROM %s WHERE `shop_vnum` IN (%s) "
                                  "GROUP BY `shop_vnum`" % (db.qt(child["db"], child["name"]),
                                                            ",".join(["%s"] * len(shops))),
                                  tuple(shops)):
                    counts[r["s"]] = int(r["n"])
            except Exception:                      # noqa: BLE001
                counts = {}
        context["shop_counts"] = counts
    if "refineusers" in kinds and rows:
        from . import modules
        try:
            context["refine_users"] = modules.refine_users([row.get("id") for row in rows])
        except Exception:                          # noqa: BLE001 - lista musi sie pokazac
            context["refine_users"] = {}
    return context


def list_html(spec, rows, base_url, search="", filters=None, sort=None, direction=None,
              page_no=1, select_form=None):
    """Tabela listy z sortowalnymi naglowkami i klikalnymi wierszami.

    `select_form` (id formularza) dodaje pierwsza kolumne z polami wyboru
    "pk" - tylko dla modulow, ktore umieja usuwac cale wiersze (spec["rows"]).
    """
    _prefetch(spec, rows)
    context = _context(spec, rows)
    params = {"q": search}
    params.update(filters or {})
    current_col, current_dir = sort or spec["order"][0], (direction or spec["order"][1])
    sortable = set(sortable_columns(spec)) | set(spec.get("key") or ())
    heads = []
    if select_form:
        heads.append('<th class="esq-c-check"><label class="esq-check" title="%s">'
                     '<input type="checkbox" data-esq-check-all="%s" /></label></th>'
                     % (render._esc(T("Zaznacz wszystkie na tej stronie", "Select all on this page")),
                        render._esc(select_form)))
    for entry in spec["list"]:
        col = _cols_of(entry)[0]
        label = render._esc(entry[1])
        numeric = entry[2] in ("money", "num", "int", "pct", "range", "refine", "expdelta",
                               "shopcount", "size")
        cls = "esq-c-num" if numeric else ""
        if col in sortable and entry[2] not in _UNSORTED_KINDS:
            next_dir = "desc" if (col == current_col and current_dir == "asc") else "asc"
            arrow = ""
            if col == current_col:
                arrow = '<i class="esq-sort">%s</i>' % ("&#9650;" if current_dir == "asc" else "&#9660;")
                cls += " esq-sorted"
            href = "%s?%ssort=%s&dir=%s" % (base_url, query_string(params), col, next_dir)
            label = '<a href="%s" title="%s">%s%s</a>' % (render._esc(href),
                                                          render._esc(T("Sortuj", "Sort")),
                                                          label, arrow)
        heads.append('<th class="%s">%s</th>' % (cls.strip(), label))
    heads.append('<th class="esq-c-act"></th>')

    body_rows = []
    for row in rows:
        href = detail_href(spec, row)
        cells = [format_cell(spec, entry, row, href, context) for entry in spec["list"]]
        if select_form:
            key_values = [row.get(name) for name in spec.get("key") or ()]
            cells.insert(0, ("esq-c-check", (
                '<label class="esq-check"><input type="checkbox" name="pk" value="%s" form="%s" '
                'title="%s" /></label>'
                % (render._esc("/".join(str(v) for v in key_values)), render._esc(select_form),
                   render._esc(T("Zaznacz do usunięcia", "Select to delete"))))
                if key_values and None not in key_values else ""))
        if href:
            cells.append(("esq-c-act", '<a class="esq-btn esq-btn-small" href="%s">%s</a>'
                          % (render._esc(href), render._esc(T("Edytuj", "Edit")))))
            attrs = ' data-href="%s"' % render._esc(href)
        else:
            cells.append(("esq-c-act", '<span class="esq-dim">%s</span>'
                          % render._esc(T("tylko odczyt", "read only"))))
            attrs = ""
        body_rows.append((attrs, cells))
    return render.table(None, body_rows, klass="esq-table esq-list",
                        empty=T("Nic nie pasuje do wyszukiwania i filtrów.",
                                "Nothing matches the search and the filters."),
                        head_html="".join(heads))


def _module_id_for(spec):
    for key, value in MODULES.items():
        if value["table"] == spec["table"] and value["db"] == spec["db"]:
            return key
    return spec["table"]


def _filter_label(kind, value, row_type=None):
    if kind == "itemtype":
        return "%s · %s" % (value, labels.item_type_text(value)[0])
    if kind == "itemsubtype":
        name = labels.item_subtype_text(row_type, value)
        return ("%s · %s" % (value, name)) if name != str(value) else str(value)
    if kind == "rank":
        return "%s · %s" % (value, labels.mob_rank_text(value)[0])
    if kind == "mobtype":
        return "%s · %s" % (value, labels.mob_type_text(value)[0])
    if kind == "empire":
        return labels.empire_text(value)[0]
    if kind == "skillgroup":
        return "%s · %s" % (value, labels.SKILL_GROUPS.get(_int(value), "?"))
    if kind == "yesno":
        return T("tak", "yes") if str(value).upper() in ("YES", "1") else T("nie", "no")
    if kind == "map":
        from . import modules
        return modules.map_label(value)
    return str(value)


def toolbar_html(spec, action, current, search="", sort=None, direction=None, total=None):
    """Pasek nad tabela: wyszukiwarka + filtry (listy z DISTINCT) w jednym formularzu."""
    table = spec["tbl"]
    parts = ['<form class="esq-toolbar" method="get" action="%s">' % render._esc(action)]
    if spec["search"]:
        parts.append('<div class="esq-tb-field esq-tb-search"><label for="esq-q">%s</label>'
                     '<input type="search" id="esq-q" name="q" value="%s" placeholder="%s" /></div>'
                     % (render._esc(T("Szukaj", "Search")), render._esc(search),
                        render._esc(spec.get("search_hint") or T("Szukaj", "Search"))))
    for name, title, kind in spec["filters"]:
        col = table["by_name"][name]
        where, params = "", ()
        if spec.get("filter_sql"):
            where = " WHERE " + spec["filter_sql"]
        # Podtyp ma sens tylko przy wybranym typie - wtedy pokazuje JEGO podtypy.
        row_type = None
        if kind == "itemsubtype":
            row_type = current.get("type")
            if row_type in (None, "") or not str(row_type).lstrip("-").isdigit():
                continue
            where += (" AND " if where else " WHERE ") + "`type` = %s"
            params = (int(row_type),)
        try:
            rows = db.query("SELECT DISTINCT %s AS v FROM %s%s ORDER BY %s LIMIT 200"
                            % (db.qi(name), db.qt(spec["db"], spec["table"]), where, db.qi(name)),
                            params)
        except Exception:                          # noqa: BLE001
            continue
        options = ['<option value="">%s</option>' % render._esc(T("wszystkie", "all"))]
        for row in rows:
            value = db.decode(row["v"], col["charset"])
            if value is None or value == "":
                continue
            selected = " selected" if str(current.get(name)) == str(value) else ""
            options.append('<option value="%s"%s>%s</option>'
                           % (render._esc(value), selected,
                              render._esc(_filter_label(kind, value, row_type))))
        parts.append('<div class="esq-tb-field"><label for="esq-f-%s">%s</label>'
                     '<select id="esq-f-%s" name="%s" onchange="this.form.submit()">%s</select></div>'
                     % (render._esc(name), render._esc(title), render._esc(name),
                        render._esc(name), "".join(options)))
    if sort:
        parts.append('<input type="hidden" name="sort" value="%s" />' % render._esc(sort))
    if direction:
        parts.append('<input type="hidden" name="dir" value="%s" />' % render._esc(direction))
    active = bool(search) or any(current.get(f[0]) not in (None, "") for f in spec["filters"])
    parts.append('<div class="esq-tb-buttons"><button type="submit" class="esq-btn esq-btn-small '
                 'esq-btn-go">%s</button>%s</div>'
                 % (render._esc(T("Szukaj", "Search")),
                    '<a class="esq-btn esq-btn-small esq-btn-ghost" href="%s">%s</a>'
                    % (render._esc(action), render._esc(T("Wyczyść", "Clear"))) if active else ""))
    parts.append("</form>")
    if total is not None:
        parts.append('<p class="esq-count">%s %s</p>'
                     % (render.num(total), i18n.plural(total, ("wiersz", "wiersze", "wierszy"),
                                                       ("row", "rows"))))
    return "".join(parts)


def filters_html(spec, action, current, search=""):
    """Zgodnosc wsteczna: pasek wyszukiwania i filtrow."""
    return toolbar_html(spec, action, current, search)


def _plural(n, one, few, many):
    """Polish only: the three forms. A text shown to a reader goes through
    i18n.plural, which has the English forms beside these."""
    n = abs(int(n))
    if n == 1:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


plural = _plural


# -----------------------------------------------------------------------------
#  Naglowek wiersza (karta nad formularzem)
# -----------------------------------------------------------------------------
def row_card(spec, row):
    esc = render._esc
    table = spec["table"]
    facts = []
    icon = ""
    if table == "item_proto":
        icon = render.icon_img(row.get("vnum"), size="big")
        type_text = labels.item_type_text(row.get("type"))[0]
        facts.append(render.badge(type_text))
        sub = labels.item_subtype_text(row.get("type"), row.get("subtype"))
        if sub and sub != str(row.get("subtype")):
            facts.append(render.badge(sub))
        if row.get("limittype0") == 1 and row.get("limitvalue0"):
            facts.append(render.badge(T("poziom %s", "level %s") % row.get("limitvalue0")))
        if row.get("gold"):
            facts.append('<span class="esq-fact">%s <b>%s</b> yang</span>'
                         % (esc(T("cena", "price")), render.num(row.get("gold"))))
    elif table == "mob_proto":
        facts.append(render.badge(T("poziom %s", "level %s") % row.get("level")))
        rank_text = labels.mob_rank_text(row.get("rank"))[0]
        facts.append('<span class="esq-tag esq-rank-%s">%s</span>'
                     % (esc(max(0, min(int(row.get("rank") or 0), 5))), esc(rank_text)))
        facts.append(render.badge(labels.mob_type_text(row.get("type"))[0]))
        facts.append('<span class="esq-fact">%s <b>%s</b></span>'
                     % (esc(T("PŻ", "HP")), render.num(row.get("max_hp"))))
        facts.append('<span class="esq-fact">%s <b>%s–%s</b></span>'
                     % (esc(T("obrażenia", "damage")), render.num(row.get("damage_min")),
                        render.num(row.get("damage_max"))))
        facts.append('<span class="esq-fact">EXP <b>%s</b></span>' % render.num(row.get("exp")))
    else:
        return ""
    return ('<div class="esq-card">%s<div class="esq-card-body"><div class="esq-card-facts">%s</div></div></div>'
            % (icon, " ".join(facts)))


# -----------------------------------------------------------------------------
#  Formularz i podglad
# -----------------------------------------------------------------------------
def _korean(value):
    """Nazwa wewnetrzna (EUC-KR w kolumnie cp1250) do pokazania."""
    if not isinstance(value, str):
        return value
    try:
        return value.encode("cp1250").decode("euc_kr")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _field_html(spec, row, col, readonly_all, invalid=(), insert=False):
    """Pole formularza. insert=True to NOWY wiersz: klucz trzeba wpisac."""
    db_name, table_name = spec["db"], spec["table"]
    name = col["name"]
    value = row.get(name)
    label, kind = fields.info(db_name, table_name, name)
    widget, extra = render.widget_for(col)
    hint_bits = []
    is_key = name in (spec.get("key") or ())
    locked = ((is_key and not insert) or name in safety.locked_columns(db_name, table_name)
              or readonly_all or col["auto"] or col.get("extra", "").startswith("on update"))
    choices = None
    after = ""
    if col["enum"]:
        choices = ([""] if col["nullable"] else []) + list(col["choices"])
    elif kind and not locked:
        if kind.startswith("flags:"):
            names = fields.flag_names(kind.split(":", 1)[1], value)
            after = ('<span class="esq-field-flags">%s</span>'
                     % (render._esc(", ".join(names)) if names else
                        render._esc(T("brak ustawionych bitów", "no bits set"))))
        elif kind in ("item", "mob"):
            extra += ' data-esq-lookup="%s"' % kind
            preview = (render.link_item(value) if kind == "item" else render.link_mob(value)) \
                if value else '<span class="esq-dim">%s</span>' % render._esc(T("brak", "none"))
            after = '<span class="esq-lookup" id="f_%s_look">%s</span>' % (render._esc(name), preview)
        elif kind == "refine":
            after = ('<span class="esq-lookup"><a href="/editsql/refine/world/%s">%s</a></span>'
                     % (render._esc(value),
                        render._esc(T("otwórz przepis #%s", "open recipe #%s") % value))) if value else ""
        else:
            choices = fields.choices(kind, row, value)
            if choices is not None:
                widget = "select"
    if is_key:
        hint_bits.append(T("numer nowego wiersza - musi być wolny", "the new row's number - must be free")
                         if insert else T("klucz wiersza", "row key"))
    if name == "name" and table_name in ("item_proto", "mob_proto"):
        value = _korean(value)
        hint_bits.append(T("tylko do odczytu", "read only"))
    if name_kind(spec, name) and i18n.lang() != "pl" and not insert:
        # The field is the Polish name the game holds, and the lists show a
        # reader of English the official English one: say which, so an edit
        # of "Wilk" is not taken for a typo of "Wolf".
        english = game_name(spec, name, row, value)
        if english and english != value:
            hint_bits.append("the Polish name the game holds; the lists show its official English "
                             "name, “%s”, which a rename here drops" % english)
    if locked:
        if widget in ("select", "set"):
            # Zablokowana lista: pokazujemy wartosc jak zwykle pole tylko do odczytu.
            widget, choices = "text", None
            extra = ""
        extra += ' readonly="readonly" tabindex="-1"'
    if widget == "set":
        choices = list(col["choices"])
    elif widget == "select" and choices is None:
        widget = "text"
    html = render.field(name, label, value, " · ".join(hint_bits), widget, choices, extra,
                        column=name, after=after, title_attr=render.column_hint(col))
    if name in invalid:
        html = html.replace('<div class="esq-field', '<div class="esq-field esq-invalid', 1)
    return html


def form_html(spec, row, action, token=None, edit_notes=(), readonly=False, invalid=()):
    """Formularz edycji z sekcjami. "Podglad zmian" idzie POST-em (action=preview)."""
    table = spec["tbl"]
    parts = ['<div id="register" class="esq-form"><form method="post" action="%s" data-esq-edit="1">'
             % render._esc(action), render.csrf_input()]
    if token:
        parts.append('<input type="hidden" name="token" value="%s" />' % render._esc(token))
    parts.append(render.notes_html(spec["db"], spec["table"]))
    for note in edit_notes:
        parts.append(note)
    if readonly:
        parts.append('<div class="esq-note esq-note-warn">%s</div>' % render._esc(T(
            "Ta tabela nie ma klucza, który jednoznacznie wskazywałby wiersz, więc edytor "
            "pokazuje ją tylko do odczytu - zapis mógłby zmienić wiele wierszy naraz.",
            "This table has no key that points at one row, so the editor shows it read "
            "only - a save could change many rows at once.")))
    for title, hint, names in spec["sections"]:
        cells = [_field_html(spec, row, table["by_name"][name], readonly, invalid) for name in names]
        if cells:
            parts.append(render.section(title, "".join(cells), hint))
    back = T("Wróć do listy", "Back to the list")
    if readonly:
        parts.append(render.actions(((back, "link",
                                      'href="/editsql/%s"' % render._esc(spec["id"])),)))
    else:
        parts.append(render.actions(
            ((T("Podgląd zmian", "Preview changes"), "primary", 'name="action" value="preview"'),
             (T("Przywróć wartości", "Reset values"), "reset", ""),
             (back, "link", 'href="/editsql/%s"' % render._esc(spec["id"]))),
            sticky=True,
            extra='<span class="esq-dirty-count" id="esq-dirty">%s</span>'
                  % render._esc(T("Brak zmian", "No changes"))))
    parts.append("</form></div>")
    return "".join(parts)


def preview_html(spec, row, changes, action, token):
    """Ekran POTWIERDZENIA: było -> będzie, i dopiero potem zapis."""
    pk_text = ", ".join("%s = %s" % (name, row.get(name)) for name in spec.get("key") or ())
    empty = T("(puste)", "(empty)")
    rows = []
    for change in changes:
        label = fields.label(spec["db"], spec["table"], change["column"])
        rows.append(("", [
            '<b>%s</b> <code class="esq-col">%s</code>' % (render._esc(label), render._esc(change["column"])),
            '<code class="esq-old">%s</code>' % render._esc(change["display_old"] or empty),
            ("esq-c-arrow", "&rarr;"),
            '<code class="esq-new">%s</code>' % render._esc(change["display_new"] or empty)]))
    count = len(changes)
    if i18n.lang() == "pl":
        note = ('Tabela <b>%s.%s</b>, wiersz <b>%s</b>. '
                '<b>Nic nie zostało jeszcze zapisane</b> - sprawdź %s i potwierdź.'
                % (render._esc(spec["db"]), render._esc(spec["table"]), render._esc(pk_text),
                   "zmianę" if count == 1 else "%d zmiany" % count if 2 <= count <= 4
                   else "%d zmian" % count))
    else:
        note = ('Table <b>%s.%s</b>, row <b>%s</b>. <b>Nothing has been saved yet</b> - '
                'check %s and confirm.'
                % (render._esc(spec["db"]), render._esc(spec["table"]), render._esc(pk_text),
                   "the change" if count == 1 else "the %d changes" % count))
    body = [
        '<div class="esq-note esq-note-info">%s</div>' % note,
        render.notes_html(spec["db"], spec["table"]),
        render.table([T("Pole", "Field"), T("Było", "Was"), "", T("Będzie", "Will be")], rows,
                     klass="esq-table esq-diff"),
        '<div id="register"><form method="post" action="%s">%s'
        '<input type="hidden" name="token" value="%s" />'
        '%s</form></div>' % (render._esc(action), render.csrf_input(), render._esc(token),
                             render.actions(((T("Zapisz zmiany", "Save changes"), "primary",
                                              'name="action" value="save"'),
                                             (T("Wróć do edycji", "Back to editing"), "plain",
                                              'name="action" value="cancel"'))))
    ]
    return "".join(body)


# -----------------------------------------------------------------------------
#  Nowy wiersz (tylko moduly z spec["rows"] - dzis Wytwarzanie)
# -----------------------------------------------------------------------------
def insert_form_html(spec, row, action, invalid=(), notes=(),
                     preview_label=None):
    """Formularz NOWEGO wiersza. Jak edycja: "Podglad" niczego jeszcze nie zapisuje."""
    if preview_label is None:
        preview_label = T("Podgląd nowego wiersza", "Preview the new row")
    table = spec["tbl"]
    parts = ['<div id="register" class="esq-form"><form method="post" action="%s" data-esq-edit="1">'
             % render._esc(action), render.csrf_input(), render.notes_html(spec["db"], spec["table"])]
    parts.extend(notes)
    for title, hint, names in spec["sections"]:
        cells = [_field_html(spec, row, table["by_name"][name], False, invalid, insert=True)
                 for name in names]
        if cells:
            parts.append(render.section(title, "".join(cells), hint))
    parts.append(render.actions(
        ((preview_label, "primary", 'name="action" value="preview"'),
         (T("Przywróć wartości", "Reset values"), "reset", ""),
         (T("Wróć do listy", "Back to the list"), "link",
          'href="/editsql/%s"' % render._esc(spec["id"]))),
        sticky=True, extra='<span class="esq-dirty-count" id="esq-dirty">%s</span>'
                           % render._esc(T("Brak zmian", "No changes"))))
    parts.append("</form></div>")
    return "".join(parts)


def _value_html(spec, name, value):
    """Wartosc nowego wiersza na ekranie potwierdzenia (przedmioty jako odnosniki)."""
    if isinstance(value, (bytes, bytearray)):
        value = db.decode(value, spec["tbl"]["by_name"][name]["charset"])
    if value is None:
        return '<span class="esq-dim">%s</span>' % render._esc(T("(puste)", "(empty)"))
    _label, kind = fields.info(spec["db"], spec["table"], name)
    if kind == "item" and value:
        return render.link_item(value) + ' <code>%s</code>' % render._esc(value)
    if name == "recipe" and spec["table"] == "crafting_proto":
        numbers = _pairs(value)
        mats = "".join('<span class="esq-mat">%s<b>&times;%s</b></span>'
                       % (render.link_item(v), render._esc(c))
                       for v, c in zip(numbers[0::2], numbers[1::2]))
        return mats + ' <code>%s</code>' % render._esc(value)
    return '<code class="esq-new">%s</code>' % render._esc(value if value != "" else T("(puste)", "(empty)"))


def insert_preview_html(spec, values, action, token, notes=(), save_label=None):
    """Ekran POTWIERDZENIA nowego wiersza: wszystkie kolumny, dopiero potem zapis."""
    if save_label is None:
        save_label = T("Dodaj wiersz", "Add the row")
    key_text = ", ".join("%s = %s" % (name, values.get(name)) for name in spec.get("key") or ())
    rows = []
    for col in spec["tbl"]["columns"]:
        if col["name"] not in values:
            continue
        rows.append(("", ['<b>%s</b> <code class="esq-col">%s</code>'
                          % (render._esc(fields.label(spec["db"], spec["table"], col["name"])),
                             render._esc(col["name"])),
                          _value_html(spec, col["name"], values[col["name"]])]))
    return "".join([
        '<div class="esq-note esq-note-info">%s</div>'
        % (T('Tabela <b>%s.%s</b>, nowy wiersz <b>%s</b>. '
             '<b>Nic nie zostało jeszcze zapisane</b> - sprawdź wartości i potwierdź.',
             'Table <b>%s.%s</b>, new row <b>%s</b>. '
             '<b>Nothing has been saved yet</b> - check the values and confirm.')
           % (render._esc(spec["db"]), render._esc(spec["table"]), render._esc(key_text))),
        render.notes_html(spec["db"], spec["table"]),
        "".join(notes),
        render.table([T("Pole", "Field"), T("Wartość", "Value")], rows, klass="esq-table esq-diff"),
        '<div id="register"><form method="post" action="%s">%s'
        '<input type="hidden" name="token" value="%s" />%s</form></div>'
        % (render._esc(action), render.csrf_input(), render._esc(token),
           render.actions(((save_label, "primary", 'name="action" value="save"'),
                           (T("Wróć do edycji", "Back to editing"), "plain",
                            'name="action" value="cancel"'))))])


def related_html(spec, row, key="related"):
    """Powiazania wiersza - to, co w tej bazie nie ma kluczy obcych."""
    out = []
    for kind in spec.get(key, ()):
        html = _related_view(kind, spec, row)
        if html:
            out.append(html)
    return "".join(out)


def _related_view(kind, spec, row):
    from . import modules
    handler = getattr(modules, "related_" + kind, None)
    if handler is None:
        return ""
    try:
        return handler(spec, row)
    except Exception as exc:                       # noqa: BLE001 - powiazania nie moga psuc edycji
        return ('<div class="esq-note esq-note-info">%s</div>'
                % (T("Nie udało się pokazać powiązań (%s): %s",
                     "Could not show the related rows (%s): %s")
                   % (render._esc(kind), render._esc(exc))))
