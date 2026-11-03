import json,subprocess
s="SELECT json_build_object('activeGoSessions',(SELECT count(*) FROM control649.admin_session WHERE revoked_at IS NULL AND expires_at>now()),'latestGoLogin',(SELECT max(created_at) FROM control649.admin_session),'admins',(SELECT count(*) FROM application.users WHERE role=0),'latestGoUse',(SELECT max(last_seen_at) FROM control649.admin_session));"
r=subprocess.run(['docker','exec','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated','-c',s],capture_output=True,text=True)
assert r.returncode==0,'ADMIN_READ_FAILED';x=json.loads(r.stdout);assert x['admins']==1 and x['activeGoSessions']>=1,'ADMIN_LOGIN_NOT_CONFIRMED';print(json.dumps(x))
