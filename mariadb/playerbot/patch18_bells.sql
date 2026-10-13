-- Patch 18: serialise reservations across every channel and kingdom.
USE player;
CREATE TABLE IF NOT EXISTS web_m2p_bell_lock(family INT PRIMARY KEY) ENGINE=InnoDB;
INSERT IGNORE INTO web_m2p_bell_lock VALUES(5030),(5040);
CREATE TABLE IF NOT EXISTS web_m2p_bell_reservation(
 item_id INT UNSIGNED PRIMARY KEY,pid INT UNSIGNED NOT NULL,family INT NOT NULL,
 units INT UNSIGNED NOT NULL,channel INT UNSIGNED NOT NULL,port INT UNSIGNED NOT NULL,
 created_at DATETIME NOT NULL,KEY(family,created_at)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS web_m2p_bell_backup LIKE item;
CREATE TABLE IF NOT EXISTS web_m2p_bell_removal(
 item_id INT UNSIGNED PRIMARY KEY,pid INT UNSIGNED NOT NULL,family INT NOT NULL,units INT NOT NULL,
 channel INT NOT NULL,port INT NOT NULL,claimed_at DATETIME NOT NULL,KEY(family,claimed_at)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS web_m2p_bell_migration(
 item_id INT UNSIGNED PRIMARY KEY,pid INT UNSIGNED NOT NULL,vnum INT UNSIGNED NOT NULL,
 units INT UNSIGNED NOT NULL,value_yang BIGINT NOT NULL DEFAULT 0,reserved TINYINT NULL,
 state VARCHAR(24) NOT NULL DEFAULT 'snapshot',snapshot_at DATETIME NOT NULL,
 checked_at DATETIME NULL,KEY(pid,state)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS web_m2p_bell_status(
 family INT PRIMARY KEY,actual BIGINT NOT NULL,unclassified BIGINT NOT NULL,
 protected BIGINT NOT NULL,ordinary BIGINT NOT NULL,queued BIGINT NOT NULL,
 state VARCHAR(32) NOT NULL,seen_at DATETIME NOT NULL
) ENGINE=InnoDB;
ALTER TABLE web_m2p_bell_migration ADD COLUMN IF NOT EXISTS ready_until DATETIME NULL;
DELIMITER $$
CREATE PROCEDURE IF NOT EXISTS pb18_snapshot_bells()
proc: BEGIN
 DECLARE version BIGINT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 INSERT IGNORE INTO web_m2p_contract_state(name,value) VALUES('bell_snapshot18',0);
 SELECT value INTO version FROM web_m2p_contract_state WHERE name='bell_snapshot18' FOR UPDATE;
 IF version=18 THEN COMMIT;LEAVE proc;END IF;
 INSERT IGNORE INTO web_m2p_bell_backup SELECT i.* FROM item i
  JOIN common.playerbot_seed_state b ON b.pid=i.owner_id AND b.seed_version=1 AND b.state IN ('complete','adopted')
  WHERE i.vnum BETWEEN 5030 AND 5049;
 INSERT IGNORE INTO web_m2p_bell_migration(item_id,pid,vnum,units,snapshot_at)
  SELECT id,owner_id,vnum,`count`,NOW() FROM web_m2p_bell_backup;
 UPDATE web_m2p_contract_state SET value=18,updated_at=NOW() WHERE name='bell_snapshot18';
 COMMIT;
END$$
CREATE OR REPLACE PROCEDURE pb18_reserve_bell(IN it INT UNSIGNED,IN who INT UNSIGNED,
 IN fam INT,IN units INT,IN int_type INT,IN ch INT,IN core_port INT)
proc: BEGIN
 DECLARE locked INT;DECLARE actual BIGINT DEFAULT 0;DECLARE held BIGINT DEFAULT 0;
 DECLARE granted INT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 SELECT family INTO locked FROM web_m2p_bell_lock WHERE family=fam FOR UPDATE;
 IF fam NOT IN (5030,5040) OR units<1 OR units>5 THEN
  ROLLBACK;SELECT 0 AS granted;LEAVE proc;
 END IF;
 -- Once a native line is durably stored, count the offer instead of its
 -- reservation. A restart may release an unexecuted reservation only when
 -- its old core is no longer alive and the item is still outside a shop.
 DELETE r FROM web_m2p_bell_reservation r JOIN item i ON i.id=r.item_id
  JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
  WHERE r.family=fam AND i.`window`='IKASHOP_OFFLINESHOP' AND i.ikashop_data IS NOT NULL AND i.ikashop_data<>'';
 DELETE r FROM web_m2p_bell_reservation r JOIN item i ON i.id=r.item_id
  LEFT JOIN web_m2p_population_runtime c ON c.channel=r.channel AND c.port=r.port
  LEFT JOIN ikashop_offlineshop s ON s.owner=i.owner_id
  WHERE r.family=fam AND (i.`window`<>'IKASHOP_OFFLINESHOP' OR COALESCE(s.duration,0)=0) AND r.created_at<NOW()-INTERVAL 10 MINUTE
  AND (c.channel IS NULL OR c.seen_at<NOW()-INTERVAL 120 SECOND OR c.boot_at>r.created_at);
 SELECT COALESCE(SUM(i.`count`),0) INTO actual FROM item i
  JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
  JOIN common.playerbot_seed_state b ON b.pid=i.owner_id AND b.seed_version=1 AND b.state IN ('complete','adopted')
  WHERE i.vnum BETWEEN fam AND fam+9 AND i.`window`='IKASHOP_OFFLINESHOP'
  AND i.ikashop_data IS NOT NULL AND i.ikashop_data<>''
  AND NOT ((i.attrtype0=int_type AND i.attrvalue0 IN (8,12)) OR (i.attrtype1=int_type AND i.attrvalue1 IN (8,12))
   OR (i.attrtype2=int_type AND i.attrvalue2 IN (8,12)) OR (i.attrtype3=int_type AND i.attrvalue3 IN (8,12))
   OR (i.attrtype4=int_type AND i.attrvalue4 IN (8,12)) OR (i.attrtype5=int_type AND i.attrvalue5 IN (8,12))
   OR (i.attrtype6=int_type AND i.attrvalue6 IN (8,12)));
 SELECT COALESCE(SUM(r.units),0) INTO held FROM web_m2p_bell_reservation r WHERE r.family=fam AND r.item_id<>it;
 IF actual+held+units<=5 THEN
  INSERT INTO web_m2p_bell_reservation VALUES(it,who,fam,units,ch,core_port,NOW())
   ON DUPLICATE KEY UPDATE units=IF(pid=who AND family=fam,VALUES(units),units);
  SELECT COUNT(*) INTO granted FROM web_m2p_bell_reservation r WHERE r.item_id=it AND r.pid=who AND r.family=fam AND r.units=units;
 END IF;
 COMMIT;
 SELECT granted AS granted;
END$$
CREATE OR REPLACE PROCEDURE pb18_pick_bell_excess(IN fam INT,IN who INT UNSIGNED,IN int_type INT,IN ch INT,IN core_port INT)
proc: BEGIN
 DECLARE locked INT;DECLARE actual BIGINT DEFAULT 0;DECLARE queued BIGINT DEFAULT 0;
 DECLARE picked INT UNSIGNED DEFAULT 0;DECLARE picked_owner INT UNSIGNED DEFAULT 0;
 DECLARE picked_units INT DEFAULT 0;DECLARE pending INT DEFAULT 0;
 DECLARE cleanup_version INT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 SELECT family INTO locked FROM web_m2p_bell_lock WHERE family=fam FOR UPDATE;
 IF fam NOT IN (5030,5040) THEN ROLLBACK;SELECT 0 AS item_id;LEAVE proc;END IF;
 DELETE r FROM web_m2p_bell_removal r LEFT JOIN item i ON i.id=r.item_id
  WHERE r.family=fam AND (i.id IS NULL OR i.`window`<>'IKASHOP_OFFLINESHOP' OR i.ikashop_data IS NULL OR i.ikashop_data='');
 DELETE r FROM web_m2p_bell_removal r
  LEFT JOIN web_m2p_population_runtime c ON c.channel=r.channel AND c.port=r.port
  WHERE r.family=fam AND r.claimed_at<NOW()-INTERVAL 10 MINUTE
  AND (c.channel IS NULL OR c.seen_at<NOW()-INTERVAL 120 SECOND OR c.boot_at>r.claimed_at);
 SELECT COALESCE(SUM(i.`count`),0),COALESCE(SUM(m.reserved IS NULL),0) INTO actual,pending
 FROM item i JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
 JOIN common.playerbot_seed_state b ON b.pid=i.owner_id AND b.seed_version=1 AND b.state IN ('complete','adopted')
 LEFT JOIN web_m2p_bell_migration m ON m.item_id=i.id
 WHERE i.vnum BETWEEN fam AND fam+9 AND i.`window`='IKASHOP_OFFLINESHOP'
 AND i.ikashop_data IS NOT NULL AND i.ikashop_data<>''
 AND NOT ((i.attrtype0=int_type AND i.attrvalue0 IN (8,12)) OR (i.attrtype1=int_type AND i.attrvalue1 IN (8,12))
  OR (i.attrtype2=int_type AND i.attrvalue2 IN (8,12)) OR (i.attrtype3=int_type AND i.attrvalue3 IN (8,12))
  OR (i.attrtype4=int_type AND i.attrvalue4 IN (8,12)) OR (i.attrtype5=int_type AND i.attrvalue5 IN (8,12))
  OR (i.attrtype6=int_type AND i.attrvalue6 IN (8,12)));
 SELECT COALESCE(SUM(units),0) INTO queued FROM web_m2p_bell_removal WHERE family=fam;
 SELECT COALESCE(MAX(value),0) INTO cleanup_version FROM web_m2p_contract_state
  WHERE name=CONCAT('bell_cleanup',fam);
 IF cleanup_version=18 THEN COMMIT;SELECT 0 AS item_id;LEAVE proc;END IF;
 IF actual<=5 AND queued=0 AND pending=0 THEN
  INSERT INTO web_m2p_contract_state(name,value) VALUES(CONCAT('bell_cleanup',fam),18)
   ON DUPLICATE KEY UPDATE value=18,updated_at=NOW();
  COMMIT;SELECT 0 AS item_id;LEAVE proc;
 END IF;
 -- An offline/unclassified owner cannot hold up known safe goods. Its
 -- holdings remain untouched and prevent the final completion marker.
 IF actual-queued<=5 THEN COMMIT;SELECT 0 AS item_id;LEAVE proc;END IF;
 SELECT i.id,i.owner_id,i.`count` INTO picked,picked_owner,picked_units
 FROM item i JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
 JOIN web_m2p_bell_migration m ON m.item_id=i.id AND m.pid=i.owner_id AND m.reserved=0 AND m.state='ordinary'
 JOIN common.playerbot_seed_state b ON b.pid=i.owner_id AND b.seed_version=1 AND b.state IN ('complete','adopted')
 LEFT JOIN web_m2p_bell_removal r ON r.item_id=i.id
 WHERE i.vnum BETWEEN fam AND fam+9 AND i.`window`='IKASHOP_OFFLINESHOP' AND r.item_id IS NULL
 AND m.checked_at>=NOW()-INTERVAL 5 MINUTE
 AND m.ready_until>=NOW()
 AND i.ikashop_data IS NOT NULL AND i.ikashop_data<>''
 AND NOT ((i.attrtype0=int_type AND i.attrvalue0 IN (8,12)) OR (i.attrtype1=int_type AND i.attrvalue1 IN (8,12))
  OR (i.attrtype2=int_type AND i.attrvalue2 IN (8,12)) OR (i.attrtype3=int_type AND i.attrvalue3 IN (8,12))
  OR (i.attrtype4=int_type AND i.attrvalue4 IN (8,12)) OR (i.attrtype5=int_type AND i.attrvalue5 IN (8,12))
  OR (i.attrtype6=int_type AND i.attrvalue6 IN (8,12)))
 ORDER BY m.value_yang/GREATEST(i.`count`,1) DESC,m.snapshot_at ASC,i.id ASC LIMIT 1;
 IF picked>0 AND picked_owner=who THEN
  INSERT INTO web_m2p_bell_removal VALUES(picked,who,fam,picked_units,ch,core_port,NOW());
 ELSE SET picked=0;
 END IF;
 COMMIT;SELECT picked AS item_id;
END$$
CREATE OR REPLACE PROCEDURE pb18_next_bell_excess(IN fam INT,IN int_type INT)
proc: BEGIN
 DECLARE locked INT;DECLARE actual BIGINT DEFAULT 0;DECLARE pending BIGINT DEFAULT 0;
 DECLARE protected_units BIGINT DEFAULT 0;DECLARE ordinary_units BIGINT DEFAULT 0;
 DECLARE queued BIGINT DEFAULT 0;DECLARE version INT DEFAULT 0;
 DECLARE picked INT UNSIGNED DEFAULT 0;DECLARE owner_pid INT UNSIGNED DEFAULT 0;
 DECLARE status_name VARCHAR(32) DEFAULT 'waiting';
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 SELECT family INTO locked FROM web_m2p_bell_lock WHERE family=fam FOR UPDATE;
 SELECT COALESCE(SUM(i.`count`),0),COALESCE(SUM(IF(m.reserved IS NULL,i.`count`,0)),0),
  COALESCE(SUM(IF(m.reserved=1,i.`count`,0)),0),COALESCE(SUM(IF(m.reserved=0,i.`count`,0)),0)
 INTO actual,pending,protected_units,ordinary_units
 FROM item i JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
 JOIN common.playerbot_seed_state b ON b.pid=i.owner_id AND b.seed_version=1 AND b.state IN ('complete','adopted')
 LEFT JOIN web_m2p_bell_migration m ON m.item_id=i.id
 WHERE i.vnum BETWEEN fam AND fam+9 AND i.`window`='IKASHOP_OFFLINESHOP'
 AND i.ikashop_data IS NOT NULL AND i.ikashop_data<>''
 AND NOT ((i.attrtype0=int_type AND i.attrvalue0 IN (8,12)) OR (i.attrtype1=int_type AND i.attrvalue1 IN (8,12))
  OR (i.attrtype2=int_type AND i.attrvalue2 IN (8,12)) OR (i.attrtype3=int_type AND i.attrvalue3 IN (8,12))
  OR (i.attrtype4=int_type AND i.attrvalue4 IN (8,12)) OR (i.attrtype5=int_type AND i.attrvalue5 IN (8,12))
  OR (i.attrtype6=int_type AND i.attrvalue6 IN (8,12)));
 DELETE r FROM web_m2p_bell_removal r LEFT JOIN item i ON i.id=r.item_id
  WHERE r.family=fam AND (i.id IS NULL OR i.`window`<>'IKASHOP_OFFLINESHOP' OR i.ikashop_data IS NULL OR i.ikashop_data='');
 DELETE r FROM web_m2p_bell_removal r
  LEFT JOIN web_m2p_population_runtime c ON c.channel=r.channel AND c.port=r.port
  WHERE r.family=fam AND r.claimed_at<NOW()-INTERVAL 10 MINUTE
  AND (c.channel IS NULL OR c.seen_at<NOW()-INTERVAL 120 SECOND OR c.boot_at>r.claimed_at);
 SELECT COALESCE(SUM(units),0) INTO queued FROM web_m2p_bell_removal WHERE family=fam;
 SELECT COALESCE(MAX(value),0) INTO version FROM web_m2p_contract_state WHERE name=CONCAT('bell_cleanup',fam);
 IF version=18 THEN SET status_name=IF(actual<=5,'complete',
  IF(pending=0 AND ordinary_units=0,'complete_protected_exception','post_migration_excess'));
 ELSEIF pending=0 AND queued=0 AND (actual<=5 OR ordinary_units=0) THEN
  -- Protected holdings have precedence over liquidation. A finished pass
  -- records their excess explicitly, rather than claiming a strict five.
  SET status_name=IF(actual>5,'complete_protected_exception','complete');
  INSERT INTO web_m2p_contract_state(name,value) VALUES(CONCAT('bell_cleanup',fam),18)
   ON DUPLICATE KEY UPDATE value=18,updated_at=NOW();
 ELSEIF actual-queued>5 THEN
  SELECT i.id,i.owner_id INTO picked,owner_pid FROM item i
  JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
  JOIN web_m2p_bell_migration m ON m.item_id=i.id AND m.pid=i.owner_id AND m.reserved=0 AND m.state='ordinary'
  JOIN common.playerbot_seed_state b ON b.pid=i.owner_id AND b.seed_version=1 AND b.state IN ('complete','adopted')
  LEFT JOIN web_m2p_bell_removal r ON r.item_id=i.id
  WHERE i.vnum BETWEEN fam AND fam+9 AND i.`window`='IKASHOP_OFFLINESHOP' AND r.item_id IS NULL
  AND m.checked_at>=NOW()-INTERVAL 5 MINUTE
  AND m.ready_until>=NOW()
  AND i.ikashop_data IS NOT NULL AND i.ikashop_data<>''
  AND NOT ((i.attrtype0=int_type AND i.attrvalue0 IN (8,12)) OR (i.attrtype1=int_type AND i.attrvalue1 IN (8,12))
   OR (i.attrtype2=int_type AND i.attrvalue2 IN (8,12)) OR (i.attrtype3=int_type AND i.attrvalue3 IN (8,12))
   OR (i.attrtype4=int_type AND i.attrvalue4 IN (8,12)) OR (i.attrtype5=int_type AND i.attrvalue5 IN (8,12))
   OR (i.attrtype6=int_type AND i.attrvalue6 IN (8,12)))
  ORDER BY m.value_yang/GREATEST(i.`count`,1) DESC,m.snapshot_at ASC,i.id ASC LIMIT 1;
  SET status_name=IF(picked>0,'service_pending',IF(pending>0,'classification_pending','owner_unavailable'));
 ELSE SET status_name=IF(queued>0,'native_ack_pending','classification_pending');
 END IF;
 INSERT INTO web_m2p_bell_status VALUES(fam,actual,pending,protected_units,ordinary_units,queued,status_name,NOW())
  ON DUPLICATE KEY UPDATE actual=VALUES(actual),unclassified=VALUES(unclassified),protected=VALUES(protected),
   ordinary=VALUES(ordinary),queued=VALUES(queued),state=VALUES(state),seen_at=VALUES(seen_at);
 COMMIT;
 SELECT picked AS item_id,owner_pid AS pid,actual,pending AS unclassified,protected_units AS protected,status_name AS state;
END$$
DELIMITER ;
CALL pb18_snapshot_bells();
