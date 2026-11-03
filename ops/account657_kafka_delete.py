import subprocess,json
from pathlib import Path
def cli(script,*args):
 r=subprocess.run(['docker','exec','trader-kafka','/opt/kafka/bin/'+script,'--bootstrap-server','localhost:9092',*args],capture_output=True,text=True,timeout=120)
 assert r.returncode==0,'KAFKA_COMMAND_FAILED'
 return r.stdout.strip()
topics=['canvas-events','trader-search-source-v1']
parts=[]
for topic in topics:
 latest=cli('kafka-get-offsets.sh','--topic',topic,'--time','-1')
 assert latest==BEFORE[topic]['latest'],'USER_TOPIC_CHANGED'
 for line in latest.splitlines():
  t,part,offset=line.rsplit(':',2);parts.append({'topic':t,'partition':int(part),'offset':int(offset)})
plan=json.dumps({'partitions':parts,'version':1})
path='/tmp/account657-delete-records.json'
r=subprocess.run(['docker','exec','-i','trader-kafka','sh','-c','cat > '+path],input=plan,capture_output=True,text=True);assert r.returncode==0,'KAFKA_PLAN_FAILED'
out=cli('kafka-delete-records.sh','--offset-json-file',path)
assert 'error' not in out.lower(),'KAFKA_DELETE_ERROR'
after={t:{when:cli('kafka-get-offsets.sh','--topic',t,'--time',value) for when,value in [('earliest','-2'),('latest','-1')]} for t in BEFORE}
for t in topics:assert after[t]['earliest']==after[t]['latest']==BEFORE[t]['latest'],'USER_EVENTS_REMAIN'
for t in BEFORE:
 if t not in topics:assert after[t]==BEFORE[t],'FINANCIAL_EVENT_OFFSET_CHANGED'
result={'clearedTopics':topics,'preservedTopics':[t for t in BEFORE if t not in topics],'after':after,'topicsAndConfigurationsPreserved':True}
p=Path('/opt/trader-runtime/account657');p.mkdir(parents=True,exist_ok=True);(p/'kafka-complete.json').write_text(json.dumps(result))
subprocess.run(['docker','exec','trader-kafka','rm','--',path],capture_output=True)
print(json.dumps(result))
