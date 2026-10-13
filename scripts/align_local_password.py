"""One-use loopback password alignment form. User enters credentials privately."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets, sqlite3, threading, json, sys
from urllib.parse import parse_qs
import httpx
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.services.security import hash_secret
cfg=dotenv_values(ROOT/'.env')
nonce=secrets.token_urlsafe(32)
email='pharmacist@example.com'
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def respond(self,status,body):
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        # Same-origin form posts need their Origin header for CSRF validation.
        self.send_header('Referrer-Policy','same-origin')
        self.end_headers();self.wfile.write(body.encode())
    def do_GET(self):
        if self.path!='/'+nonce: return self.respond(404,'Not found')
        self.respond(200,'''<!doctype html><title>Match pharmacy passwords</title><style>body{font:18px system-ui;max-width:580px;margin:70px auto;padding:24px}input,button{display:block;width:100%;padding:12px;margin:12px 0;box-sizing:border-box}button{background:#176b59;color:white;border:0;border-radius:6px}</style><h1>Match your pharmacy login</h1><p>Account: pharmacist@example.com</p><p>Enter the password you created in Supabase. We will verify it with your configured Supabase project, then update only your local pharmacy login. Your cloud password will not change.</p><form method="post"><label>Supabase password<input type="password" name="password" autocomplete="off" required minlength="12" maxlength="128"></label><label>Confirm password<input type="password" name="confirm" autocomplete="off" required minlength="12" maxlength="128"></label><button>Verify and update local login</button></form><p>Your password is not saved in a file or shown in chat. Existing local sessions will be signed out. This form expires in 15 minutes.</p>''')
    def do_POST(self):
        if self.path!='/'+nonce or self.headers.get('Origin')!=origin: return self.respond(403,'Invalid form origin')
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<4096: return self.respond(400,'Invalid request')
        data=parse_qs(self.rfile.read(size).decode())
        password=data.get('password',[''])[0]
        if password!=data.get('confirm',[''])[0] or not 12<=len(password)<=128: return self.respond(400,'Passwords must match and contain 12–128 characters. Go back and retry.')
        try:
            with sqlite3.connect(ROOT/'temp.db') as local:
                profile=local.execute('SELECT id FROM employee_table WHERE lower(email)=lower(?)',(email,)).fetchone()
                if not profile: return self.respond(409,'Local account not found; nothing changed.')
            response=httpx.post(cfg['SUPABASE_PROJECT_URL']+'/auth/v1/token?grant_type=password',headers={'apikey':cfg['SUPABASE_PUBLISHABLE_KEY']},json={'email':email,'password':password},timeout=20)
            if response.status_code!=200: return self.respond(400,'Supabase did not accept this password. Nothing changed. Go back and enter your Supabase password again.')
            session=response.json()
            if session.get('user',{}).get('email','').lower()!=email: return self.respond(403,'Cloud account mismatch; nothing changed.')
            check=httpx.post(cfg['SUPABASE_PROJECT_URL']+'/rest/v1/rpc/erp_sync_pull',headers={'apikey':cfg['SUPABASE_PUBLISHABLE_KEY'],'Authorization':'Bearer '+session['access_token']},json={'p_device':cfg['SYNC_DEVICE_ID'],'p_device_secret':cfg['SYNC_DEVICE_SECRET'],'p_cursor':0},timeout=20)
            if check.status_code!=200 or str(check.json().get('pharmacy_id'))!=cfg['SYNC_PHARMACY_ID']: return self.respond(409,'Cloud login worked but device verification failed. Local password was not changed; tell Codex this message.')
            digest=hash_secret(password)
            with sqlite3.connect(ROOT/'temp.db',timeout=10) as local:
                local.execute('UPDATE employee_table SET password_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',(digest,profile[0]))
                local.execute('DELETE FROM auth_sessions WHERE profile_id=?',(profile[0],))
                local.execute('DELETE FROM password_reset_tokens WHERE profile_id=?',(profile[0],))
            self.respond(200,'<h1>Local password updated</h1><p>Your cloud login and device were verified. Both logins now use your Supabase password.</p><p>Return to the pharmacy app and sign in as pharmacist@example.com with that password. Your medicine queue has not been uploaded.</p>')
            print('SUCCESS: local password aligned; cloud login and device verified. No medicines uploaded.',flush=True)
            threading.Thread(target=self.server.shutdown,daemon=True).start()
        except Exception:
            self.respond(503,'Could not complete verification. No success confirmed. Tell Codex this message; do not send your password.')
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
origin='http://127.0.0.1:'+str(server.server_port)
print('FORM_URL='+origin+'/'+nonce,flush=True)
expiry=threading.Timer(900,server.shutdown);expiry.daemon=True;expiry.start()
server.serve_forever();server.server_close()
