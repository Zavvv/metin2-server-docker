-- The full skip (Kiciamol, 16 October): every stage's remaining reward, the
-- variants a quest offers (a weapon, the truth or the lie), the repeatable
-- quests' current cycle, and the native unlocks a quest ends in. Lua 5.0.3.
-- Loaded after the original queue helper. No dynamic quest eval.
-- Ours: a registered bot's PID is refused (gm_quest_admin.lua's is_bot_pid),
-- and the GM's and the character's lines are in the reader's language.
local M=gm_quest_admin_lib
local C=gm_quest_catalog
-- The catalog's Polish words a GM reads, with their English.
M.WORDS={
    ["Pelny skip"]="Full skip",["Bron 1"]="Weapon 1",["Bron 2"]="Weapon 2",
    ["Prawda"]="The truth",["Klamstwo"]="The lie",["Sukces"]="Success",
    ["Niepowodzenie"]="Failure",["Yang"]="Yang",["Doswiadczenie"]="Experience",
    ["Zemsta zakonczona"]="Revenge done",["Rezygnacja z zemsty"]="Revenge given up",
    ["Pierwsza profesja"]="First skill group",["Druga profesja"]="Second skill group",
    ["Skrypt systemowy lub nieaktywna definicja; nie ma jednorazowej misji do zakonczenia."]=
        "A system script or an inactive definition; there is no one-time quest to complete.",
    ["Biolog 92 ma w tej dystrybucji pusta definicje (bez zadania i nagrody)."]=
        "The Biologist of 92 has an empty definition here (no task and no reward).",
}
function M.word(pl)
    local en=M.WORDS[pl]
    if not en then
        local _,_,vnum=string.find(tostring(pl),"^Przedmiot #(%d+)$")
        if vnum then en="Item #"..vnum end
    end
    if en then return M.t(pl,en) end
    return pl
end
local function contains(t,value)
    for _,v in ipairs(t or {}) do if v==value then return true end end
    return false
end
local function additems(dst,src)
    for _,v in ipairs(src or {}) do table.insert(dst,{v[1],v[2],v[3] or 0}) end
end
function M.options(key,value,job)
    local c=C[key];local f=c and c.full_skip
    local stage=M.state_name(key,value);local out={}
    if not f or not contains(f.active,stage) then return out end
    for id,p in pairs(f.plans) do
        if (not p.jobs or contains(p.jobs,job)) and (not p.stages or contains(p.stages,stage)) and not contains(p.exclude_stages,stage) then
            table.insert(out,{id,M.word(p.label)})
        end
    end
    table.sort(out,function(a,b)
        if a[1]==b[1] then return false end
        if a[1]==f.default then return true end
        if b[1]==f.default then return false end
        return a[1]<b[1]
    end)
    return out
end
function M.allowed(key,value)
    local c=C[key];local f=c and c.full_skip
    return f and contains(f.active,M.state_name(key,value)) or false
end
function M.resolve(key,value,job,sex,flags,variant,horse_level,other)
    local options=M.options(key,value,job)
    if table.getn(options)==0 then return nil,"unsupported_or_inactive" end
    if not variant or variant=="" then variant=options[1][1] end
    local valid=false;for _,v in ipairs(options) do if v[1]==variant then valid=true end end
    if not valid then return nil,"invalid_reward_choice" end
    local f=C[key].full_skip;local stage=M.state_name(key,value);local s=f.plans[variant]
    local cycle=-1
    if f.cycle_flag then cycle=tonumber(flags[f.cycle_flag]) or 0 end
    if f.cycle_context=="horse" then cycle=horse_level end
    local p={variant=variant,label=s.label,cycle=cycle,spec=s,stage=stage,terminal=s.terminal or f.terminal,
             rewards=s.rewards_by_stage and s.rewards_by_stage[stage] or s.rewards,items={},
             exp=s.exp,gold=s.gold_by_stage and s.gold_by_stage[stage] or s.gold,alignment=s.alignment,context={}}
    additems(p.items,s.items)
    if s.items_by_job then additems(p.items,s.items_by_job[tostring(job)]) end
    if s.items_by_sex and not contains(s.items_sex_paid_states,stage) then additems(p.items,s.items_by_sex[tostring(sex)]) end
    if not contains(s.items_before_paid_states,stage) then for _,v in pairs(s.items_before_stage or {}) do additems(p.items,v) end end
    if not contains(s.items_early_paid_states,stage) then additems(p.items,s.items_early) end
    if key=="hunting" then
        local d=f.hunting_data[cycle+1]
        if not d then return nil,"quest_cycle_finished" end
        p.gold=p.gold+d.gold;p.exp_percent={d.level,d.percent}
        for i=1,table.getn(d.items),2 do
            local v=d.items[i]
            if v=="primary_armor" then v=({11200,11400,11600,11800})[job+1] end
            if v=="primary_helmet" then v=({12200,12340,12480,12620})[job+1] end
            table.insert(p.items,{v,d.items[i+1],0})
        end
    end
    if s.native=="horse" then
        if horse_level~=s.horse_target-1 then return nil,"horse_level_changed" end
        p.horse_target=s.horse_target
    elseif s.native=="horse_training" then
        if horse_level<s.horse_min or horse_level>s.horse_max then return nil,"horse_level_changed" end
        p.horse_target=horse_level+1
    elseif s.native=="quest_book" then
        local index=tonumber(other.quest_book_index) or 0
        if index<=0 then return nil,"quest_cycle_finished" end
        table.insert(p.context,tostring(index));p.book_index=index
    end
    return p
end
function M.flags(pid,key)
    local rows=M.query("SELECT szState,lValue FROM player.quest WHERE dwPID="..pid.." AND szName="..M.literal(key).." ORDER BY szState")
    local out={};for _,r in ipairs(rows) do out[r.szState]=tonumber(r.lValue) or 0 end
    return out
end
function M.native_flags(key)
    local out={}
    -- Only declared fields participate in resolution. No expensive SQL in the
    -- idle player timer; this runs solely for an actual pending GM request.
    local f=C[key].full_skip
    if f.cycle_flag then out[f.cycle_flag]=pc.getf(key,f.cycle_flag) end
    return out
end
function M.preview(pid,key,value,variant,native)
    local flags,job,sex,horse_level,other
    if native then
        flags=M.native_flags(key);job=pc.get_job();sex=pc.get_sex();horse_level=pc.get_horse_level()
        other={quest_book_index=pc.getf("quest_book_manage","quest_index")}
    else
        flags=M.flags(pid,key)
        local rows=M.query("SELECT job,horse_level FROM player.player WHERE id="..pid)
        if not rows[1] then return nil,"player_not_found" end
        local race=tonumber(rows[1].job);job=math.mod(race,4);sex=({0,1,0,1,1,0,1,0})[race+1]
        horse_level=tonumber(rows[1].horse_level) or 0
        local ext=M.flags(pid,"quest_book_manage");other={quest_book_index=ext.quest_index or 0}
    end
    local p,err=M.resolve(key,value,job,sex,flags,variant,horse_level,other)
    if not p then return nil,err end
    local parts={"full2",C[key].full_skip.revision,tostring(value),p.variant,tostring(p.cycle),tostring(job),tostring(sex)}
    for _,v in ipairs(p.context) do table.insert(parts,v) end
    p.definitions={}
    for _,name in ipairs(p.rewards) do
        local field="CASE MOD(p.job,4) WHEN 0 THEN r.warrior_items WHEN 1 THEN r.assassin_items WHEN 2 THEN r.sura_items ELSE r.shaman_items END"
        local rows=M.query("SELECT r.exp,r.gold,r.alignment,CAST(r.items AS CHAR) AS items,CAST("..field.." AS CHAR) AS class_items,MD5(CONCAT_WS('|',r.exp,r.gold,r.alignment,COALESCE(r.items,''),COALESCE("..field..",''))) AS reward_signature FROM world.quest_reward_proto r JOIN player.player p ON p.id="..pid.." WHERE quest_name="..M.literal(name))
        if not rows[1] then return nil,"reward_definition_missing" end
        table.insert(parts,name);table.insert(parts,rows[1].reward_signature);p.definitions[name]=rows[1]
    end
    local rows=M.query("SELECT MD5("..M.literal(table.concat(parts,"|"))..") AS signature")
    if not rows[1] then return nil,"reward_definition_missing" end
    p.signature=rows[1].signature;p.job=job
    return p
end
function M.active_key(pid,key,cycle)
    return pid..":"..key..(cycle>=0 and ":"..cycle or "")
end
function M.inventory_fits(items)
    local grid={};local occupied=0;local seen={};local old=item.get_id()
    -- This distribution has 4 inventory pages plus 1 horse page (225 cells).
    -- select_cell filters locked cells. Infer the unlocked bound using the
    -- native empty-cell count and the occupied anchors, without DB snapshots.
    for cell=0,224 do
        if item.select_cell(cell) then
            local id=item.get_id()
            if not seen[id] then
                seen[id]=true
                local anchor=item.get_cell();local size=item.get_size()
                for i=0,size-1 do grid[anchor+i*5]=true;occupied=occupied+1 end
            end
        end
    end
    if old and old>0 then item.select(old) end
    local maximum=pc.get_empty_inventory_count()+occupied
    if maximum<0 or maximum>225 then return false end
    for _,it in ipairs(items) do
        local size=gm_quest_item_sizes[it[1]];if not size or size<1 or size>3 then return false end
        local placed=false
        for cell=0,maximum-1 do
            if math.mod(math.floor(cell/5),9)+size<=9 and cell+(size-1)*5<maximum then
                local free=true;for i=0,size-1 do if grid[cell+i*5] then free=false end end
                if free then
                    for i=0,size-1 do grid[cell+i*5]=true end
                    placed=true;break
                end
            end
        end
        if not placed then return false end
    end
    return true
end
-- A Herbalist's Knife (29201-29210) in the hand or the bag, as
-- herbalism_onboarding.has_knife() asks it.
function M.has_herbalist_knife()
    local w=pc.get_weapon()
    if w and w>=29201 and w<=29210 then return true end
    for v=29201,29210 do if pc.count_item(v)>0 then return true end end
    return false
end
local function pool(t)
    local total=0;for i=1,table.getn(t),2 do total=total+t[i+1] end
    local n=number(1,total);local current=0
    for i=1,table.getn(t),2 do current=current+t[i+1];if n<=current then return t[i] end end
end
function M.prepare_full(row)
    local key=row.quest_name;local p,err=M.preview(pc.get_player_id(),key,tonumber(row.expected_state),row.variant,true)
    if not p then return nil,err end
    if p.cycle~=tonumber(row.expected_cycle) then return nil,"quest_cycle_changed" end
    if p.signature~=row.reward_signature then return nil,"reward_changed_refresh" end
    if p.spec.biologist and pc.getf(key,"sk_reward_paid")~=0 then return nil,"biologist_already_paid" end
    if p.spec.native=="dragon_soul" and ds.is_qualified() then return nil,"already_rewarded" end
    if p.spec.native=="skill_group" and pc.get_skill_group()~=0 then return nil,"already_rewarded" end
    for _,name in ipairs(p.rewards) do
        local rd={get_quest_reward_data(name)}
        if not M.definition_matches(rd,p.definitions[name]) then return nil,"reward_cache_mismatch_reload" end
        p.exp=p.exp+rd[1];p.gold=p.gold+rd[2];p.alignment=p.alignment+rd[3]
        for i=4,table.getn(rd),3 do
            local v,n=rd[i],rd[i+1]
            if rd[i+2]==true or rd[i+2]==1 then v,n=get_item_drop_info_from_special_group(v) end
            table.insert(p.items,{v,n,0})
        end
    end
    if p.exp_percent then p.exp=p.exp+pc.get_exp_level0(p.exp_percent[1],p.exp_percent[2]) end
    if p.spec.native=="quest_book" then
        local d=quest_book_data.QUEST_LIST[p.book_index];if not d then return nil,"quest_cycle_changed" end
        local r=quest_book_data.QUEST_REWARD;local kind=d.rewardType
        p.exp=p.exp+pool(r.exp[kind]);p.gold=p.gold+pool(r.gold[kind])
        local count=1;if number(1,4)==1 then count=count+1 end
        -- Match the stock helper literally (including Lua truthiness of 0).
        if pc.get_premium_remain_sec(PREMIUM_ITEM) then count=count+1 end
        for _,v in pairs(get_special_items(r.special_group[kind],count,true)) do
            table.insert(p.items,{v.vnum,v.count,math.max(v.rare_pct,50)})
        end
    end
    if p.spec.native=="herbalism" then
        -- Ours (kaethasger, 18 October): the introduction's own reward, 5% of
        -- a level (herbalism_onboarding.quest's reward state), and the first
        -- knife its start talk gives a character that has none and never got it.
        p.exp=p.exp+math.floor(pc.get_next_exp()*5/100)
        if pc.getf(key,"knife_given")==0 and not M.has_herbalist_knife() then table.insert(p.items,{29201,1,0}) end
    end
    if p.spec.native=="senior" then
        p.temporary_affect=({{POINT_MAX_HP,100},{POINT_HP_REGEN,30},{POINT_ST,5},{POINT_HT,5},
            {POINT_CRITICAL_PCT,10},{POINT_ATT_SPEED,10},{POINT_ATTBONUS_ANIMAL,10}})[number(1,7)]
    end
    if pc.get_gold()+p.gold>=2000000000 then return nil,"yang_limit" end
    if not p.exp or p.exp<0 or not p.gold or p.gold<0 then return nil,"reward_definition_invalid" end
    for _,it in ipairs(p.items) do
        if type(it[1])~="number" or type(it[2])~="number" or it[1]<1 or it[2]<1 or it[2]>200 or it[2]~=math.floor(it[2]) then return nil,"reward_item_invalid" end
        if not gm_quest_item_sizes[it[1]] then return nil,"item_size_unknown" end
    end
    table.sort(p.items,function(x,y) return gm_quest_item_sizes[x[1]]>gm_quest_item_sizes[y[1]] end)
    if not M.inventory_fits(p.items) then return nil,"inventory_full" end
    return p
end
function M.execute_full(row,p)
    local key=row.quest_name;local f=C[key].full_skip;local s=p.spec
    pc.setf(key,"qa_reward_id",tonumber(row.id))
    -- Cleanup owned quest materials only; missing requirements are skipped.
    local removals=s.remove_by_stage and s.remove_by_stage[p.stage] or s.remove
    if contains(s.remove_paid_states,p.stage) or (s.remove_when_rewards and table.getn(p.rewards)==0) then removals={} end
    for _,v in ipairs(removals) do
        local count=pc.count_item(v[1]);if v[2]~="all" then count=math.min(count,v[2]) end
        if count>0 then pc.remove_item(v[1],count) end
    end
    for _,it in ipairs(p.items) do
        local before=pc.count_item(it[1]);pc.give_item2(it[1],it[2],it[3])
        if pc.count_item(it[1])<before+it[2] then error("reward_item_not_in_inventory") end
    end
    if p.exp>0 then pc.give_exp2(p.exp) end
    if p.gold>0 then pc.change_money(p.gold) end
    if p.alignment~=0 then pc.change_alignment(p.alignment) end
    if s.native=="biologist" then
        for _,v in ipairs(gm_quest_biologist_affects[key]) do
            if v[3] then affect.add_collect(v[1],v[2],v[3]) else affect.add_collect(v[1],v[2]) end
        end
    elseif s.native=="dragon_soul" then
        ds.give_qualification();pc.setf(key,"qualified",1)
        pc.setf(key,"eye_timestamp",math.floor(get_global_time()/86400));pc.setf(key,"eye_left",m2_ds_eyes_per_day()-1)
    elseif s.native=="skill_group" then pc.set_skill_group(s.group)
    elseif s.native=="warehouse" then
        game.set_safebox_level(2);pc.set_account_flag("safebox_level",1)
        affect.remove(AFFECT_QUEST_USE);cleartimer("warehouse_expand_time");cleartimer("warehouse_expand_ambush")
    elseif s.native=="hunting" then
        pc.setf(key,"huntingProgress",p.cycle+1);pc.setf(key,"huntingMobVnum",0);pc.setf(key,"huntingMobCount",0)
    elseif s.native=="horse" or s.native=="horse_training" then
        horse.unride();horse.advance();horse.ride()
    elseif s.native=="cave_key" then
        if pc.getf(key,"heavens_cave_keyquest_Repeat")==0 and p.stage=="check_cooldown" then
            local cooldown=game.get_event_flag("keycooldown")
            pc.setf(key,"heavens_cave_keyquest_CooldownTime",cooldown>=1 and cooldown*60 or 86400)
        end
        pc.setf(key,"overall_cooldown_timestamp",get_time());pc.setf(key,"heavens_cave_keyquest_Repeat",1)
    elseif s.native=="quest_book" then
        pc.setf("quest_book_manage","quest_index",0);pc.add_player_stat(PLAYER_STATS_QUESTBOOK_FLAG)
    elseif s.native=="herbalism" then
        -- completed 3 is the plan's flag; herbalism.lua's can_craft() and
        -- is_unlocked() read it. The first recipe may be read at once, as the
        -- reward state lets it, and no second free knife comes after this.
        pc.setf("crafting","learn_delay11",0);pc.setf(key,"knife_given",1)
    elseif s.native=="senior" then affect.add(p.temporary_affect[1],p.temporary_affect[2],300)
    elseif s.native=="escort" then
        local vid=pc.getf(key,"escort_vid")
        if vid>0 and npc.select(vid)>0 and npc.get_race()==20401 then npc.purge() end
        cleartimer("escort_abort")
    end
    if s.reputation then pc.add_reputation(_G[s.reputation[1]],s.reputation[2]) end
    if s.biologist then pc.setf(key,"sk_reward_paid",1) end
    for _,v in ipairs(s.flags) do pc.setf(key,v[1],v[2]) end
    if f.cycle_flag=="qa_cycle" then pc.setf(key,"qa_cycle",p.cycle+1) end
    set_quest_state(key,p.terminal)
    for _,v in ipairs(s.follow) do if pc.getf(v[1],"__status")==0 then set_quest_state(v[1],v[2]) end end
    local result="wariant="..p.variant.."; EXP="..p.exp.."; Yang="..p.gold.."; items="
    for _,it in ipairs(p.items) do result=result..it[1].."x"..it[2].."/" end
    M.finish(row.id,"done",string.sub(result,1,200),false)
    syschat(M.t("GM wykonal pelny skip misji: ","A GM completed the quest for you: ")..C[key].label..
        M.t(". Odswiez dziennik przez przelogowanie.",". Log in again to refresh the quest list."))
end
-- Preserve the existing bounded queue/atomic claim. Only replace resolution
-- and effects, and validate the repeat-cycle and permanent nonrepeat guard.
M.prepare=function(key,signature,row) return M.prepare_full(row) end
M.execute=M.execute_full

local old_command=M.command
function M.command(args)
    if args[1]~="detail" and args[1]~="complete" then return old_command(args) end
    if not pc.is_gm() then return end
    local nonce=tostring(args[2] or "")
    if not string.find(nonce,'^%d+$') or string.len(nonce)>16 then return end
    local me=pc.get_player_id();local now=get_time();local quota=M.cooldown[me]
    if not quota or quota.until_time<=now then quota={until_time=now+10,count=0};M.cooldown[me]=quota end
    quota.count=quota.count+1
    if quota.count>30 then M.send(nonce,"error","rate_limit");return end
    local pid=M.integer(args[3],1,4294967295);local key=args[4] or ""
    if not pid or string.len(key)>64 or not string.find(key,'^[%w_]+$') then M.send(nonce,"error","invalid_request");return end
    if args[1]=="detail" then
        M.previews[me]=nil
        local flags=M.flags(pid,key);local value=flags.__status or 0
        local p,reason=M.preview(pid,key,value,args[5] or "",false)
        M.send(nonce,"detail_begin","ok")
        if not p then
            M.send(nonce,"detail_line",M.hex(C[key] and C[key].readonly_reason and M.word(C[key].readonly_reason) or reason or "unsupported_or_inactive"))
            M.send(nonce,"detail_end","ok");return
        end
        M.previews[me]={pid=pid,key=key,expected=value,signature=p.signature,variant=p.variant,cycle=p.cycle,until_time=now+300}
        for _,v in ipairs(M.options(key,value,p.job)) do M.send(nonce,"choice",v[1].."|"..M.hex(v[2])) end
        M.send(nonce,"chosen",p.variant)
        local lines={M.t("Pelny skip: ","Full skip: ")..M.word(p.label),"EXP "..p.exp.."; Yang "..p.gold.."; "..M.t("ranga ","rank ")..p.alignment}
        if M.is_bot_pid(pid) then table.insert(lines,1,M.t("Bot populacji - skip i nagrody sa wylaczone.","A bot of the population - no skip and no reward.")) end
        if p.exp_percent then table.insert(lines,M.t("Dodatkowo ","Plus ")..p.exp_percent[2]..M.t("% EXP poziomu ","% of the EXP of level ")..p.exp_percent[1]) end
        for _,name in ipairs(p.rewards) do
            local r=p.definitions[name];table.insert(lines,name..": EXP "..r.exp..", Yang "..r.gold..", "..M.t("ranga ","rank ")..r.alignment)
            for _,field in ipairs({r.items,r.class_items}) do
                local tokens={}
                for part in M.scan(tostring(field or ""),'[^,]+') do table.insert(tokens,(string.gsub(part,'^%s*(.-)%s*$','%1'))) end
                for i=1,table.getn(tokens),2 do
                    local v=tokens[i];local count=tokens[i+1] or "?"
                    if string.sub(v,1,1)=="s" then table.insert(lines,M.t("Losowy przedmiot z grupy ","A random item of group ")..string.sub(v,2).." x"..count)
                    else table.insert(lines,item_name(tonumber(v)).." (#"..v..") x"..count) end
                end
            end
        end
        for _,v in ipairs(p.items) do table.insert(lines,item_name(v[1]).." (#"..v[1]..") x"..v[2]) end
        if p.spec.native=="biologist" then
            for _,v in ipairs(gm_quest_biologist_affects[key]) do table.insert(lines,M.t("Staly bonus: ","Permanent bonus: ")..(gm_quest_point_names[v[1]] or v[1]).." +"..v[2]) end
        elseif p.spec.native=="quest_book" then table.insert(lines,M.t("Losowe EXP/Yang/przedmioty wedlug oryginalnego zwoju; bonusy jak w misji.","Random EXP/Yang/items by the scroll's own tables; bonuses as in the quest."))
        elseif p.spec.native=="senior" then table.insert(lines,M.t("Losowy bonus na 5 minut, jak w oryginalnym zadaniu.","A random bonus for 5 minutes, as in the quest."))
        elseif p.horse_target then table.insert(lines,M.t("Poziom konia po skipie: ","Horse level after the skip: ")..p.horse_target)
        elseif p.spec.native=="warehouse" then table.insert(lines,M.t("Odblokowanie drugiej strony magazynu.","Unlocks the storage's second page."))
        elseif p.spec.native=="dragon_soul" then table.insert(lines,M.t("Odblokowanie alchemii smoczych kamieni.","Unlocks the Dragon Stone Alchemy."))
        elseif p.spec.native=="herbalism" then table.insert(lines,M.t("Zielarstwo odblokowane; 5% EXP poziomu; Nozyk Zielarza+0, jesli postac go nie ma.","Herbalism unlocked; 5% of a level's EXP; a Herbalist's Knife+0 if the character has none."))
        elseif p.spec.native=="skill_group" then table.insert(lines,M.t("Wybrana profesja: ","Skill group: ")..p.spec.group) end
        if p.spec.reputation then table.insert(lines,M.t("Reputacja: +","Reputation: +")..p.spec.reputation[2]) end
        table.insert(lines,M.t("Koncowy etap: ","Final stage: ")..p.terminal..M.t(". Wczesniejsze nagrody nie sa powtarzane.",". Earlier rewards are not paid again."))
        for i=1,math.min(table.getn(lines),32) do M.send(nonce,"detail_line",M.hex(string.sub(lines[i],1,170))) end
        M.send(nonce,"detail_end","ok")
    else
        local value=M.integer(args[5],-2147483648,2147483647);local preview=M.previews[me]
        if not value or not M.allowed(key,value) then M.send(nonce,"error","unsupported_or_inactive");return end
        if not preview or preview.pid~=pid or preview.key~=key or preview.expected~=value or preview.until_time<now or
           (args[6] and args[6]~="" and args[6]~=preview.variant) then M.send(nonce,"error","reward_preview_required");return end
        local conf=M.query("SELECT enabled FROM player.web_quest_admin_config WHERE id=1")
        if not conf[1] or tonumber(conf[1].enabled)~=1 then M.send(nonce,"error","completion_disabled");return end
        if M.is_bot_pid(pid) then M.send(nonce,"error","playerbot");return end
        local active=M.active_key(pid,key,preview.cycle);local token="gm:"..me..":"..nonce
        M.query("INSERT IGNORE INTO player.web_quest_admin_actions(request_key,active_key,player_id,quest_name,expected_state,reward_signature,variant,expected_cycle,requester,source,reason,expires_at) VALUES("..
            M.literal(token)..","..M.literal(active)..","..pid..","..M.literal(key)..","..value..","..M.literal(preview.signature)..","..
            M.literal(preview.variant)..","..preview.cycle..","..M.literal(pc.get_name())..",'f9','GM F9 full skip',DATE_ADD(NOW(),INTERVAL 2 MINUTE))")
        local rows=M.query("SELECT id,status FROM player.web_quest_admin_actions WHERE active_key="..M.literal(active).." OR request_key="..M.literal(token).." ORDER BY id DESC LIMIT 1")
        if not rows[1] then M.send(nonce,"error","queue_failed");return end
        M.send(nonce,"queued",rows[1].id.."|"..rows[1].status)
    end
end
