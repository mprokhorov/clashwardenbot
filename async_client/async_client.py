import asyncio
import base64
import json
import logging
import time
import urllib.parse
from http import HTTPStatus
from typing import Optional

import httpx
from asyncio_throttle import Throttler

DEVELOPER_API_URL = 'https://developer.clashofclans.com/api'
KEY_UPDATE_INTERVAL_SECONDS = 60


class AsyncClient:
    def __init__(
            self,
            email: Optional[str] = None,
            password: Optional[str] = None,
            key_name: Optional[str] = None,
            key_description: Optional[str] = None,
            key: Optional[str] = None
    ):
        """
        An asynchronous Clash of Clans API client

        :param email: email address of the Clash of Clans API account
        :param password: password of the Clash of Clans API account
        :param key_name: name of key to be updated or created
        :param key_description: description of key to be updated or created
        :param key: existing key which will be used to connect to Clash of Clans API.
            If specified, overrides previous parameters.

        The key is retrieved on the first request, so creating the client never makes network requests
        and does not fail when the developer site is unavailable.
        """
        self.email = email
        self.password = password
        self.key_name = key_name
        self.key_description = key_description
        self.key = key

        self.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30))
        self.throttler = Throttler(rate_limit=20, period=1)
        self.key_lock = asyncio.Lock()
        self.key_updated_at = None

    async def update_key(self) -> bool:
        if self.email is None or self.password is None:
            return False
        async with self.key_lock:
            # Requests that got 403 at the same time wait for the lock and reuse the key updated by the first one,
            # and failed attempts are not repeated more often than once a minute
            if self.key_updated_at is not None and time.monotonic() - self.key_updated_at < KEY_UPDATE_INTERVAL_SECONDS:
                return self.key is not None
            self.key_updated_at = time.monotonic()
            try:
                self.key = await self.retrieve_key()
            except (httpx.HTTPError, KeyError, IndexError, ValueError):
                logging.exception('Clash of Clans API key was not updated')
                return False
            if self.key is None:
                logging.error('Clash of Clans API key was not found after update')
            return self.key is not None

    async def retrieve_key(self) -> Optional[str]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as session:
            login = await session.post(
                url=f'{DEVELOPER_API_URL}/login',
                json={'email': self.email, 'password': self.password}
            )
            login.raise_for_status()
            current_ip = json.loads(
                base64.b64decode(login.json()['temporaryAPIToken'].split('.')[1] + '====').decode('utf-8')
            )['limits'][1]['cidrs'][0].split('/')[0]
            retrieved_keys = (await session.post(url=f'{DEVELOPER_API_URL}/apikey/list')).json()['keys']
            key_to_update = next((key for key in retrieved_keys if key['name'] == self.key_name), None)
            if key_to_update is not None and current_ip in key_to_update['cidrRanges']:
                return key_to_update['key']
            if key_to_update is not None:
                await session.post(url=f'{DEVELOPER_API_URL}/apikey/revoke', json={'id': key_to_update['id']})
            await session.post(
                url=f'{DEVELOPER_API_URL}/apikey/create',
                json={
                    'cidrRanges': (key_to_update['cidrRanges'] if key_to_update is not None else []) + [current_ip],
                    'description': self.key_description,
                    'name': self.key_name,
                    'scopes': ['clash']
                }
            )
            updated_keys = (await session.post(url=f'{DEVELOPER_API_URL}/apikey/list')).json()['keys']
            await session.post(url=f'{DEVELOPER_API_URL}/logout')
            return next((key['key'] for key in updated_keys if key['name'] == self.key_name), None)

    async def request(self, url: str) -> httpx.Response:
        return await self.http_client.get(
            url=url,
            headers={'authorization': f'Bearer {self.key}', 'accept': 'application/json'}
        )

    async def get_data(self, url: str) -> Optional[dict]:
        if self.key is None:
            await self.update_key()
        async with self.throttler:
            try:
                response = await self.request(url)
                if response.status_code == HTTPStatus.FORBIDDEN and await self.update_key():
                    response = await self.request(url)
            except httpx.HTTPError as e:
                logging.warning(f'Clash of Clans API request {url} failed: {e!r}')
                return None
        if response.status_code != HTTPStatus.OK:
            return None
        try:
            return response.json()
        except ValueError:
            logging.warning(f'Clash of Clans API returned invalid JSON for {url}')
            return None

    async def get_clan(self, clan_tag: str):
        return await self.get_data(
            f'https://api.clashofclans.com/v1/clans/{urllib.parse.quote(clan_tag)}'
        )

    async def get_clan_current_war(self, clan_tag: str):
        return await self.get_data(
            f'https://api.clashofclans.com/v1/clans/{urllib.parse.quote(clan_tag)}/currentwar'
        )

    async def get_clan_war_league_group(self, clan_tag: str):
        return await self.get_data(
            f'https://api.clashofclans.com/v1/clans/{urllib.parse.quote(clan_tag)}/currentwar/leaguegroup'
        )

    async def get_clan_war_league_war(self, war_tag: str):
        return await self.get_data(
            f'https://api.clashofclans.com/v1/clanwarleagues/wars/{urllib.parse.quote(war_tag)}'
        )

    async def get_clan_capital_raid_seasons(self, clan_tag: str, limit: Optional[int] = None):
        return await self.get_data(
            f'https://api.clashofclans.com/v1/clans/{urllib.parse.quote(clan_tag)}/capitalraidseasons'
            f'{f'?limit={limit}' if limit is not None else ''}'
        )

    async def get_clan_members(self, clan_tag: str):
        return await self.get_data(
            f'https://api.clashofclans.com/v1/clans/{urllib.parse.quote(clan_tag)}/members'
        )

    async def get_player(self, player_tag: str):
        return await self.get_data(
            f'https://api.clashofclans.com/v1/players/{urllib.parse.quote(player_tag)}'
        )

    async def get_war_log(self, clan_tag: str):
        return await self.get_data(
            f'https://api.clashofclans.com/v1/clans/{urllib.parse.quote(clan_tag)}/warlog'
        )
