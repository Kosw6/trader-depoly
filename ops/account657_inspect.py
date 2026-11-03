import subprocess,json
def sql(s):
 r=subprocess.run(['docker','exec','-i','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated'],input=s,capture_output=True,text=True)
 assert r.returncode==0,'INSPECTION_SQL_FAILED'
 return json.loads(r.stdout)
r=sql("""SELECT json_build_object(
'tables',(SELECT json_agg(x) FROM (SELECT schemaname,tablename FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') ORDER BY 1,2)x),
'columns',(SELECT json_agg(x) FROM (SELECT table_schema,table_name,string_agg(column_name,',' ORDER BY ordinal_position) columns FROM information_schema.columns WHERE table_schema IN ('application','ai') GROUP BY 1,2 ORDER BY 1,2)x),
'fks',(SELECT json_agg(x) FROM (SELECT conrelid::regclass::text child,confrelid::regclass::text parent,pg_get_constraintdef(oid) definition FROM pg_constraint WHERE contype='f' AND (connamespace IN ('application'::regnamespace,'ai'::regnamespace)))x),
'activity',(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend' AND xact_start IS NOT NULL),
'prepared',(SELECT count(*) FROM pg_prepared_xacts));""")
r['containers']=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
import zlib,base64
print(json.dumps({'compressed':base64.b64encode(zlib.compress(json.dumps(r).encode())).decode()}))
