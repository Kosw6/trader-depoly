import subprocess,json
def cli(*args):
 sh='export REDISCLI_AUTH="$(awk \'$1=="requirepass" {print $2}\' /usr/local/etc/redis/redis.conf)"; exec redis-cli --no-auth-warning --json "$@"'
 r=subprocess.run(['docker','exec','trader-redis','sh','-c',sh,'redis-task',*map(str,args)],capture_output=True,text=True)
 assert r.returncode==0,'REDIS_DELETE_FAILED'
 return json.loads(r.stdout)
cursor='0';keys=set()
while True:
 cursor,found=cli('-n',0,'SCAN',cursor,'MATCH','canvas:*','COUNT',1000);keys.update(found)
 if str(cursor)=='0':break
assert len(keys)<=5 and all(k.startswith('canvas:') for k in keys),'CACHE_TARGET_DRIFT'
deleted=cli('-n',0,'DEL',*sorted(keys)) if keys else 0
assert cli('-n',0,'DBSIZE')==0,'UNEXPECTED_REDIS_DATA_REVIEW'
assert cli('SAVE')=='OK','REDIS_PERSISTENCE_FAILED'
print(json.dumps({'deletedCanvasKeys':deleted,'remainingDb0Keys':0,'persisted':True,'flushAllUsed':False}))
