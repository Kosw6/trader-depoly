"""Promote only the owner's explicitly identified newly registered account."""
import json,subprocess
sql=r"""
BEGIN;
SET LOCAL lock_timeout='10s';
LOCK TABLE application.users IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE selected658 ON COMMIT DROP AS
 SELECT id, md5((to_jsonb(u)-'role')::text) fingerprint FROM application.users u
 WHERE email='kosw006@gmail.com' OR login_id='kosw006@gmail.com';
DO $$ BEGIN
 IF (SELECT count(*) FROM selected658) <> 1 THEN RAISE EXCEPTION 'IDENTITY_NOT_UNIQUE'; END IF;
 IF (SELECT count(*) FROM application.users) <> 1 THEN RAISE EXCEPTION 'UNEXPECTED_OTHER_ACCOUNTS'; END IF;
 IF EXISTS(SELECT 1 FROM application.users WHERE role IS DISTINCT FROM 1) THEN RAISE EXCEPTION 'UNEXPECTED_ROLE'; END IF;
END $$;
UPDATE application.users SET role=0 WHERE id=(SELECT id FROM selected658);
DO $$ BEGIN
 IF (SELECT count(*) FROM application.users WHERE role=0) <> 1 THEN RAISE EXCEPTION 'ADMIN_COUNT'; END IF;
 IF EXISTS(SELECT 1 FROM application.users u JOIN selected658 s USING(id) WHERE md5((to_jsonb(u)-'role')::text)<>s.fingerprint) THEN RAISE EXCEPTION 'OTHER_FIELDS_CHANGED'; END IF;
END $$;
COMMIT;
SELECT json_build_object('committed',true,'accounts',(SELECT count(*) FROM application.users),'admins',(SELECT count(*) FROM application.users WHERE role=0),'otherFieldsUnchanged',true);
"""
r=subprocess.run(['docker','exec','-i','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated'],input=sql,capture_output=True,text=True)
assert r.returncode==0,'PROMOTION_TRANSACTION_FAILED_DO_NOT_REPLAY'
print(r.stdout)
