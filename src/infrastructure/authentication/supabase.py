from typing import Optional
import json
import supabase
from types import MappingProxyType
import re

_TYPE_MAP    = {"string":"text","integer":"integer","float":"numeric",
                "boolean":"boolean","date":"date","datetime":"timestamp"}
_AUTH_FIELDS = {"id","email","password"}


def _pg(field, meta):

    pg_type = _TYPE_MAP.get(meta.get("type", "string"), "text")
    parts = [pg_type]
            
    return " ".join(parts)

def _cols(schema): 
    return {f: _pg(f, m) for f, m in schema.items() if f not in _AUTH_FIELDS}

def _existing(cur):
    cur.execute("""select column_name,data_type from information_schema.columns
                   where table_schema='public' and table_name='profiles'
                   and column_name not in ('id','created_at')""")
    return dict(cur.fetchall())

def profiles_table(schema):
    desired = _cols(schema)
    cols    = (["id uuid references auth.users(id) on delete cascade primary key"]
               + [f"{f} {t}" for f,t in desired.items()]
               + ["created_at timestamp default now()"])
    def migrate_fn(cur):
        ex = _existing(cur)
        return ([f"alter table public.profiles add column {c} {t};"                      for c,t in desired.items() if c not in ex]
              + [f"alter table public.profiles alter column {c} type {t} using {c}::{t};" for c,t in desired.items() if c in ex and ex[c]!=t]
              # + [f"alter table public.profiles drop column {c};"                           for c in ex if c not in desired]
              )
    return MappingProxyType({
        "name": "profiles table",
        "check_sql": "select exists(select 1 from information_schema.tables where table_schema='public' and table_name='profiles')",
        "create_sql": f"create table public.profiles (\n  {', '.join(cols)}\n);",
        "migrate_fn": migrate_fn,
    })

def handle_new_user(schema):
    fields = [f for f in schema if f not in _AUTH_FIELDS]
    ins_f  = ", ".join(["id"] + fields)
    ins_v  = ", ".join(["new.id"] + [f"new.raw_user_meta_data->>'{f}'" for f in fields])
    fn_sql = f"""create or replace function handle_new_user() returns trigger as $$
begin insert into public.profiles ({ins_f}) values ({ins_v}); return new; end;
$$ language plpgsql security definer;"""
    def migrate_fn(cur):
        cur.execute("select prosrc from pg_proc where proname='handle_new_user'")
        row = cur.fetchone()
        if not row: return [fn_sql]
        m = re.search(r"insert into public\.profiles \((.+?)\)", row[0])
        return [fn_sql] if (m.group(1).replace(" ","") if m else "") != ins_f.replace(" ","") else []
    
    return MappingProxyType({
        "name": "function handle_new_user",
        "check_sql": "select exists(select 1 from pg_proc where proname='handle_new_user')",
        "create_sql": fn_sql,
        "migrate_fn": migrate_fn,
    })
    

def on_auth_user_created():
    return MappingProxyType({
        "name": "trigger on_auth_user_created",
        "check_sql": "select exists(select 1 from pg_trigger where tgname='on_auth_user_created')",
        "create_sql": """create trigger on_auth_user_created after insert on auth.users
           for each row execute procedure handle_new_user();""",
        "migrate_fn": lambda cur: [],
    })

# ── helpers ───────────────────────────────────────────────────────────────────

def map_supabase_error(error):
    if error == 'Invalid login credentials':
        return [{"field": "email", "message": "Invalid login credentials"},{"field": "password", "message": "Invalid login credentials"}]
    elif error == 'Email change requested':
        return [{"field": "email", "message": "Email change requested"}]
    elif error == 'Email not confirmed':
        return [{"field": "email", "message": "Email not confirmed"}]
    elif error == 'Email already in use':
        return [{"field": "email", "message": "Email already in use"}]
    elif error == 'Password reset requested':
        return [{"field": "password", "message": "Password reset requested"}]
    elif error == 'Password reset failed':
        return [{"field": "password", "message": "Password reset failed"}]
    elif error == 'User not found':
        return [{"field": "email", "message": "User not found"}]
    return [{"field": "General", "message": error}]
    
    

def map_auth_response(provider,auth_res):
    # auth_res è l'oggetto restituito dal client python di supabase
    session = auth_res.session if not isinstance(auth_res, dict) else auth_res['session']
    user = auth_res.user if not isinstance(auth_res, dict) else auth_res['user']

    return {
        "id": user.id,
        "providers": {provider: {
            'tokens': {
                'access_token': session.access_token, 
                'refresh_token': session.refresh_token, 
                'expires_at': session.expires_at, 
                'token_type': session.token_type
            },
            'user': {
                "id": user.id,
                "email": user.email,
                **user.user_metadata
            }
        }},
        "user": {
            "id": user.id,
            "email": user.email,
            **user.user_metadata
        }
    }

class Adapter(authentication.port):
    """
    Adapter Supabase stateless per ambienti multi-utente.

    Ogni chiamata crea un client Supabase isolato: nessuna sessione condivisa
    tra richieste concorrenti di utenti diversi.

    Esempio:
        adapter = Adapter(url="https://...", key="anon-key")
        result  = await adapter.authenticate(email="u@example.com", password="secret")
        if result.success:
            tokens = result.data["tokens"]
    """

    def __init__(self, **kwargs):
        url = kwargs.get("url")
        key = kwargs.get("key")
        db_url = kwargs.get("db_url")
        self._schema = kwargs.get("models").get("user")
        if not url or not key:
            raise ValueError("Supabase URL e key sono obbligatori.")
        self._url = url
        self._key = key
        self._db_url = db_url
        self.name = "supabase"
        self._migrations = [
            profiles_table(self._schema),
            handle_new_user(self._schema),
            on_auth_user_created()
        ]
        self._seeds  = []
        if db_url:
            self.migrate()

    # ── Supabase client ───────────────────────────────────────────────────────

    def _client(self):
        return supabase.create_client(self._url, self._key)

    def _authed_client(self, session):
        tokens = session["providers"][self.name]["tokens"]
        client = self._client()
        client.auth.set_session(
            tokens["access_token"],
            tokens.get("refresh_token", ""),
        )
        return client

    # ── port implementation ───────────────────────────────────────────────────

    async def sign_up(self, password=None,email=None, **kwargs):
        
        try:
            # Creiamo una copia per non sporcare l'oggetto originale
            
            # Passiamo i parametri correttamente
            response = self._client().auth.sign_up({
                "email": email,
                "password": password,
                "options": {
                    "data": kwargs,
                    #"email_redirect_to": "http://localhost:5000/recovery"
                }
            })
            return authentication.flow.success(map_auth_response(self.name, response))
        except Exception as e:
            return authentication.flow.error(map_supabase_error(str(e)))

    async def sign_in(self, email, password):
        try:
            response  = self._client().auth.sign_in_with_password({"email": email, "password": password})
            return authentication.flow.success(map_auth_response(self.name,response))
        except Exception as e:
            return authentication.flow.error(map_supabase_error(str(e)))

    async def sign_out(self, session):
        try:
            tokens = session['providers'][self.name]['tokens']
            client = self._client()
            # IMPORTANTE: Passa sia access che refresh token se disponibili
            client.auth.set_session(tokens['access_token'], tokens.get('refresh_token', ""))
            
            # Opzionale: puoi forzare lo scope globale
            client.auth.sign_out({"scope": "global"})
            return authentication.flow.success()
        except Exception as e:
            return authentication.flow.error(map_supabase_error(str(e)))

    async def sign_aid(self, **kwargs):
        try:
            match kwargs['type']:
                case 'signup':
                    response = self._client().auth.verify_otp(**kwargs)
                    return authentication.flow.success(map_auth_response(self.name, response))
                case 'signin':
                    response = self._client().auth.verify_otp(**kwargs)
                    return authentication.flow.success(map_auth_response(self.name, response))
                case 'recovery':
                    response = self._client().auth.verify_otp(**kwargs)
                    return authentication.flow.success(map_auth_response(self.name, response))
                case 'magiclink':
                    client = self._client()
                    client.auth.set_session(kwargs['access_token'], kwargs.get('refresh_token', ""))
                    user = client.auth.get_user()
                    session = client.auth.get_session()
                    response = {'session':session, 'user':user.user}
                    return authentication.flow.success(map_auth_response(self.name, response))
                case _:
                    return authentication.flow.error("Invalid type")
            client = self._client()
            response = client.auth.verify_otp(**kwargs)
            return authentication.flow.success(map_auth_response(self.name, response))
        except Exception as e:
            return authentication.flow.error(map_supabase_error(str(e)))

    async def get_user(self, session):
        try:
            tokens = session['providers'][self.name]['tokens']
            client = self._client()
            client.auth.set_session(tokens['access_token'], tokens.get('refresh_token', ""))
            
            response = client.auth.get_user()
            
            if not response.user:
                return authentication.flow.error("Utente non autenticato.")
            
            # Restituiamo un formato coerente con il resto dell'app
            user = response.user
            return authentication.flow.success({
                "id": user.id,
                "email": user.email,
                **user.user_metadata
            })
        except Exception as e:
            return authentication.flow.error(map_supabase_error(str(e)))