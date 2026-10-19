-- Patch 18: serialise reservations across every channel and kingdom.
USE player;
-- One coordinator per world-minute. Actual entry/exit claims share durable
-- fractional budgets, so delayed exits cannot bunch across several cores.
CREATE TABLE IF NOT EXISTS web_m2p_rotation_control(
 singleton TINYINT PRIMARY KEY,planned_min BIGINT UNSIGNED NOT NULL DEFAULT 0,
 step_min BIGINT UNSIGNED NOT NULL DEFAULT 0,step_hour BIGINT UNSIGNED NOT NULL DEFAULT 0,
 target INT UNSIGNED NOT NULL DEFAULT 1,hourly INT UNSIGNED NOT NULL DEFAULT 15,
 op_credit BIGINT UNSIGNED NOT NULL DEFAULT 0,exit_credit BIGINT UNSIGNED NOT NULL DEFAULT 0,
 exchange_token INT UNSIGNED NOT NULL DEFAULT 0,exchange_left INT UNSIGNED NOT NULL DEFAULT 0
) ENGINE=InnoDB;
INSERT IGNORE INTO web_m2p_rotation_control(singleton) VALUES(1);
DELIMITER $$
CREATE OR REPLACE PROCEDURE pb21_rotation_plan(IN stamp INT UNSIGNED,IN wanted INT UNSIGNED,
 IN hourly_pct INT UNSIGNED,IN exchange_stamp INT UNSIGNED)
proc: BEGIN
 DECLARE previous BIGINT UNSIGNED;DECLARE token INT UNSIGNED;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 SELECT planned_min,exchange_token INTO previous,token FROM web_m2p_rotation_control WHERE singleton=1 FOR UPDATE;
 IF previous=FLOOR(stamp/60) THEN COMMIT;SELECT 0 AS granted,0 AS exchange_left;LEAVE proc;END IF;
 UPDATE web_m2p_rotation_control SET planned_min=FLOOR(stamp/60),target=GREATEST(1,wanted),hourly=LEAST(100,hourly_pct) WHERE singleton=1;
 IF token<>exchange_stamp THEN
  UPDATE web_m2p_rotation_control SET exchange_token=exchange_stamp,exchange_left=(
   SELECT FLOOR(COUNT(*)/10) FROM common.playerbot_rotation WHERE selected=1 AND online=1 AND retired=0
  ) WHERE singleton=1;
 END IF;
 COMMIT;
 SELECT 1 AS granted,exchange_left FROM web_m2p_rotation_control WHERE singleton=1;
END$$
CREATE OR REPLACE PROCEDURE pb21_rotation_take(IN who INT UNSIGNED,IN own_core VARCHAR(100),
 IN entering TINYINT UNSIGNED,IN stamp INT UNSIGNED)
proc: BEGIN
 DECLARE previous BIGINT UNSIGNED;DECLARE previous_hour BIGINT UNSIGNED;
 DECLARE goal BIGINT UNSIGNED;DECLARE hourly_pct INT UNSIGNED;
 DECLARE ops BIGINT UNSIGNED;DECLARE exits BIGINT UNSIGNED;DECLARE permitted INT DEFAULT 0;
 DECLARE occupied BIGINT UNSIGNED DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 SELECT step_min,step_hour,target,hourly,op_credit,exit_credit
  INTO previous,previous_hour,goal,hourly_pct,ops,exits FROM web_m2p_rotation_control WHERE singleton=1 FOR UPDATE;
 IF previous=0 THEN SET ops=goal*2;SET exits=goal*hourly_pct;
 ELSE
  IF FLOOR(stamp/60)>previous THEN SET ops=LEAST(GREATEST(100,goal*2),ops+(FLOOR(stamp/60)-previous)*goal*2);END IF;
  IF FLOOR(stamp/3600)>previous_hour THEN SET exits=LEAST(GREATEST(100,goal*hourly_pct),exits+(FLOOR(stamp/3600)-previous_hour)*goal*hourly_pct);END IF;
 END IF;
 SET ops=LEAST(GREATEST(100,goal*2),ops);SET exits=LEAST(GREATEST(100,goal*hourly_pct),exits);
 UPDATE web_m2p_rotation_control SET step_min=FLOOR(stamp/60),step_hour=FLOOR(stamp/3600),op_credit=ops,exit_credit=exits WHERE singleton=1;
 IF ops<100 OR (entering NOT IN (1,3) AND (exits<100 OR hourly_pct=0)) THEN COMMIT;SELECT 0 AS granted;LEAVE proc;END IF;
 IF entering IN (1,3) THEN
  SELECT COUNT(*) INTO occupied FROM common.playerbot_rotation r JOIN common.playerbot_rotation_core c ON c.core=r.core
   WHERE r.pid<>who AND c.seen_at>NOW()-INTERVAL 150 SECOND
   AND (r.online=1 OR r.admitted=2 OR (entering=3 AND r.admitted=1));
  IF occupied>=goal THEN COMMIT;SELECT 0 AS granted;LEAVE proc;END IF;
 END IF;
 IF entering=1 THEN
  UPDATE common.playerbot_rotation SET admitted=2,requested_at=stamp
   WHERE pid=who AND core=own_core AND selected=1 AND retired=0 AND online=0 AND admitted=1;
 ELSEIF entering=3 THEN
  UPDATE common.playerbot_rotation SET admitted=2,requested_at=stamp
   WHERE pid=who AND core=own_core AND selected=0 AND retired=0 AND online=0 AND admitted=0 AND role_hold=1
   AND EXISTS(SELECT 1 FROM player.playerbot_sidekick sk WHERE sk.sidekick_pid=who)
   AND EXISTS(SELECT 1 FROM common.playerbot_rotation_core c WHERE c.core=own_core AND c.seen_at>NOW()-INTERVAL 150 SECOND);
 ELSE
  UPDATE common.playerbot_rotation SET admitted=0,out_request=0
   WHERE pid=who AND core=own_core AND selected=1 AND online=1 AND pin=0 AND role_hold=0
   AND (out_request=1 OR (entering=2 AND retired=1));
 END IF;
 SET permitted=ROW_COUNT();
 IF permitted=1 THEN
  UPDATE web_m2p_rotation_control SET op_credit=op_credit-100,
   exit_credit=exit_credit-IF(entering IN (1,3),0,100),exchange_left=IF(entering IN (1,3),exchange_left,IF(exchange_left>0,exchange_left-1,0)) WHERE singleton=1;
 END IF;
 COMMIT;SELECT permitted AS granted;
END$$
DELIMITER ;
-- Patch 21: reserve pearl *lines* across every core before native removal.
CREATE TABLE IF NOT EXISTS web_m2p_pearl_lock(vnum INT UNSIGNED PRIMARY KEY) ENGINE=InnoDB;
INSERT IGNORE INTO web_m2p_pearl_lock VALUES(27992),(27993),(27994);
CREATE TABLE IF NOT EXISTS web_m2p_pearl_reservation(
 item_id INT UNSIGNED PRIMARY KEY,pid INT UNSIGNED NOT NULL,vnum INT UNSIGNED NOT NULL,
 channel INT UNSIGNED NOT NULL,port INT UNSIGNED NOT NULL,created_at DATETIME NOT NULL,
 KEY kind(vnum,created_at),KEY owner(pid,vnum)
) ENGINE=InnoDB;
DELIMITER $$
CREATE OR REPLACE PROCEDURE pb21_reserve_pearl(IN it INT UNSIGNED,IN who INT UNSIGNED,
 IN kind INT UNSIGNED,IN ch INT UNSIGNED,IN core_port INT UNSIGNED)
proc: BEGIN
 DECLARE locked INT;DECLARE actual INT DEFAULT 0;DECLARE own_lines INT DEFAULT 0;
 DECLARE held INT DEFAULT 0;DECLARE own_held INT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 IF kind NOT IN (27992,27993,27994) THEN ROLLBACK;SELECT 0 AS granted;LEAVE proc;END IF;
 SELECT vnum INTO locked FROM web_m2p_pearl_lock WHERE vnum=kind FOR UPDATE;
 -- Account identity is verified again at this shared write boundary.
 IF NOT EXISTS(SELECT 1 FROM common.playerbot_seed_state l JOIN player p ON p.id=l.pid
  JOIN account.account a ON a.id=p.account_id JOIN player_index pi ON pi.id=a.id
  WHERE l.pid=who AND l.seed_version=1 AND l.state IN ('complete','adopted')
  AND BINARY a.login=BINARY CONCAT('playerbot_',LPAD(l.pid-3,GREATEST(3,LENGTH(l.pid-3)),'0'))
  AND BINARY a.social_id=BINARY CONCAT('9',LPAD(l.pid-3,12,'0'))
  AND pi.pid1=l.pid AND pi.pid2=0 AND pi.pid3=0 AND pi.pid4=0 AND pi.empire IN(1,2,3)) THEN
  ROLLBACK;SELECT 0 AS granted;LEAVE proc;
 END IF;
 DELETE r FROM web_m2p_pearl_reservation r JOIN item i ON i.id=r.item_id
  JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
  WHERE r.vnum=kind AND i.`window`='IKASHOP_OFFLINESHOP';
 -- Uncertain live-core mutations stay reserved. A stopped core's unused
 -- reservation is released only after a delay and an unchanged bag item.
 DELETE r FROM web_m2p_pearl_reservation r JOIN item i ON i.id=r.item_id
  LEFT JOIN web_m2p_population_runtime c ON c.channel=r.channel AND c.port=r.port
  WHERE r.vnum=kind AND i.`window`<>'IKASHOP_OFFLINESHOP'
  AND r.created_at<NOW()-INTERVAL 10 MINUTE
  AND (c.channel IS NULL OR c.seen_at<NOW()-INTERVAL 120 SECOND OR c.boot_at>r.created_at);
 IF EXISTS(SELECT 1 FROM web_m2p_pearl_reservation WHERE item_id=it AND pid=who AND vnum=kind) THEN
  COMMIT;SELECT 1 AS granted;LEAVE proc;
 END IF;
 SELECT COUNT(*),COALESCE(SUM(i.owner_id=who),0) INTO actual,own_lines FROM item i
  JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
  WHERE i.vnum=kind AND i.`window`='IKASHOP_OFFLINESHOP';
 SELECT COUNT(*),COALESCE(SUM(pid=who),0) INTO held,own_held FROM web_m2p_pearl_reservation WHERE vnum=kind;
 IF actual+held>=40 OR own_lines+own_held>=2 THEN ROLLBACK;SELECT 0 AS granted;LEAVE proc;END IF;
 INSERT INTO web_m2p_pearl_reservation VALUES(it,who,kind,ch,core_port,NOW());
 COMMIT;SELECT 1 AS granted;
END$$
DELIMITER ;
CREATE TABLE IF NOT EXISTS web_m2p_retirement_day(day INT UNSIGNED PRIMARY KEY,used INT UNSIGNED NOT NULL DEFAULT 0) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS web_m2p_retirement_claim(pid INT UNSIGNED PRIMARY KEY,started INT UNSIGNED NOT NULL,day INT UNSIGNED NOT NULL) ENGINE=InnoDB;
DELIMITER $$
CREATE OR REPLACE PROCEDURE pb21_retire_claim(IN who INT UNSIGNED,IN population INT UNSIGNED,IN today INT UNSIGNED)
proc: BEGIN
 DECLARE used_count INT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 INSERT IGNORE INTO web_m2p_retirement_day VALUES(today,0);
 SELECT used INTO used_count FROM web_m2p_retirement_day WHERE day=today FOR UPDATE;
 IF EXISTS(SELECT 1 FROM web_m2p_retirement_claim WHERE pid=who) THEN COMMIT;SELECT 1 AS granted;LEAVE proc;END IF;
 IF used_count>=FLOOR(population*0.005) OR NOT EXISTS(
  SELECT 1 FROM common.playerbot_seed_state l JOIN player p ON p.id=l.pid
  JOIN account.account a ON a.id=p.account_id JOIN player_index pi ON pi.id=a.id
  WHERE l.pid=who AND l.seed_version=1 AND l.state IN ('complete','adopted')
  AND BINARY a.login=BINARY CONCAT('playerbot_',LPAD(l.pid-3,GREATEST(3,LENGTH(l.pid-3)),'0'))
  AND BINARY a.social_id=BINARY CONCAT('9',LPAD(l.pid-3,12,'0'))
  AND pi.pid1=l.pid AND pi.pid2=0 AND pi.pid3=0 AND pi.pid4=0 AND pi.empire IN(1,2,3)
  AND NOT EXISTS(SELECT 1 FROM common.playerbot_rotation r WHERE r.pid=who AND (r.pin=1 OR r.role_hold=1))
  AND NOT EXISTS(SELECT 1 FROM player.guild g WHERE g.master=who)
  AND NOT EXISTS(SELECT 1 FROM player.marriage m WHERE (m.pid1=who OR m.pid2=who) AND m.is_married=1)
  AND NOT EXISTS(SELECT 1 FROM player.playerbot_sidekick sk WHERE sk.sidekick_pid=who)
 ) THEN ROLLBACK;SELECT 0 AS granted;LEAVE proc;END IF;
 INSERT INTO web_m2p_retirement_claim VALUES(who,UNIX_TIMESTAMP(NOW()),today);
 UPDATE web_m2p_retirement_day SET used=used+1 WHERE day=today;
 COMMIT;SELECT 1 AS granted;
END$$
DELIMITER ;
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
-- Patch 19, 2D: every claim of a line is an attempt; after three a line that
-- still stands is an error, set aside so the rest goes on.
ALTER TABLE web_m2p_bell_migration ADD COLUMN IF NOT EXISTS attempts INT UNSIGNED NOT NULL DEFAULT 0;
ALTER TABLE web_m2p_bell_status ADD COLUMN IF NOT EXISTS removed BIGINT NOT NULL DEFAULT 0;
ALTER TABLE web_m2p_bell_status ADD COLUMN IF NOT EXISTS errors BIGINT NOT NULL DEFAULT 0;
ALTER TABLE web_m2p_bell_status ADD COLUMN IF NOT EXISTS done TINYINT NOT NULL DEFAULT 0;
-- Patch 19, 1H: a market line the Plan buys a base from, claimed for one bot
-- across every core and channel; free again after five minutes or when the
-- purchase fails (playerbot_patch19_surplus.h; the core makes it too).
CREATE TABLE IF NOT EXISTS web_m2p_offer_claim(
 item_id INT UNSIGNED PRIMARY KEY,pid INT UNSIGNED NOT NULL,
 claimed_at DATETIME NOT NULL,KEY(pid)
) ENGINE=InnoDB;
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
 DECLARE errored BIGINT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 SELECT family INTO locked FROM web_m2p_bell_lock WHERE family=fam FOR UPDATE;
 IF fam NOT IN (5030,5040) THEN ROLLBACK;SELECT 0 AS item_id;LEAVE proc;END IF;
 DELETE r FROM web_m2p_bell_removal r LEFT JOIN item i ON i.id=r.item_id
  WHERE r.family=fam AND (i.id IS NULL OR i.`window`<>'IKASHOP_OFFLINESHOP' OR i.ikashop_data IS NULL OR i.ikashop_data='');
 -- Patch 19, 2D: a claim ten minutes old is a failed attempt whatever its
 -- core (a visit's own deadline is ninety seconds); a live core used to keep
 -- it for ever, and the queued units held the migration short of its end.
 DELETE r FROM web_m2p_bell_removal r
  WHERE r.family=fam AND r.claimed_at<NOW()-INTERVAL 10 MINUTE;
 -- Patch 19, 2D: a line three attempts could not take down is an error,
 -- set aside; the others go on and the end is marked without it.
 UPDATE web_m2p_bell_migration m LEFT JOIN web_m2p_bell_removal r ON r.item_id=m.item_id
  SET m.state='error' WHERE m.vnum BETWEEN fam AND fam+9 AND m.state='ordinary' AND m.attempts>=3 AND r.item_id IS NULL;
 SELECT COALESCE(SUM(i.`count`),0),COALESCE(SUM(m.reserved IS NULL),0),COALESCE(SUM(IF(m.state='error',i.`count`,0)),0)
 INTO actual,pending,errored
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
 IF actual-errored<=5 AND queued=0 AND pending=0 THEN
  INSERT INTO web_m2p_contract_state(name,value) VALUES(CONCAT('bell_cleanup',fam),18)
   ON DUPLICATE KEY UPDATE value=18,updated_at=NOW();
  COMMIT;SELECT 0 AS item_id;LEAVE proc;
 END IF;
 -- An offline/unclassified owner cannot hold up known safe goods. Its
 -- holdings remain untouched and prevent the final completion marker.
 IF actual-queued-errored<=5 THEN COMMIT;SELECT 0 AS item_id;LEAVE proc;END IF;
 SELECT i.id,i.owner_id,i.`count` INTO picked,picked_owner,picked_units
 FROM item i JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
 JOIN web_m2p_bell_migration m ON m.item_id=i.id AND m.pid=i.owner_id AND m.reserved=0 AND m.state='ordinary'
 JOIN common.playerbot_seed_state b ON b.pid=i.owner_id AND b.seed_version=1 AND b.state IN ('complete','adopted')
 LEFT JOIN web_m2p_bell_removal r ON r.item_id=i.id
 WHERE i.vnum BETWEEN fam AND fam+9 AND i.`window`='IKASHOP_OFFLINESHOP' AND r.item_id IS NULL
 AND m.attempts<3
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
  UPDATE web_m2p_bell_migration SET attempts=attempts+1 WHERE item_id=picked;
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
 DECLARE error_units BIGINT DEFAULT 0;DECLARE removed_lines BIGINT DEFAULT 0;
 DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK;RESIGNAL;END;
 START TRANSACTION;
 SELECT family INTO locked FROM web_m2p_bell_lock WHERE family=fam FOR UPDATE;
 DELETE r FROM web_m2p_bell_removal r LEFT JOIN item i ON i.id=r.item_id
  WHERE r.family=fam AND (i.id IS NULL OR i.`window`<>'IKASHOP_OFFLINESHOP' OR i.ikashop_data IS NULL OR i.ikashop_data='');
 -- Patch 19, 2D: a claim ten minutes old is a failed attempt whatever its
 -- core (a visit's own deadline is ninety seconds); a live core used to keep
 -- it for ever, and the queued units held the migration short of its end.
 DELETE r FROM web_m2p_bell_removal r
  WHERE r.family=fam AND r.claimed_at<NOW()-INTERVAL 10 MINUTE;
 -- Patch 19, 2D: three failed attempts set a line aside as an error.
 UPDATE web_m2p_bell_migration m LEFT JOIN web_m2p_bell_removal r ON r.item_id=m.item_id
  SET m.state='error' WHERE m.vnum BETWEEN fam AND fam+9 AND m.state='ordinary' AND m.attempts>=3 AND r.item_id IS NULL;
 SELECT COALESCE(SUM(i.`count`),0),COALESCE(SUM(IF(m.reserved IS NULL,i.`count`,0)),0),
  COALESCE(SUM(IF(m.reserved=1,i.`count`,0)),0),
  COALESCE(SUM(IF(m.reserved=0 AND m.state<>'error',i.`count`,0)),0),
  COALESCE(SUM(IF(m.state='error',i.`count`,0)),0)
 INTO actual,pending,protected_units,ordinary_units,error_units
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
 SELECT COUNT(*) INTO removed_lines FROM web_m2p_bell_migration WHERE vnum BETWEEN fam AND fam+9 AND state='removed';
 SELECT COALESCE(MAX(value),0) INTO version FROM web_m2p_contract_state WHERE name=CONCAT('bell_cleanup',fam);
 IF version=18 THEN SET status_name=IF(error_units>0,'complete_with_errors',IF(actual<=5,'complete',
  IF(pending=0 AND ordinary_units=0,'complete_protected_exception','post_migration_excess')));
 ELSEIF pending=0 AND queued=0 AND (actual-error_units<=5 OR ordinary_units=0) THEN
  -- Protected holdings have precedence over liquidation. A finished pass
  -- records their excess explicitly, rather than claiming a strict five;
  -- a line set aside as an error does not hold the end (Patch 19, 2D).
  SET status_name=IF(error_units>0,'complete_with_errors',IF(actual>5,'complete_protected_exception','complete'));
  INSERT INTO web_m2p_contract_state(name,value) VALUES(CONCAT('bell_cleanup',fam),18)
   ON DUPLICATE KEY UPDATE value=18,updated_at=NOW();
  SET version=18;
 ELSEIF actual-queued-error_units>5 THEN
  SELECT i.id,i.owner_id INTO picked,owner_pid FROM item i
  JOIN ikashop_offlineshop s ON s.owner=i.owner_id AND s.duration>0
  JOIN web_m2p_bell_migration m ON m.item_id=i.id AND m.pid=i.owner_id AND m.reserved=0 AND m.state='ordinary'
  JOIN common.playerbot_seed_state b ON b.pid=i.owner_id AND b.seed_version=1 AND b.state IN ('complete','adopted')
  LEFT JOIN web_m2p_bell_removal r ON r.item_id=i.id
  WHERE i.vnum BETWEEN fam AND fam+9 AND i.`window`='IKASHOP_OFFLINESHOP' AND r.item_id IS NULL
  AND m.attempts<3
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
 INSERT INTO web_m2p_bell_status(family,actual,unclassified,protected,ordinary,queued,state,seen_at,removed,errors,done)
  VALUES(fam,actual,pending,protected_units,ordinary_units,queued,status_name,NOW(),removed_lines,error_units,IF(version=18,1,0))
  ON DUPLICATE KEY UPDATE actual=VALUES(actual),unclassified=VALUES(unclassified),protected=VALUES(protected),
   ordinary=VALUES(ordinary),queued=VALUES(queued),state=VALUES(state),seen_at=VALUES(seen_at),
   removed=VALUES(removed),errors=VALUES(errors),done=VALUES(done);
 COMMIT;
 SELECT picked AS item_id,owner_pid AS pid,actual,pending AS unclassified,protected_units AS protected,status_name AS state;
END$$
DELIMITER ;
CALL pb18_snapshot_bells();
