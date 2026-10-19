-- The Herbalist's Workshop (Said / saido_0, 17 October; zielarz.quest,
-- docs/notes/gathering.md): Baek-Go's crafting window 111 and its 27 recipes,
-- 401-427, gated by the Herbalist Rank. A row's recipe_vnum is 400 - no scroll
-- teaches 400; the quest writes the rank as the flag crafting.progress_400 - so
-- its req_progress is the rank it needs. Run by apply.sh on every start, after
-- crafting_windows.sql (whose tables it fills); mt2009 only.
--
-- A recipe is added only where its number is free (INSERT IGNORE): a row the
-- operator changed in the panel stays as it is. The window's rows are written
-- once (web_m2p_contract_state 'zielarz_window_seeded'), like the package's
-- windows, so a window the operator reordered or emptied stays so; its name
-- makes m2_crafting_windows.lua own window 111 either way. The bots craft
-- nothing here (playerbot_herbalism.h knows window 102's rows only).
INSERT IGNORE INTO world.crafting_proto (vnum, item_vnum, count, price, chance, recipe, req_progress, req_level, recipe_vnum, comment) VALUES
(401, 50736, 3, 3000, 80, '50901,1,50724,15,50723,10', 1, 20, 400, 'zielarz rank 1: Cave Mushroom'),
(402, 50733, 3, 3000, 80, '50901,1,50721,15,50722,10', 1, 20, 400, 'zielarz rank 1: Amber Petal'),
(409, 50908, 1, 30000, 100, '50901,1,50721,10,50722,10,50733,5', 1, 20, 400, 'zielarz rank 1: Herbalist''s Marble'),
(403, 50735, 3, 6000, 75, '50902,1,50724,15,50725,10', 2, 35, 400, 'zielarz rank 2: Snake Root'),
(404, 50734, 3, 6000, 75, '50902,1,50726,15,50723,10', 2, 35, 400, 'zielarz rank 2: Pearl Panicles'),
(405, 50732, 3, 6000, 75, '50902,1,50725,15,50722,10', 2, 35, 400, 'zielarz rank 2: Snowflower'),
(410, 50940, 1, 50000, 100, '50901,1,30360,5,50721,10', 2, 35, 400, 'zielarz rank 2: Recipe: Sun Elixir (S)'),
(411, 50941, 1, 100000, 100, '50901,1,30360,5,50722,10', 2, 35, 400, 'zielarz rank 2: Recipe: Moon Elixir (S)'),
(406, 50731, 3, 8000, 70, '50902,1,50728,12,50727,8', 3, 50, 400, 'zielarz rank 3: Night Star'),
(407, 50729, 3, 8000, 70, '50902,1,50727,12,50726,8', 3, 50, 400, 'zielarz rank 3: Dandelion'),
(408, 50730, 3, 8000, 70, '50902,1,50728,12,50725,8', 3, 50, 400, 'zielarz rank 3: Thistle'),
(412, 50944, 1, 150000, 100, '50902,1,30360,10,50726,10', 3, 50, 400, 'zielarz rank 3: Recipe: Sun Elixir (M)'),
(413, 50945, 1, 300000, 100, '50902,1,30360,10,50725,10', 3, 50, 400, 'zielarz rank 3: Recipe: Moon Elixir (M)'),
(414, 50946, 1, 350000, 100, '50903,1,30360,15,50729,10', 4, 65, 400, 'zielarz rank 4: Recipe: Sun Elixir (L)'),
(415, 50947, 1, 700000, 100, '50903,1,30360,15,50728,10', 4, 65, 400, 'zielarz rank 4: Recipe: Moon Elixir (L)'),
(416, 51748, 5, 140000, 70, '50903,8,51747,8,30357,2,50727,8', 4, 65, 400, 'zielarz rank 4: Crimson Potion'),
(417, 51753, 5, 140000, 70, '50903,8,51752,8,30344,1,50729,8', 4, 65, 400, 'zielarz rank 4: Grey Potion'),
(418, 51702, 5, 70000, 70, '50903,5,51701,8,30379,1,30358,1', 5, 80, 400, 'zielarz rank 5: Orange Dew'),
(419, 51707, 5, 70000, 70, '50903,5,51706,8,30379,1,30347,1', 5, 80, 400, 'zielarz rank 5: Yellow Dew'),
(420, 51712, 5, 70000, 70, '50903,5,51711,8,30379,1,30351,1', 5, 80, 400, 'zielarz rank 5: Cyan Dew'),
(421, 51717, 5, 70000, 70, '50903,5,51716,8,30379,1,30356,1', 5, 80, 400, 'zielarz rank 5: Blue Dew'),
(422, 51722, 5, 70000, 70, '50903,5,51721,8,30357,1', 5, 80, 400, 'zielarz rank 5: Green Dew'),
(423, 51727, 5, 70000, 70, '50903,5,51726,8,30345,1', 5, 80, 400, 'zielarz rank 5: Platinum Dew'),
(424, 51737, 5, 70000, 70, '50903,5,51736,8,30379,1,30349,1,50729,8', 5, 80, 400, 'zielarz rank 5: Red Dew'),
(425, 51742, 5, 70000, 65, '50903,5,51741,8,50733,4,30346,1', 5, 80, 400, 'zielarz rank 5: Purple Dew'),
(426, 51747, 5, 70000, 80, '50903,5,51746,8,30348,1,50734,4', 5, 80, 400, 'zielarz rank 5: Crimson Dew'),
(427, 51752, 5, 70000, 80, '50903,5,51751,8,30355,1,50732,4', 5, 80, 400, 'zielarz rank 5: White Dew');
CREATE TEMPORARY TABLE world.tmp_zielarz_window (
 window_id INT UNSIGNED NOT NULL, recipe_id INT UNSIGNED NOT NULL, sort_order INT UNSIGNED NOT NULL
);
INSERT INTO world.tmp_zielarz_window (window_id, recipe_id, sort_order) VALUES
(111, 401, 1),(111, 402, 2),(111, 409, 3),(111, 403, 4),(111, 404, 5),(111, 405, 6),(111, 410, 7),(111, 411, 8),(111, 406, 9),(111, 407, 10),(111, 408, 11),(111, 412, 12),(111, 413, 13),(111, 414, 14),(111, 415, 15),(111, 416, 16),(111, 417, 17),(111, 418, 18),(111, 419, 19),(111, 420, 20),(111, 421, 21),(111, 422, 22),(111, 423, 23),(111, 424, 24),(111, 425, 25),(111, 426, 26),(111, 427, 27);
INSERT IGNORE INTO world.crafting_window (window_id, recipe_id, sort_order)
SELECT t.window_id, t.recipe_id, t.sort_order FROM world.tmp_zielarz_window t
 WHERE NOT EXISTS (SELECT 1 FROM player.web_m2p_contract_state WHERE name = 'zielarz_window_seeded');
INSERT IGNORE INTO player.web_m2p_contract_state (name, value) VALUES ('zielarz_window_seeded', 1);
DROP TEMPORARY TABLE world.tmp_zielarz_window;
INSERT IGNORE INTO world.crafting_window_name (window_id, name) VALUES (111, 'crafting_zielarz');
