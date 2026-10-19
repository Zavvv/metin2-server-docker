-- The GM's quest skip (Kiciamol, 15-16 October): F9's "Misje" page, the
-- target board's "Misje" button and the panel's "Misje graczy" read a
-- character's saved quests and queue a completion with its reward
-- (player.web_quest_admin_actions); the character's own timer carries it out
-- (gm_quest_full_skip.lua replaces the resolution and the effects).
--
-- Loaded after gm_quest_catalog.lua. Character changes occur exclusively in
-- the target's PLAYER timer. Server timers only read/write the action table.
--
-- Ours over his package: a bot of the population and a player's companion
-- get nothing from it (Tieru: no bot gets anything for free) - the queue
-- refuses a registered bot's PID and a bot's descriptor never runs the timer
-- (gm_quest_admin.quest) - and what a character reads is in its language.
gm_quest_admin_lib = {cache={}, cursor=0, cooldown={}, previews={}}
local M = gm_quest_admin_lib
local C = gm_quest_catalog
M.scan = string.gmatch or string.gfind

function M.t(pl, en)
    if pc.getf("playerbot_lang", "en") == 1 then
        return playerbot_quest_text ~= nil and playerbot_quest_text(en) or en
    end
    return pl
end
function M.is_bot()
    return pc.is_playerbot ~= nil and pc.is_playerbot()
end
-- A registered identity of the seed: a bot of the population or a companion.
function M.is_bot_pid(pid)
    local rows=M.query("SELECT pid FROM common.playerbot_seed_state WHERE pid="..pid.." LIMIT 1")
    return rows[1] ~= nil
end

function M.query(sql)
    local a,b = mysql_direct_query(sql)
    if type(a)=="table" then return a,0 end
    return type(b)=="table" and b or {}, tonumber(a) or 0
end
function M.hex(s)
    return (string.gsub(tostring(s),'.',function(c) return string.format('%02x',string.byte(c)) end))
end
function M.literal(s) return "X'"..M.hex(s).."'" end
function M.integer(s,lo,hi)
    local n=tonumber(s)
    if n and n==math.floor(n) and n>=lo and n<=hi then return n end
end
function M.state_name(key,value)
    if C[key] then
        for name,n in pairs(C[key].states) do if n==value then return name end end
    end
    return tostring(value)
end
function M.allowed(key,value)
    local c=C[key]
    if not c or not c.adapter then return false end
    for _,name in ipairs(c.adapter.active) do if c.states[name]==value then return true end end
    return false
end
function M.finish(id,status,message,release)
    M.query("UPDATE player.web_quest_admin_actions SET status="..M.literal(status)..
        ",result="..M.literal(message)..",finished_at=NOW()"..
        (release and ",active_key=NULL" or "").." WHERE id="..id.." AND status='applying'")
end
function M.poll()
    -- All cores may see the same pending rows; the conditional SQL claim in
    -- the target's timer is atomic. Bounded circular paging avoids starvation.
    M.query("UPDATE player.web_quest_admin_actions SET status='expired',result='player_offline_or_busy',active_key=NULL,finished_at=NOW() WHERE status='pending' AND expires_at<NOW()")
    -- Never retry an action whose execution might have been interrupted.
    M.query("UPDATE player.web_quest_admin_actions SET status='uncertain',result='manual_review_required',finished_at=NOW() WHERE status='applying' AND created_at<DATE_SUB(NOW(),INTERVAL 10 MINUTE)")
    local rows=M.query("SELECT id,player_id FROM player.web_quest_admin_actions WHERE status='pending' AND id>"..M.cursor.." ORDER BY id LIMIT 32")
    for pid,r in pairs(M.cache) do if r.until_time<get_time() then M.cache[pid]=nil end end
    if table.getn(rows)==0 then M.cursor=0; return end
    for _,r in ipairs(rows) do
        local id=tonumber(r.id);local pid=tonumber(r.player_id)
        if id and pid then
            if not M.cache[pid] or M.cache[pid].id>=id then M.cache[pid]={id=id,until_time=get_time()+30} end
            M.cursor=id
        end
    end
end
function M.cache_next(pid)
    local rows=M.query("SELECT id FROM player.web_quest_admin_actions WHERE player_id="..pid.." AND status='pending' AND expires_at>=NOW() ORDER BY id LIMIT 1")
    if rows[1] then M.cache[pid]={id=tonumber(rows[1].id),until_time=get_time()+30} end
end
function M.reward_row(pid,key)
    local a=C[key].adapter
    if a.reward=="" then return {reward_signature="bio1:"..key} end
    local field="CASE MOD(p.job,4) WHEN 0 THEN r.warrior_items WHEN 1 THEN r.assassin_items WHEN 2 THEN r.sura_items ELSE r.shaman_items END"
    local rows=M.query("SELECT r.exp,r.gold,r.alignment,CAST(r.items AS CHAR) AS items,CAST("..field.." AS CHAR) AS class_items,MD5(CONCAT_WS('|',r.exp,r.gold,r.alignment,COALESCE(r.items,''),COALESCE("..field..",''))) AS reward_signature FROM world.quest_reward_proto r JOIN player.player p ON p.id="..pid.." WHERE quest_name="..M.literal(a.reward))
    return rows[1]
end
function M.definition_matches(rd,r)
    if tonumber(rd[1])~=tonumber(r.exp) or tonumber(rd[2])~=tonumber(r.gold) or tonumber(rd[3])~=tonumber(r.alignment) then return false end
    local index=4
    for _,field in ipairs({r.items,r.class_items}) do
        local tokens={}
        for part in M.scan(tostring(field or ""),'[^,]+') do table.insert(tokens,(string.gsub(part,'^%s*(.-)%s*$','%1'))) end
        if math.mod(table.getn(tokens),2)~=0 then return false end
        for i=1,table.getn(tokens),2 do
            local special=string.sub(tokens[i],1,1)=="s"
            local vnum=tonumber(special and string.sub(tokens[i],2) or tokens[i])
            if tonumber(rd[index])~=vnum or tonumber(rd[index+1])~=tonumber(tokens[i+1]) or (rd[index+2]==true or rd[index+2]==1)~=special then return false end
            index=index+3
        end
    end
    return index==table.getn(rd)+1
end
function M.prepare(key,signature)
    local a=C[key].adapter
    if a.biologist and pc.getf(key,"sk_reward_paid")~=0 then return nil,"biologist_already_paid" end
    local definition=M.reward_row(pc.get_player_id(),key)
    if not definition or definition.reward_signature~=signature then return nil,"reward_changed_refresh" end
    local plan={exp=0,gold=0,alignment=0,items={}}
    if a.reward~="" then
        local rd={get_quest_reward_data(a.reward)}
        if not M.definition_matches(rd,definition) then return nil,"reward_cache_mismatch_reload" end
        if table.getn(rd)<3 or math.mod(table.getn(rd)-3,3)~=0 then return nil,"reward_definition_missing" end
        plan.exp=tonumber(rd[1]);plan.gold=tonumber(rd[2]);plan.alignment=tonumber(rd[3])
        if not plan.exp or plan.exp<0 or not plan.gold or plan.gold<0 or not plan.alignment then return nil,"reward_definition_invalid" end
        for i=4,table.getn(rd),3 do
            local v,n=tonumber(rd[i]),tonumber(rd[i+1])
            if rd[i+2]==true or rd[i+2]==1 then v,n=get_item_drop_info_from_special_group(v) end
            if not v or v<1 or not n or n<1 or n>200 or n~=math.floor(n) then return nil,"reward_item_invalid" end
            table.insert(plan.items,{v,n})
        end
    end
    if a.fixed_item and a.fixed_item>0 then table.insert(plan.items,{a.fixed_item,1}) end
    if pc.get_gold()+plan.gold>=2000000000 then return nil,"yang_limit" end
    local cells=0;local tall=0
    for _,it in ipairs(plan.items) do
        local size=gm_quest_item_sizes[it[1]]
        if not size or size<1 or size>3 then return nil,"item_size_unknown" end
        if not pc.enough_inventory(it[1]) then return nil,"inventory_full" end
        cells=cells+size
        if size>1 then tall=tall+1 end
        it[3]=size
    end
    -- Multiple tall items need a real inventory reservation API. Refuse before
    -- touching the character rather than risk dropping a reward on the ground.
    if tall>1 then return nil,"multiple_tall_rewards_need_review" end
    if pc.get_empty_inventory_count()<cells then return nil,"inventory_full" end
    table.sort(plan.items,function(x,y) return x[3]>y[3] end)
    return plan
end
function M.execute(row,plan)
    local key=row.quest_name;local a=C[key].adapter
    -- Durable SQL claim is already held. Mark this character too. The SQL
    -- record survives a core crash and prevents every automatic retry.
    pc.setf(key,"qa_reward_id",tonumber(row.id))
    set_quest_state(key,a.terminal)
    for _,it in ipairs(plan.items) do
        local before=pc.count_item(it[1])
        pc.give_item2(it[1],it[2],0)
        if pc.count_item(it[1])<before+it[2] then error("reward_item_not_in_inventory") end
    end
    if plan.exp>0 then pc.give_exp2(plan.exp) end
    if plan.gold>0 then pc.change_money(plan.gold) end
    if plan.alignment~=0 then pc.change_alignment(plan.alignment) end
    if a.biologist then
        -- Early herb quests use the native reward table, without dialogues.
        -- Later quests also have permanent affects in the official helper.
        if a.reward=="" then
            -- Item has already been granted and checked above. Apply precisely
            -- the official affects, without granting the helper's item twice.
            local affects=gm_quest_biologist_affects[key]
            if not affects then error("biologist_affects_missing") end
            for _,v in ipairs(affects) do
                if v[3] then affect.add_collect(v[1],v[2],v[3]) else affect.add_collect(v[1],v[2]) end
            end
        end
        pc.setf(key,"sk_reward_paid",1)
    end
    for _,v in ipairs(a.remove) do
        local count=math.min(pc.count_item(v[1]),v[2])
        if count>0 then pc.remove_item(v[1],count) end
    end
    for _,v in ipairs(a.flags) do pc.setf(key,v[1],v[2]) end
    for _,v in ipairs(a.follow) do
        -- Never regress an already-started/finished next quest.
        if pc.getf(v[1],"__status")==0 then set_quest_state(v[1],v[2]) end
    end
    local result="EXP="..plan.exp.."; Yang="..plan.gold.."; ranga="..plan.alignment.."; items="
    for _,it in ipairs(plan.items) do result=result..it[1].."x"..it[2].."/" end
    if a.biologist then result=result.."; biolog="..key end
    M.finish(row.id,"done",string.sub(result,1,200),false)
    syschat(M.t("GM zakonczyl misje z nagroda: ","A GM completed a quest with its reward: ")..C[key].label..
        M.t(". W razie starego wpisu na liscie misji przeloguj postac.",". If the quest list still shows it, log in again."))
end
function M.apply_pending()
    local pid=pc.get_player_id();local hint=M.cache[pid]
    if not hint then return end
    if M.is_bot() then M.cache[pid]=nil;return end
    if hint.until_time<get_time() then M.cache[pid]=nil;return end
    if pc.is_busy() or pc.is_dead() then return end
    M.cache[pid]=nil
    M.run_action(hint.id,pid,{})
    M.cache_next(pid)
end
-- Iwakura's Patch 20, 4J: a bot's action, fired by its core once
-- (qa_bot.timer) with the action's id in the bot's own flags; only a row the
-- panel queued for a bot (source 'panel_bot'). An EXP-blocked bot's lock holds
-- (bot_noexp, set by the core from AFFECT_EXP_BLOCK): no experience is given.
function M.apply_bot()
    if not M.is_bot() then return end
    local id=pc.getf("gm_quest_admin","bot_action");local noexp=pc.getf("gm_quest_admin","bot_noexp")==1
    pc.setf("gm_quest_admin","bot_action",0);pc.setf("gm_quest_admin","bot_noexp",0)
    if not id or id<=0 then return end
    M.run_action(id,pc.get_player_id(),{bot=true,noexp=noexp})
end
-- A completion written down where the operator reads the world's log.
function M.log_done(row,pid)
    M.query("INSERT INTO log.log (`type`,`time`,`who`,`x`,`y`,`what`,`how`,`hint`,`ip`) VALUES('CHARACTER',NOW(),"..pid..
        ",0,0,"..tonumber(row.id)..",'QUEST_ADMIN_DONE',"..M.literal(string.sub("quest="..tostring(row.quest_name)..
        " by="..tostring(row.requester).." src="..tostring(row.source),1,250))..",'')")
end
function M.run_action(id,pid,opts)
    local rows=M.query("SELECT * FROM player.web_quest_admin_actions WHERE id="..id.." AND player_id="..pid.." AND status='pending' AND expires_at>=NOW()")
    if not rows[1] then return end
    local row=rows[1];local key=row.quest_name;local expected=tonumber(row.expected_state)
    if (opts.bot==true)~=(row.source=="panel_bot") then return end
    local config=M.query("SELECT enabled FROM player.web_quest_admin_config WHERE id=1")
    if not config[1] or tonumber(config[1].enabled)~=1 then return end
    -- Revalidate the actual in-memory character on its own core/channel.
    local rejection=nil
    -- Patch 20, 4J: never a GM's character, never inside an instance.
    if pc.is_gm() then rejection="gm_character" end
    if not rejection and pc.get_map_index()>=10000 then rejection="in_instance" end
    if not rejection and opts.bot and (pc.is_busy() or pc.is_dead()) then rejection="busy" end
    if not rejection and not M.allowed(key,expected) then rejection="unsupported_or_inactive" end
    if not rejection and pc.getf(key,"__status")~=expected then rejection="state_changed_refresh" end
    local f=C[key] and C[key].full_skip
    local repeatable=f and (f.cycle_flag or f.cycle_context)
    if not rejection and not repeatable and pc.getf(key,"qa_reward_id")~=0 then rejection="already_rewarded" end
    local plan,reason=nil,nil
    if not rejection then plan,reason=M.prepare(key,row.reward_signature,row);rejection=reason end
    if plan and opts.noexp then plan.exp=0 end
    local _,affected=M.query("UPDATE player.web_quest_admin_actions SET status='applying',claim=UUID() WHERE id="..id.." AND status='pending' AND expires_at>=NOW()")
    if affected~=1 then return end
    if rejection then M.finish(id,"rejected",rejection,true);return end
    local ok,err=pcall(M.execute,row,plan)
    if not ok then
        -- Could be a partial reward. Never release active_key or replay it.
        M.finish(id,"uncertain",string.sub(tostring(err),1,160),false)
    else
        M.log_done(row,pid)
    end
end
function M.send(nonce,kind,payload)
    cmdchat("GMQuest "..nonce.." "..kind.." "..payload)
end
function M.command(args)
    -- UI visibility is not authorization; every request checks the server GM.
    if not pc.is_gm() then return end
    local nonce=tostring(args[2] or "")
    if not string.find(nonce,'^%d+$') or string.len(nonce)>16 then return end
    local me=pc.get_player_id();local now=get_time()
    local quota=M.cooldown[me]
    if not quota or quota.until_time<=now then quota={until_time=now+10,count=0};M.cooldown[me]=quota end
    quota.count=quota.count+1
    if quota.count>30 then M.send(nonce,"error","rate_limit");return end
    local cmd=args[1]
    if cmd=="list" then
        local name=args[3] or "";local page=M.integer(args[4],0,10000);local mode=args[5]
        if string.len(name)<2 or string.len(name)>24 or not page or (mode~="active" and mode~="all") then M.send(nonce,"error","invalid_request");return end
        local players=M.query("SELECT id,name FROM player.player WHERE name="..M.literal(name).." LIMIT 1")
        if not players[1] then M.send(nonce,"error","player_not_found");return end
        local pid=tonumber(players[1].id)
        local flags=M.query("SELECT szName,szState,lValue FROM player.quest WHERE dwPID="..pid.." ORDER BY szName,szState LIMIT 5000")
        local saved={}
        for _,f in ipairs(flags) do
            local key=f.szName
            if not saved[key] then saved[key]={value=0,flags={}} end
            table.insert(saved[key].flags,tostring(f.szState).."="..tostring(f.lValue))
            if f.szState=="__status" then saved[key].value=tonumber(f.lValue) or 0 end
        end
        local keys={}
        for key,_ in pairs(saved) do table.insert(keys,key) end
        table.sort(keys)
        local filtered={}
        for _,key in ipairs(keys) do
            local v=saved[key].value;local qState=M.state_name(key,v)
            local lower=string.gsub(string.gsub(string.lower(qState),'^_+',''),'_+$','')
            if mode=="all" or (v~=0 and lower~='complete' and lower~='giveup' and lower~='cancel') then table.insert(filtered,key) end
        end
        M.send(nonce,"begin",pid.."|"..table.getn(filtered).."|"..page)
        for i=page*7+1,math.min(page*7+7,table.getn(filtered)) do
            local key=filtered[i];local c=C[key];local v=saved[key].value
            M.send(nonce,"row",key.."|"..v.."|"..(M.allowed(key,v) and "1" or "0").."|"..M.hex(c and c.label or key).."|"..M.hex(M.state_name(key,v)))
        end
        M.send(nonce,"end","ok")
    elseif cmd=="detail" then
        local pid=M.integer(args[3],1,4294967295);local key=args[4] or ""
        if not pid or string.len(key)>64 or not string.find(key,'^[%w_]+$') then M.send(nonce,"error","invalid_request");return end
        local c=C[key];local a=c and c.adapter
        M.previews[me]=nil
        local lines={key, a and "Zakonczenie z nagroda dostepne dla aktywnej misji." or "Tylko podglad - misja wymaga osobnej obslugi."}
        if a then
            if a.reward~="" then
                -- Native mysql_direct_query returns TEXT/BLOB as byte arrays;
                -- reward_row deliberately CASTs them to textual fields.
                local r=M.reward_row(pid,key)
                if r then
                    M.previews[me]={pid=pid,key=key,signature=r.reward_signature,until_time=now+300}
                    table.insert(lines,"Nagroda: EXP "..r.exp..", Yang "..r.gold..", ranga "..r.alignment)
                    for _,field in ipairs({r.items,r.class_items}) do
                        local tokens={}
                        for part in M.scan(tostring(field or ""),'[^,]+') do table.insert(tokens,(string.gsub(part,'^%s*(.-)%s*$','%1'))) end
                        for i=1,table.getn(tokens),2 do
                            local v=tokens[i];local count=tokens[i+1] or "?"
                            if string.sub(v,1,1)=="s" then table.insert(lines,"Losowy przedmiot z grupy "..string.sub(v,2).." x"..count)
                            else table.insert(lines,item_name(tonumber(v)).." (#"..v..") x"..count) end
                        end
                    end
                else table.insert(lines,"Brak definicji nagrody - wykonanie bedzie odrzucone.") end
            else
                M.previews[me]={pid=pid,key=key,signature="bio1:"..key,until_time=now+300}
                for _,it in ipairs(gm_quest_biologist_affects[key] or {}) do
                    table.insert(lines,"Staly bonus: "..(gm_quest_point_names[it[1]] or tostring(it[1])).." +"..it[2])
                end
                table.insert(lines,"Szkatulka #"..a.fixed_item.." x1")
            end
        end
        local flags=M.query("SELECT szState,lValue FROM player.quest WHERE dwPID="..pid.." AND szName="..M.literal(key).." ORDER BY szState LIMIT 30")
        local text="Flagi: "
        for _,r in ipairs(flags) do
            local fragment=r.szState.."="..r.lValue.."; "
            if string.len(text)+string.len(fragment)>100 then table.insert(lines,text);text="" end
            text=text..fragment
        end
        if text~="" then table.insert(lines,text) end
        M.send(nonce,"detail_begin","ok")
        for i=1,math.min(table.getn(lines),7) do M.send(nonce,"detail_line",M.hex(string.sub(lines[i],1,170))) end
        M.send(nonce,"detail_line",M.hex("Pelne flagi i historia: panel WWW -> Misje graczy."))
        M.send(nonce,"detail_end","ok")
    elseif cmd=="complete" then
        local pid=M.integer(args[3],1,4294967295);local key=args[4] or "";local qState=M.integer(args[5],-2147483648,2147483647)
        if not pid or not qState or not M.allowed(key,qState) then M.send(nonce,"error","unsupported_or_inactive");return end
        local preview=M.previews[me]
        if not preview or preview.pid~=pid or preview.key~=key or preview.until_time<now then M.send(nonce,"error","reward_preview_required");return end
        local active=pid..":"..key;local token="gm:"..me..":"..nonce
        local conf=M.query("SELECT enabled FROM player.web_quest_admin_config WHERE id=1")
        if not conf[1] or tonumber(conf[1].enabled)~=1 then M.send(nonce,"error","completion_disabled");return end
        M.query("INSERT IGNORE INTO player.web_quest_admin_actions(request_key,active_key,player_id,quest_name,expected_state,reward_signature,requester,source,reason,expires_at) VALUES("..
            M.literal(token)..","..M.literal(active)..","..pid..","..M.literal(key)..","..qState..","..M.literal(preview.signature)..","..M.literal(pc.get_name())..",'f9','GM F9 confirmation',DATE_ADD(NOW(),INTERVAL 2 MINUTE))")
        local rows=M.query("SELECT id,status FROM player.web_quest_admin_actions WHERE active_key="..M.literal(active).." OR request_key="..M.literal(token).." ORDER BY id DESC LIMIT 1")
        if not rows[1] then M.send(nonce,"error","queue_failed");return end
        M.send(nonce,"queued",rows[1].id.."|"..rows[1].status)
    elseif cmd=="status" then
        local id=M.integer(args[3],1,9007199254740991)
        if not id then M.send(nonce,"error","invalid_request");return end
        local rows=M.query("SELECT id,status,result FROM player.web_quest_admin_actions WHERE id="..id)
        if not rows[1] then M.send(nonce,"error","action_not_found");return end
        M.send(nonce,"status",rows[1].id.."|"..rows[1].status.."|"..M.hex(rows[1].result))
    else M.send(nonce,"error","invalid_request") end
end
