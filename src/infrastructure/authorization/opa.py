import aiohttp
import framework.core.flow as flow

class adapter:
    def __init__(self, **constants):
        self.config = constants['config']
        self.url = self.config.get('url')

    
    @flow.result(safe_kwargs=True)
    async def whoami(self, **data):
        """
        Recupera le informazioni del profilo utente da GitHub utilizzando l'access_token.
        """
        access_token = data.get("access_token")
        if not access_token:
            raise ValueError("Access token mancante.")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "flet-app"
        }

        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.github.com/user", headers=headers) as response:
                if response.status == 200:
                    user_data = await response.json()
                    return {
                        "id": user_data.get("id"),
                        "username": user_data.get("login"),
                        "name": user_data.get("name"),
                        "avatar_url": user_data.get("avatar_url"),
                        "email": user_data.get("email"),
                        "url": user_data.get("html_url"),
                        "provider": "github",
                        "raw": user_data
                    }
                else:
                    print(f"Errore durante whoami: {response.status} - {await response.text()}")
                    return None
    
    @flow.result(safe_kwargs=True)
    async def logout(self,**data):
        pass

    @flow.result(safe_kwargs=True)
    async def registration(self,**data):
        pass

    '''async def authenticate(self,**data):
        
        url = self.url+f"&code={data.get('code','')}"
        headers = {
            'accept': 'application/json'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                print(response.status,response.json())
                if response.status == 200:
                    data = await response.json()
                    print(data,'github')
                    return data
                else:
                    return None'''
    
    @flow.result(safe_kwargs=True)
    async def authenticate(self, **data):
        """
        Esegue l'autenticazione con GitHub (OAuth) e restituisce una sessione normalizzata.
        """
        url = self.url + f"&code={data.get('code', '')}"
        headers = {
            'accept': 'application/json'
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status == 200:
                    token_data = await response.json()
                    access_token = token_data.get("access_token")
                    token_type = token_data.get("token_type", "bearer")
                    scope = token_data.get("scope", "")

                    if not access_token:
                        return None
                    
                    user = await self.whoami(access_token=access_token)

                    # Costruzione della sessione in formato coerente
                    session_data = {
                        "tokens":{
                            "access_token": access_token,
                            "refresh_token": None,
                            "token_type": token_type,
                            "scope": scope,
                        },
                        "user": user,
                    }

                    return session_data
                else:
                    print(f"Auth error {response.status}: {await response.text()}")
                    return None