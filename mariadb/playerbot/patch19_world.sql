-- Iwakura x Tyrion Patch 19, points 1J and 5: the world's own item rows, as
-- the db core reads them at boot (PROTO_FROM_DB = 1: world.item_proto, not a
-- txt). mt2009 only; apply.sh runs it after patch18_contracts.sql (whose
-- web_m2p_contract_state it marks) and before any core loads an item.
-- Idempotent: every start runs it, and nothing changes twice.
USE player;
CREATE TABLE IF NOT EXISTS web_m2p_proto_migration_old (
 migration VARCHAR(32) NOT NULL, vnum INT UNSIGNED NOT NULL, field VARCHAR(16) NOT NULL,
 old_value BIGINT NOT NULL, new_value BIGINT NOT NULL, at DATETIME NOT NULL,
 PRIMARY KEY (migration, vnum, field)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
DELIMITER //
-- 1J: 25040 and 25041 (Zwoj Blogoslawienstwa) fail a grade down: value0 0,
-- once, with the old value kept; 25042 (Magiczny Kamien, value0 1, no loss)
-- is not touched. The marker keeps a later choice of the operator's.
CREATE OR REPLACE PROCEDURE pb19_scroll_value0()
main: BEGIN
 DECLARE done BIGINT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
 START TRANSACTION;
 INSERT IGNORE INTO web_m2p_contract_state(name, value) VALUES('scroll_value0_patch19', 0);
 SELECT value INTO done FROM web_m2p_contract_state WHERE name = 'scroll_value0_patch19' FOR UPDATE;
 IF done = 19 THEN COMMIT; LEAVE main; END IF;
 INSERT IGNORE INTO web_m2p_proto_migration_old(migration, vnum, field, old_value, new_value, at)
  SELECT 'scroll_value0_19', vnum, 'value0', value0, 0, NOW() FROM world.item_proto
  WHERE vnum IN (25040, 25041) AND value0 <> 0;
 UPDATE world.item_proto SET value0 = 0 WHERE vnum IN (25040, 25041) AND value0 <> 0;
 UPDATE web_m2p_contract_state SET value = 19, updated_at = NOW() WHERE name = 'scroll_value0_patch19';
 COMMIT;
END//
-- 5: Cor Draconis (surowe) is the Alchemist's 50255 and stacks to a hundred
-- at least. The package row carries ANTI_STACK (32768), which kept every
-- piece in a cell of its own; it goes, STACKABLE (4) is set and a stack
-- under a hundred is raised (200 stays). Its old values are kept once. The
-- three other rows of that name (50260, 51501, 51502) nothing in this world
-- drops; a bag's or a box's piece of one becomes a 50255, and a socket a
-- raw Cor Draconis carries (nothing writes one) is cleared, so every pile
-- merges. An offline shop's line keeps its row (its ikashop_data names it);
-- the core converts a bag's at the login (NormalizePlayerBotCorDraconis).
CREATE OR REPLACE PROCEDURE pb19_cor_draconis()
main: BEGIN
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
 START TRANSACTION;
 INSERT IGNORE INTO web_m2p_proto_migration_old(migration, vnum, field, old_value, new_value, at)
  SELECT 'cor_draconis_19', vnum, 'antiflag', antiflag, antiflag & ~32768, NOW() FROM world.item_proto
  WHERE vnum = 50255 AND (antiflag & 32768) <> 0;
 INSERT IGNORE INTO web_m2p_proto_migration_old(migration, vnum, field, old_value, new_value, at)
  SELECT 'cor_draconis_19', vnum, 'stack', stack, 100, NOW() FROM world.item_proto
  WHERE vnum = 50255 AND stack < 100;
 UPDATE world.item_proto SET antiflag = antiflag & ~32768, flag = flag | 4, stack = GREATEST(stack, 100)
  WHERE vnum = 50255 AND ((antiflag & 32768) <> 0 OR (flag & 4) = 0 OR stack < 100);
 UPDATE item SET vnum = 50255
  WHERE vnum IN (50260, 51501, 51502) AND `window` IN ('INVENTORY', 'SAFEBOX', 'MALL')
  AND EXISTS (SELECT 1 FROM world.item_proto WHERE vnum = 50255);
 UPDATE item SET socket0 = 0, socket1 = 0, socket2 = 0
  WHERE vnum = 50255 AND `window` IN ('INVENTORY', 'SAFEBOX', 'MALL')
  AND (socket0 <> 0 OR socket1 <> 0 OR socket2 <> 0);
 COMMIT;
END//
DELIMITER ;
CALL pb19_scroll_value0();
CALL pb19_cor_draconis();
-- What the scroll migration found, for the migrator's log.
SELECT CONCAT('patch19 scroll value0: vnum=', vnum, ' old=', old_value, ' new=', new_value, ' at=', at)
 FROM web_m2p_proto_migration_old WHERE migration = 'scroll_value0_19' ORDER BY vnum;
