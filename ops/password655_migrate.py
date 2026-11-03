"""Run only on the database host in maintenance. No credentials leave this process.
Existing backups/WAL are not erased by this migration.
"""
import concurrent.futures,ctypes,ctypes.util,fcntl,hashlib,json,os,re,subprocess,time
from pathlib import Path

PREFIX='{pbkdf2-sha256-600k-v1}'
ROOT=Path('/opt/trader-runtime/password655')
ARGON_PATTERN=r'\$argon2id\$v=19\$m=19456,t=2,p=1\$[A-Za-z0-9+/]{22}\$[A-Za-z0-9+/]{43}'
LIB=ctypes.CDLL(ctypes.util.find_library('argon2'))
ENCODE=LIB.argon2id_hash_encoded
ENCODE.argtypes=[ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t]
ENCODE.restype=ctypes.c_int
VERIFY=LIB.argon2id_verify
VERIFY.argtypes=[ctypes.c_char_p,ctypes.c_void_p,ctypes.c_size_t];VERIFY.restype=ctypes.c_int
def query(sql):
    r=subprocess.run(['docker','exec','-i','trader-integrated547-db','psql','-XqAt','-v','ON_ERROR_STOP=1','-U','postgres','-d','trader_integrated'],
        input="SET log_statement='none';SET log_min_error_statement='panic';SET statement_timeout='120s';"+sql,
        capture_output=True,text=True)
    assert r.returncode==0,'PASSWORD_MIGRATION_SQL_FAILED'
    return r.stdout.strip()
def write(name,value):
    target=ROOT/name;tmp=target.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.chmod(0o600);os.replace(tmp,target)
def snapshot():
    return json.loads(query("SELECT json_build_object('users',count(*),'nonPasswordHash',md5(coalesce(string_agg((to_jsonb(t)-'password')::text,E'\\n' ORDER BY id),'')),'nullPasswords',count(*) FILTER(WHERE password IS NULL),'maxBytes',max(octet_length(password))) FROM application.users t;"))
def encode(row):
    raw=row.pop('password');assert raw is not None and 0<len(raw.encode('utf8'))<=4096,'PASSWORD_LENGTH_REQUIRES_REVIEW'
    salt=os.urandom(16);data=raw.encode('utf8');out=ctypes.create_string_buffer(200)
    assert ENCODE(2,19456,1,data,len(data),salt,len(salt),32,out,len(out))==0,'ARGON_ENCODING_FAILED'
    assert VERIFY(out.value,data,len(data))==0,'ARGON_RAW_VERIFICATION_FAILED'
    return int(row['id']),out.value.decode('ascii')
def main():
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (ROOT/'migration.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert not (ROOT/'complete.json').exists(),'MIGRATION_ALREADY_COMPLETE'
        assert query("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend';")=='0','DATABASE_CLIENTS_PRESENT'
        before=snapshot()
        if (ROOT/'before.json').exists():
            original=json.loads((ROOT/'before.json').read_text());assert original['nonPasswordHash']==before['nonPasswordHash'],'USER_FIELDS_CHANGED'
        else:write('before.json',before)
        rows=json.loads(query("SELECT coalesce(json_agg(json_build_object('id',id,'password',password) ORDER BY id),'[]') FROM application.users WHERE password IS NOT NULL;"))
        pending=[];already=0
        for row in rows:
            if re.fullmatch(re.escape(PREFIX)+r'[0-9a-f]{96}',row['password']) or re.fullmatch(ARGON_PATTERN,row['password']):already+=1
            else:
                assert not row['password'].startswith(('{','$2a$','$2b$','$2y$')),'UNKNOWN_PASSWORD_FORMAT'
                assert row['password'].strip() and len(row['password'].encode('utf8'))<=4096,'INVALID_LEGACY_PASSWORD_REVIEW'
                pending.append(row)
        done=0;started=time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for offset in range(0,len(pending),40):
                batch=list(pool.map(encode,pending[offset:offset+40]))
                values=','.join("(%d,'%s')"%(uid,hashed) for uid,hashed in batch)
                updated=query("BEGIN;SET LOCAL lock_timeout='3s';UPDATE application.users u SET password=v.hash FROM (VALUES "+values+") v(id,hash) WHERE u.id=v.id;SELECT count(*) FROM application.users u JOIN (VALUES "+values+") v(id,hash) ON u.id=v.id AND u.password=v.hash;COMMIT;")
                assert updated==str(len(batch)),'PASSWORD_WRITE_READBACK_MISMATCH'
                done+=len(batch);write('progress.json',{'algorithm':'argon2id','status':'MIGRATING','converted':done,'previouslyConverted':already,'pending':len(pending)-done,'elapsedSeconds':round(time.time()-started)})
        after=snapshot();assert before['nonPasswordHash']==after['nonPasswordHash'] and before['users']==after['users'],'OTHER_USER_DATA_CHANGED'
        finalRows=json.loads(query("SELECT coalesce(json_agg(password),'[]') FROM application.users WHERE password IS NOT NULL;"))
        pb=sum(bool(re.fullmatch(re.escape(PREFIX)+r'[0-9a-f]{96}',x)) for x in finalRows)
        ar=sum(bool(re.fullmatch(ARGON_PATTERN,x)) for x in finalRows)
        counts={'hashed':pb+ar,'argon2id':ar,'pbkdf2':pb,'otherNonNull':len(finalRows)-pb-ar,'null':after['nullPasswords']}
        assert counts['otherNonNull']==0 and counts['hashed']==done+already,'HASH_SET_MISMATCH'
        result={'status':'VERIFIED','converted':done,'previouslyConverted':already,'users':after['users'],'counts':counts,'nonPasswordFieldsUnchanged':True,'plaintextExported':False,'oldBackupsDeleted':False,'elapsedSeconds':round(time.time()-started)}
        write('complete.json',result);print(json.dumps(result))
if __name__=='__main__':main()
