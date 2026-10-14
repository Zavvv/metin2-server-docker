-- The Hexagonal Chest event (Kiciamol, 14 October): the 21 chests of the maps
-- after the first villages, 55000-55020, as world.item_proto rows, each a copy
-- of 50037 - the package's Hexagonal Treasure Chest, the M1 one - with its own
-- vnum and names: a giftbox (type 23) of one cell that stacks to 200
-- (STACKABLE, flag 4), its proto name HEX_MAP_<vnum> and its Polish name in
-- ASCII, as his installer made them. mt2009 only: the db core reads the rows
-- at boot (PROTO_FROM_DB), and apply.sh runs this before any core loads an
-- item. The chests' groups (special_item_group.hexagonal.txt) are the game
-- image's, and the client's rows are port/protoify.py's.
--
-- Idempotent: every start runs it. A vnum already in the table - this event's
-- row, or anything an operator put there - is left as it is, and one that is
-- not this event's is named, never overwritten. The list is held to
-- files/hexagonal_catalog.json by tests/hexagonal_catalog_test.py, and
-- tools/generate_english_names.py reads the names from it (--added-items).
USE world;
CREATE TEMPORARY TABLE pb_hexagonal_new_items (
 vnum INT UNSIGNED NOT NULL PRIMARY KEY,
 name VARCHAR(32) NOT NULL,
 locale_name VARCHAR(32) NOT NULL
) ENGINE=MEMORY DEFAULT CHARSET=latin1;
-- (Its names are ASCII and compared as bytes: the world's collation is its own.)
INSERT INTO pb_hexagonal_new_items VALUES
 (55000, 'HEX_MAP_55000', 'Heks. Szkatulka M2'),
 (55001, 'HEX_MAP_55001', 'Heks. Szkatulka Tereny Gildii'),
 (55002, 'HEX_MAP_55002', 'Heks. Szkatulka Gora Sohan'),
 (55003, 'HEX_MAP_55003', 'Heks. Szkatulka Ognista Ziemia'),
 (55004, 'HEX_MAP_55004', 'Heks. Szkatulka Pustynia'),
 (55005, 'HEX_MAP_55005', 'Heks. Szkatulka Dolina Orkow'),
 (55006, 'HEX_MAP_55006', 'Heks. Szkatulka Swiatynia'),
 (55007, 'HEX_MAP_55007', 'Heks. Szkatulka Wieza Demonow'),
 (55008, 'HEX_MAP_55008', 'Heks. Szkatulka Las Duchow'),
 (55009, 'HEX_MAP_55009', 'Heks. Szkatulka Czerwony Las'),
 (55010, 'HEX_MAP_55010', 'Heks. Szkatulka Loch Pajakow V2'),
 (55011, 'HEX_MAP_55011', 'Heks. Szkatulka Grota V1'),
 (55012, 'HEX_MAP_55012', 'Heks. Szkatulka Grota V2'),
 (55013, 'HEX_MAP_55013', 'Heks. Szkatulka Loch Malp V2'),
 (55014, 'HEX_MAP_55014', 'Heks. Szkatulka Loch Malp V3'),
 (55015, 'HEX_MAP_55015', 'Heks. Szkatulka Komnata Smoka'),
 (55016, 'HEX_MAP_55016', 'Heks. Szkatulka Przyladek'),
 (55017, 'HEX_MAP_55017', 'Heks. Szkatulka Nefrytowa Zatoka'),
 (55018, 'HEX_MAP_55018', 'Heks. Szkatulka Klif Gautama'),
 (55019, 'HEX_MAP_55019', 'Heks. Szkatulka Gory Grzmotu'),
 (55020, 'HEX_MAP_55020', 'Heks. Szkatulka Twierdza');
-- One copy of 50037 a chest, every column the table has, whatever its columns.
CREATE TEMPORARY TABLE pb_hexagonal_rows AS
 SELECT t.*, n.vnum AS hex_vnum, n.name AS hex_name, n.locale_name AS hex_locale_name
 FROM world.item_proto t JOIN pb_hexagonal_new_items n
 WHERE t.vnum = 50037;
UPDATE pb_hexagonal_rows SET vnum = hex_vnum, name = hex_name, locale_name = hex_locale_name,
 type = 23, subtype = 0, size = 1, stack = 200, flag = 4, refined_vnum = 0, refine_set = 0;
ALTER TABLE pb_hexagonal_rows DROP COLUMN hex_vnum, DROP COLUMN hex_name, DROP COLUMN hex_locale_name;
INSERT IGNORE INTO world.item_proto SELECT * FROM pb_hexagonal_rows;
-- What the migrator's log says.
SELECT CONCAT('hexagonal chests: ', COUNT(*), ' of ', (SELECT COUNT(*) FROM pb_hexagonal_new_items),
              ' in world.item_proto')
 FROM world.item_proto p JOIN pb_hexagonal_new_items n ON n.vnum = p.vnum AND BINARY p.name = BINARY n.name;
SELECT CONCAT('WARNING: hexagonal chest ', n.vnum, ' is already another item (', p.name,
              '); its group opens that item')
 FROM world.item_proto p JOIN pb_hexagonal_new_items n ON n.vnum = p.vnum
 WHERE BINARY p.name <> BINARY n.name ORDER BY n.vnum;
SELECT 'WARNING: no 50037 in world.item_proto - the hexagonal chests were not added'
 FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM world.item_proto WHERE vnum = 50037);
DROP TEMPORARY TABLE pb_hexagonal_rows;
DROP TEMPORARY TABLE pb_hexagonal_new_items;
