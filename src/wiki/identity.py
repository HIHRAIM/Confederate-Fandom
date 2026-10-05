"""Confirm that a Fandom staff profile names the Discord command caller.

The Fandom user API resolves a name to a numeric user id. Fandom's public
user-attribute service exposes the Discord handle set on that profile. The
handle must equal the caller's unique Discord username, including a legacy
discriminator when one is present. Network failure never proves ownership.
"""
import aiohttp

_USERS_API = "https://community.fandom.com/api.php"
_HANDLE_API = "https://services.fandom.com/user-attribute/user/{uid}/attr/discordHandle"
_HEADERS = {"User-Agent": "Confederate-Fandom-bot/1.0 (wiki task bot)"}

async def profile_discord_handle(name):
    """The public handle attached to this Fandom account, or None."""
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(_USERS_API, params={
                "action": "query", "list": "users", "ususers": name,
                "format": "json"}, headers=_HEADERS) as response:
            response.raise_for_status()
            data = await response.json()
        users = data.get("query", {}).get("users", [])
        if not users or "userid" not in users[0] or "missing" in users[0]:
            return None
        url = _HANDLE_API.format(uid=int(users[0]["userid"]))
        async with session.get(url, headers=_HEADERS) as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            attribute = await response.json()
        if isinstance(attribute, dict) and attribute.get("name") == "discordHandle":
            return (attribute.get("value") or "").strip() or None
    return None

def handle_matches(fandom_handle, discord_name):
    """Compare authenticated Discord username to the Fandom profile field."""
    return bool(fandom_handle) and fandom_handle.strip().lstrip("@").casefold() == (
        discord_name or "").strip().lstrip("@").casefold()
