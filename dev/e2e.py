import json, time, urllib.request, sys
B="http://127.0.0.1:8126"; T=open(sys.argv[1]).read().strip()  # path to a dev-HA token file
def req(method, path, body=None):
    r=urllib.request.Request(B+path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization":"Bearer "+T,"Content-Type":"application/json"})
    with urllib.request.urlopen(r) as f: return json.loads(f.read() or "null")
def st(e): return req("GET","/api/states/"+e)
def call(d,s,data): req("POST",f"/api/services/{d}/{s}",data); time.sleep(1.2)
P="media_player.living_room"
def vol(): return st(P)["attributes"].get("volume_level")
entry=[e for e in req("GET","/api/config/config_entries/entry") if e["domain"]=="adaptive_audio" and e["title"]=="Living room"][0]["entry_id"]
SPEAKERS={"players":[P,"media_player.walkman"],"idle_gap":0,"skip_sources":"Line In","autoreset":0,"max_rate":3}
QUIET_CAP={"quiet_volume":10,"quiet_entity":"input_boolean.night_mode","quiet_state":"on",
           "cap_enabled":False,"cap_start":"22:00:00","cap_end":"07:00:00","cap_volume":25}
def _values(fields):
    """The page's current values, from its suggested values (sections nested)."""
    out={}
    for f in fields:
        if f.get("type")=="expandable": out[f["name"]]=_values(f["schema"])
        elif "suggested_value" in (f.get("description") or {}): out[f["name"]]=f["description"]["suggested_value"]
    return out
def options(**kw):
    """Configure is one page: fill it from its current values plus SPEAKERS/QUIET_CAP/kw, submit."""
    U="/api/config/config_entries/options/flow"
    f=req("POST",U,{"handler":entry}); fid=f["flow_id"]
    for _ in range(3):
        v=_values(f["data_schema"])
        for sec, base in (("speakers",SPEAKERS),("quiet_cap",QUIET_CAP)):
            v[sec]={**v.get(sec,{}),**{k:kw.get(k,x) for k,x in base.items()}}
        f=req("POST",f"{U}/{fid}",v)
        if f["type"]!="form": break
    time.sleep(2); return f["type"]
def check(name, got, want):
    ok = abs((got or -1)-want)<0.011; print(("PASS" if ok else "FAIL"), name, "got", got, "want", want)
tgt=int(st("sensor.adaptive_audio_living_room_scheduled_volume")["state"])/100
print("options:",options(idle_gap=0))
call("media_player","volume_set",{"entity_id":P,"volume_level":0.9})
call("media_player","media_pause",{"entity_id":P}); call("media_player","media_play",{"entity_id":P})
check("fresh start gets target", vol(), tgt)
call("media_player","volume_set",{"entity_id":P,"volume_level":0.8})
check("mid-play change stands", vol(), 0.8)
call("input_boolean","turn_on",{"entity_id":"input_boolean.night_mode"})
check("linked quiet pulls down", vol(), 0.10)
call("media_player","volume_set",{"entity_id":P,"volume_level":0.5})
check("quiet caps a raise", vol(), 0.10)
call("input_boolean","turn_off",{"entity_id":"input_boolean.night_mode"})
call("switch","turn_on",{"entity_id":"switch.adaptive_audio_living_room_quiet_mode"})
call("media_player","media_pause",{"entity_id":P}); call("media_player","media_play",{"entity_id":P})
check("quiet switch: start at quiet volume", vol(), 0.10)
call("number","set_value",{"entity_id":"number.adaptive_audio_living_room_quiet_volume","value":6})
check("lower quiet volume applies live", vol(), 0.06)
call("switch","turn_off",{"entity_id":"switch.adaptive_audio_living_room_quiet_mode"})
print("options:",options(idle_gap=1))
call("media_player","volume_set",{"entity_id":P,"volume_level":0.7})
call("media_player","media_pause",{"entity_id":P}); call("media_player","media_play",{"entity_id":P})
check("short pause keeps volume", vol(), 0.7)
now=time.localtime(); start=f"{now.tm_hour:02d}:00:00"; end=f"{(now.tm_hour+1)%24:02d}:00:00"
print("options:",options(idle_gap=1,cap_enabled=True,cap_start=start,cap_end=end,cap_volume=25))
call("media_player","volume_set",{"entity_id":P,"volume_level":0.9})
check("cap pulls a raise back", vol(), 0.25)
call("media_player","volume_set",{"entity_id":P,"volume_level":0.2})
check("below cap is fine", vol(), 0.2)
print("options:",options(idle_gap=0))
call("switch","turn_off",{"entity_id":"switch.adaptive_audio_living_room_adaptive_audio"})
call("media_player","media_pause",{"entity_id":P}); call("media_player","media_play",{"entity_id":P})
check("disabled: hands off", vol(), 0.2)
call("switch","turn_on",{"entity_id":"switch.adaptive_audio_living_room_adaptive_audio"})
call("button","press",{"entity_id":"button.adaptive_audio_living_room_set_volume_now"})
check("apply button", vol(), tgt)
check("apply button other speaker", st("media_player.walkman")["attributes"].get("volume_level"), tgt)
s=st("sensor.adaptive_audio_living_room_scheduled_volume"); print("steps+sun target:",s["state"],s["attributes"]["schedule_error"])
print("last_applied:",json.dumps(s["attributes"]["last_applied"]))

# Adapt while playing: glide toward the target, a hand change takes the speaker over.
SW="switch.adaptive_audio_living_room_adjust_while_playing"
print("options:",options(idle_gap=0))
call("switch","turn_off",{"entity_id":SW})
call("media_player","volume_set",{"entity_id":P,"volume_level":0.25})
call("switch","turn_on",{"entity_id":SW})
time.sleep(63)
check("adapt: one max_rate (3%) step toward the target", vol(), 0.28)
call("media_player","volume_set",{"entity_id":P,"volume_level":0.55})
print("taken over:", st(SW)["attributes"]["taken_over"])
time.sleep(62)
check("adapt: hand change is left alone", vol(), 0.55)
call("media_player","media_pause",{"entity_id":P}); call("media_player","media_play",{"entity_id":P})
check("adapt: fresh start clears the takeover", vol(), tgt)
print("taken over after fresh start:", st(SW)["attributes"]["taken_over"])
call("switch","turn_off",{"entity_id":SW})
