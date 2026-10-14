-- Iwakura x Tyrion Patch 19, point 10: the NPC crafting windows as a table.
-- Run by apply.sh on every start (mt2009 only: r40250 has no world database).
--
-- The package lists each window's recipes in quest/libs/crafting/
-- crafting_data.lua, a file of the image, so a recipe the operator added to a
-- window by hand was gone at the next update. The list lives here now: one
-- row a recipe of a window, in its order. quest/m2_crafting_windows.lua,
-- dofile'd after crafting_data.lua when a core loads its quests, puts every
-- window of this table in place of the file's (a recipe crafting_proto lacks
-- is left out); a window the table does not name keeps the file's list, and
-- an empty or unreadable table changes nothing. A change takes effect at the
-- next start of the cores.
--
-- window_id is the window's number in crafting_data.lua: 101..110 for the
-- package's named windows (CRAFTING_BLACKSMITH = 101 ... CRAFTING_BUM = 110,
-- opened by their NPCs' quests), and the NPC's own vnum for the guild
-- alchemists (20060..20072). The rows below are the package's file as it is;
-- they are written once (web_m2p_contract_state 'crafting_window_seeded'), so
-- a window the operator emptied stays empty.
CREATE TABLE IF NOT EXISTS world.crafting_window (
 window_id INT UNSIGNED NOT NULL, recipe_id INT UNSIGNED NOT NULL,
 sort_order INT UNSIGNED NOT NULL DEFAULT 0,
 PRIMARY KEY (window_id, recipe_id), KEY ordered (window_id, sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
CREATE TABLE IF NOT EXISTS world.crafting_window_name (
 window_id INT UNSIGNED PRIMARY KEY, name VARCHAR(48) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
CREATE TABLE IF NOT EXISTS player.web_m2p_contract_state (
 name VARCHAR(64) PRIMARY KEY, value BIGINT NOT NULL,
 updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TEMPORARY TABLE world.tmp_crafting_window (
 window_id INT UNSIGNED NOT NULL, recipe_id INT UNSIGNED NOT NULL, sort_order INT UNSIGNED NOT NULL
);
INSERT INTO world.tmp_crafting_window (window_id, recipe_id, sort_order) VALUES
(101,1,1),(101,2,2),(101,3,3),(101,4,4),(101,5,5),(101,6,6),(102,11,1),(102,12,2),(102,13,3),(102,14,4),(102,15,5),(102,16,6),
(102,17,7),(102,18,8),(102,19,9),(102,20,10),(102,21,11),(102,22,12),(102,23,13),(102,24,14),(102,25,15),(102,26,16),(102,27,17),(102,28,18),
(102,29,19),(102,30,20),(102,31,21),(102,32,22),(102,33,23),(102,34,24),(102,35,25),(102,36,26),(102,37,27),(102,38,28),(102,39,29),(102,40,30),
(102,41,31),(102,42,32),(102,43,33),(102,44,34),(102,45,35),(102,46,36),(102,47,37),(102,48,38),(102,49,39),(102,50,40),(102,51,41),(102,52,42),
(102,53,43),(102,54,44),(102,55,45),(102,56,46),(102,57,47),(102,67,48),(102,68,49),(102,71,50),(102,72,51),(102,73,52),(102,74,53),(102,78,54),
(102,79,55),(102,80,56),(102,81,57),(102,82,58),(102,83,59),(102,84,60),(102,85,61),(102,86,62),(102,87,63),(102,88,64),(102,92,65),(102,93,66),
(102,94,67),(102,95,68),(103,90,1),(103,91,2),(104,100,1),(104,101,2),(104,102,3),(104,103,4),(105,151,1),(105,152,2),(106,8001,1),(106,8002,2),
(106,8003,3),(106,8004,4),(106,8005,5),(107,201,1),(107,202,2),(107,203,3),(107,204,4),(108,301,1),(108,302,2),(108,303,3),(109,351,1),(109,352,2),
(109,353,3),(109,354,4),(109,355,5),(109,356,6),(109,357,7),(109,358,8),(109,359,9),(109,360,10),(109,361,11),(109,362,12),(110,221,1),(20060,50621,1),
(20062,50623,1),(20063,50624,1),(20064,50625,1),(20065,50626,1),(20066,50627,1),(20067,50628,1),(20068,50629,1),(20069,50630,1),(20070,50631,1),(20071,50632,1),(20072,50633,1);
INSERT IGNORE INTO world.crafting_window (window_id, recipe_id, sort_order)
SELECT t.window_id, t.recipe_id, t.sort_order FROM world.tmp_crafting_window t
 WHERE NOT EXISTS (SELECT 1 FROM player.web_m2p_contract_state WHERE name = 'crafting_window_seeded');
INSERT IGNORE INTO player.web_m2p_contract_state (name, value) VALUES ('crafting_window_seeded', 1);
DROP TEMPORARY TABLE world.tmp_crafting_window;
INSERT IGNORE INTO world.crafting_window_name (window_id, name) VALUES
(101,'crafting_blacksmith'),
(102,'crafting_baekgo'),
(103,'crafting_chef'),
(104,'crafting_halfdemon'),
(105,'crafting_horseman'),
(106,'crafting_arrow'),
(107,'crafting_black_steel'),
(108,'crafting_nakajima'),
(109,'crafting_alchemist_ore'),
(110,'crafting_bum'),
(20060,'npc_20060'),
(20062,'npc_20062'),
(20063,'npc_20063'),
(20064,'npc_20064'),
(20065,'npc_20065'),
(20066,'npc_20066'),
(20067,'npc_20067'),
(20068,'npc_20068'),
(20069,'npc_20069'),
(20070,'npc_20070'),
(20071,'npc_20071'),
(20072,'npc_20072');
