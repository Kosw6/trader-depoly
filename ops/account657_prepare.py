import subprocess,json,hashlib
from pathlib import Path
root=Path('/opt/trader-runtime/account657');root.mkdir(parents=True,exist_ok=True)
assert not (root/'database-complete.json').exists(),'ALREADY_COMPLETED'
def sql(s):
 r=subprocess.run(['docker','exec','-i','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated'],input=s,capture_output=True,text=True)
 assert r.returncode==0,'PREPARE_SQL_FAILED'
 return json.loads(r.stdout)
names='users team user_team directory page note node edge node_note_link node_note_link_test node_history notifycation join_request admin_session cache_invalidation_task realtime_outbox processed_event search_source_state search_source_outbox ai_initial_run ai_wake_request canvas_lock edit_session edit_session_dirty_fields note_stock_tag note_upload note_upload_part policy_consent ai_transfer_consent'.split()
ai='event_quarantine event_receipt index_attempt index_job initial_notification initial_progress initial_run_job source_index_state'.split()
targets=['application.'+n for n in names]+['ai.'+n for n in ai]+['control649.admin_session']
before={t:sql('SELECT count(*) FROM '+t+';') for t in targets}
types=sql("SELECT json_build_object('sourceTypes',(SELECT json_agg(DISTINCT source_type) FROM ai.index_job),'tables',(SELECT json_agg(schemaname||'.'||tablename) FROM pg_tables WHERE schemaname IN ('source_local','source_remote','price_incremental567','price_refresh559','control649','price_gap581','integration_meta','application','ai')));")
assert set(types['sourceTypes'] or []) <= {'NOTE','NODE','EDGE','LINK','PAGE'},'UNEXPECTED_INDEX_SOURCE'
protected=[t for t in types['tables'] if t not in targets]
financial={t:sql('SELECT count(*) FROM '+t+';') for t in protected}
record={'targets':targets,'before':before,'protectedCounts':financial,'sourceTypes':types['sourceTypes']}
(root/'prepared.json').write_text(json.dumps(record));root.chmod(0o700)
config=json.loads(subprocess.check_output(['docker','inspect','trader-opensearch']))[0]
paths=[]
for m in config['Mounts']:
 if 'cert' in m['Destination'] or 'config' in m['Destination']:paths.append({'source':m['Source'],'destination':m['Destination']})
record['searchMounts']=paths
record['searchFiles']=[str(x) for x in Path('/data/trader-integrated547/opensearch').glob('**/*') if x.is_file() and x.suffix in ('.pem','.yml','.json')][:50]
print(json.dumps(record))
