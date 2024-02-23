import base64
import json

import httpx
import requests
import urllib.parse

from http import HTTPStatus
from typing import Optional


class AsyncClient:
    def __init__(self,
                 email: Optional[str] = None, password: Optional[str] = None,
                 key_name: Optional[str] = None, key_description: Optional[str] = None,
                 key: Optional[str] = None):
        """
        An asynchronous Clash of Clans API client

        :param email: email address of the Clash of Clans API account
        :param password: password of the Clash of Clans API account
        :param key_name: name of key to be updated or created
        :param key_description: description of key to be updated or created
        :param key: existing key which will be used to connect to Clash of Clans API.
            If specified, overrides previous parameters.
        """
        self.email = email
        self.password = password
        self.key_name = key_name
        self.key_description = key_description
        self.key = key

        self.http_client = httpx.AsyncClient()

        if None not in (self.email, self.password):
            self.update_key()

    def update_key(self) -> bool:
        if None in (self.email, self.password):
            return False
        session = requests.Session()
        login = session.post(url='https://developer.clashofclans.com/api/login',
                             json={'email': self.email, 'password': self.password})
        current_ip = json.loads(base64.b64decode(login.json()['temporaryAPIToken'].split('.')[1] + '====')
                                .decode('utf-8'))['limits'][1]['cidrs'][0].split('/')[0]
        retrieved_key_to_update = None
        retrieved_key_list = session.post(url=f"https://developer.clashofclans.com/api/apikey/list").json()['keys']
        for retrieved_key in retrieved_key_list:
            if retrieved_key['name'] == self.key_name:
                retrieved_key_to_update = retrieved_key
                break
        if retrieved_key_to_update is None:
            session.post(url='https://developer.clashofclans.com/api/apikey/create',
                         json={'cidrRanges': [current_ip], 'description': self.key_description,
                               'name': self.key_name, 'scopes': ['clash']})
        else:
            if current_ip in retrieved_key_to_update['cidrRanges']:
                self.key = retrieved_key_to_update['key']
                return True
            else:
                session.post(url='https://developer.clashofclans.com/api/apikey/revoke',
                             json={'id': retrieved_key_to_update['id']})
                session.post(url='https://developer.clashofclans.com/api/apikey/create',
                             json={'cidrRanges': retrieved_key_to_update['cidrRanges'] + [current_ip],
                                   'description': self.key_description,
                                   'name': self.key_name,
                                   'scopes': ['clash']})
        updated_key_list = session.post(url='https://developer.clashofclans.com/api/apikey/list').json()['keys']
        session.post(url='https://developer.clashofclans.com/api/logout')
        self.key = None
        for updated_key in updated_key_list:
            if updated_key['name'] == self.key_name:
                self.key = updated_key['key']
                break
        if self.key is None:
            return False
        return True

    async def get_data(self, url: str):
        response = await self.http_client.get(url=url,
                                              headers={
                                                  'authorization': f'Bearer {self.key}',
                                                  'accept': 'application/json'
                                              },
                                              timeout=60)
        if response.status_code == HTTPStatus.FORBIDDEN and self.update_key():
            response = await self.http_client.get(url=url,
                                                  headers={
                                                      'authorization': f'Bearer {self.key}',
                                                      'accept': 'application/json'
                                                  },
                                                  timeout=60)
        return response.json() if response.status_code == HTTPStatus.OK else None

    async def get_clan(self, clan_tag: str):
        return await self.get_data(f'https://api.clashofclans.com/v1/clans/'
                                   f'{urllib.parse.quote(clan_tag)}')

    async def get_clan_current_war(self, clan_tag: str):
        return await self.get_data(f'https://api.clashofclans.com/v1/clans/'
                                   f'{urllib.parse.quote(clan_tag)}/currentwar')

    async def get_clan_war_league_group(self, clan_tag: str):
        return await self.get_data(f'https://api.clashofclans.com/v1/clans/'
                                   f'{urllib.parse.quote(clan_tag)}/currentwar/leaguegroup')

    async def get_clan_war_league_war(self, war_tag: str):
        return await self.get_data(f'https://api.clashofclans.com/v1/clanwarleagues/wars/'
                                   f'{urllib.parse.quote(war_tag)}')

    async def get_clan_capital_raid_seasons(self, clan_tag: str):
        return await self.get_data(f'https://api.clashofclans.com/v1/clans/'
                                   f'{urllib.parse.quote(clan_tag)}/capitalraidseasons')

    async def get_clan_members(self, clan_tag: str):
        return await self.get_data(f'https://api.clashofclans.com/v1/clans/'
                                   f'{urllib.parse.quote(clan_tag)}/members')

    async def get_player(self, player_tag: str):
        return await self.get_data(f'https://api.clashofclans.com/v1/players/'
                                   f'{urllib.parse.quote(player_tag)}')
