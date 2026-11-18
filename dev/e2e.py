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
entry=[e for e in req("GET","/api/config/config_entries/entry") if e["domain"]=="adaptive_volume"][0]["entry_id"]
def options(**kw):
    f=req("POST","/api/config/config_entries/options/flow",{"handler":entry})
    cur={x["name"]:None for x in f["data_schema"]}
    base={"players":[P,"media_player.walkman"],"mode":"curve","points":"07:00 20\n10:00 40\n18:00 35\n22:00 15","idle_gap":0,
          "skip_sources":"Line In","quiet_volume":10,"quiet_entity":"input_boolean.night_mode","quiet_state":"on",
          "cap_enabled":False,"cap_start":"22:00:00","cap_end":"07:00:00","cap_volume":25}
    base.update(kw); r=req("POST",f"/api/config/config_entries/options/flow/{f['flow_id']}",base); time.sleep(2); return r["type"]
def check(name, got, want):
    ok = abs((got or -1)-want)<0.011; print(("PASS" if ok else "FAIL"), name, "got", got, "want", want)
tgt=int(st("sensor.adaptive_volume_living_room_target_volume")["state"])/100
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
call("switch","turn_on",{"entity_id":"switch.adaptive_volume_living_room_quiet"})
call("media_player","media_pause",{"entity_id":P}); call("media_player","media_play",{"entity_id":P})
check("quiet switch: start at quiet volume", vol(), 0.10)
call("number","set_value",{"entity_id":"number.adaptive_volume_living_room_quiet_volume","value":6})
check("lower quiet volume applies live", vol(), 0.06)
call("switch","turn_off",{"entity_id":"switch.adaptive_volume_living_room_quiet"})
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
call("switch","turn_off",{"entity_id":"switch.adaptive_volume_living_room_adaptive_volume"})
call("media_player","media_pause",{"entity_id":P}); call("media_player","media_play",{"entity_id":P})
check("disabled: hands off", vol(), 0.2)
call("switch","turn_on",{"entity_id":"switch.adaptive_volume_living_room_adaptive_volume"})
call("button","press",{"entity_id":"button.adaptive_volume_living_room_apply_volume_now"})
check("apply button", vol(), tgt)
check("apply button other speaker", st("media_player.walkman")["attributes"].get("volume_level"), tgt)
print("options:",options(mode="steps",points="sunrise 20\n12:00 40\nsunset 30\nsunset+120 15"))
s=st("sensor.adaptive_volume_living_room_target_volume"); print("steps+sun target:",s["state"],s["attributes"]["schedule_error"])
print("last_applied:",json.dumps(s["attributes"]["last_applied"]))
