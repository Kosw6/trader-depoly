import subprocess,json,re,collections
if ROLE=='redis':
 def cli(*args):
  sh='export REDISCLI_AUTH="$(awk \'$1=="requirepass" {print $2}\' /usr/local/etc/redis/redis.conf)"; exec redis-cli --no-auth-warning --json "$@"'
  r=subprocess.run(['docker','exec','trader-redis','sh','-c',sh,'redis-task',*map(str,args)],capture_output=True,text=True)
  assert r.returncode==0,'REDIS_INSPECT_FAILED'
  if args[0]=='INFO' and r.stdout.lstrip().startswith('#'):return r.stdout
  return json.loads(r.stdout)
 info=cli('INFO','keyspace');dbs=re.findall(r'^db(\d+):',info,re.M);result={}
 for db in dbs:
  cur='0';groups=collections.Counter()
  while True:
   cur,keys=cli('-n',db,'SCAN',cur,'COUNT',1000)
   for key in keys:
    match=re.match(r'^[A-Za-z_-]+',key);label=match.group(0) if match else 'OTHER'
    groups[label]+=1
   if str(cur)=='0':break
  result[db]=dict(groups)
 print(json.dumps({'databases':result}))
elif ROLE=='kafka':
 def cli(script,*args):
  r=subprocess.run(['docker','exec','trader-kafka','/opt/kafka/bin/'+script,'--bootstrap-server','localhost:9092',*args],capture_output=True,text=True,timeout=90)
  assert r.returncode==0,'KAFKA_INSPECT_FAILED'
  return r.stdout.strip()
 topics=[t for t in cli('kafka-topics.sh','--list').splitlines() if not t.startswith('__')]
 result={t:{when:cli('kafka-get-offsets.sh','--topic',t,'--time',value) for when,value in [('earliest','-2'),('latest','-1')]} for t in topics}
 print(json.dumps({'topics':result}))
