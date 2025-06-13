import requests
import aiohttp
import asyncio
import lxml.html
import time
import random
import json
from datetime import datetime
from typing import Dict, List, Optional

# config
WEBHOOK_URL = "https://discord.com/api/webhooks/1382897013196324968/4xd_rwwMAdYv7FvdTDt0a7QMgQRxeIGfbcfEzX9UKjclvB8zMXmE8wYrtDPFrR2fsazS"
MAX_TRADE_ADS = 50
FETCH_INTERVAL = 20
TEMP_IGNORE_DAYS = 7

def load_file(filename: str) -> List[str]:
    try:
        with open(filename, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

def load_json(filename: str) -> dict:
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def get_headers() -> Dict[str, str]:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15"
    ]
    return {"User-Agent": random.choice(user_agents)}


class IgnoreManager:
    def __init__(self):
        self.perm_ignore = set(load_file("ignore_list.txt"))
        self.temp_ignore = load_json("temp_ignore_list.json")
        self.clean_temp_ignore()
    
    def clean_temp_ignore(self):
        current_time = datetime.now()
        to_remove = []
        
        for user_id, data in self.temp_ignore.items():
            try:
                added_date = datetime.fromisoformat(data.get("added_date", ""))
                if (current_time - added_date).days >= TEMP_IGNORE_DAYS:
                    to_remove.append(user_id)
            except ValueError:
                to_remove.append(user_id)
        
        for user_id in to_remove:
            del self.temp_ignore[user_id]
        
        if to_remove:
            self._save_temp_ignore()
    
    def should_ignore(self, user_id: int) -> bool:
        return str(user_id) in self.perm_ignore or str(user_id) in self.temp_ignore
    
    def add_to_perm_ignore(self, user_id: int):
        with open("ignore_list.txt", 'a') as f:
            f.write(f"{user_id}\n")
        self.perm_ignore.add(str(user_id))
    
    def add_to_temp_ignore(self, user_id: int, username: str, trade_count: int):
        self.temp_ignore[str(user_id)] = {
            "username": username,
            "added_date": datetime.now().isoformat(),
            "trade_ads_count": trade_count
        }
        self._save_temp_ignore()
    
    def _save_temp_ignore(self):
        with open("temp_ignore_list.json", 'w') as f:
            json.dump(self.temp_ignore, f, indent=2)

class RolimonsAPI:
    def __init__(self, proxies: List[str]):
        self.proxies = proxies
        self.item_details = {}
        self.load_items()
    
    def _get_proxy_dict(self) -> Optional[dict]:
        if not self.proxies:
            return None
        proxy = random.choice(self.proxies)
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}
    
    def load_items(self):
        try:
            response = requests.get("https://www.rolimons.com/itemapi/itemdetails", 
                                  headers=get_headers(), timeout=30)
            if response.ok:
                data = response.json().get("items", {})
                self.item_details = {
                    int(item_id): {
                        "name": details[0],
                        "acronym": details[1] or "",
                        "value": details[4] or 0
                    } for item_id, details in data.items()
                }
                print(f"Loaded {len(self.item_details)} items")
        except Exception as e:
            print(f"Failed to load item details: {e}")
    
    def get_recent_ads(self) -> List:
        try:
            response = requests.get("https://api.rolimons.com/tradeads/v1/getrecentads",
                                  proxies=self._get_proxy_dict(), headers=get_headers(), timeout=15)
            if response.ok:
                return response.json().get('trade_ads', [])
        except Exception as e:
            print(f"Error getting recent trade ads: {e}")
        return []
    
    async def get_tradead_count(self, session: aiohttp.ClientSession, user_id: int) -> Optional[int]:
        """get total trade ad count from profile"""
        url = f"https://www.rolimons.com/player/{user_id}"
        proxy = f"http://{random.choice(self.proxies)}" if self.proxies else None
        
        try:
            async with session.get(url, proxy=proxy, headers=get_headers(), timeout=15) as response:
                if response.status == 200:
                    content = await response.text()
                    doc = lxml.html.fromstring(content)
                    
                    xpaths = [
                        '//div[contains(@class, "trade-ads-created-container")]//span[contains(@class, "stat-data")]/text()',
                        '//h6[contains(text(), "Trade Ads Created")]/following-sibling::span/text()'
                    ]
                    
                    for xpath in xpaths:
                        elements = doc.xpath(xpath)
                        if elements:
                            return int(elements[0].strip().replace(',', ''))
        except Exception as e:
            print(f"Error checking user {user_id}: {e}")
        return None
    
    def get_avatar(self, user_id: int) -> Optional[str]:
        try:
            url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=false"
            response = requests.get(url, proxies=self._get_proxy_dict(), headers=get_headers(), timeout=10)
            if response.ok:
                data = response.json()
                if data.get('data'):
                    return data['data'][0]['imageUrl']
        except Exception:
            pass
        return None

class DiscordNotifier:
    def __init__(self, webhook_url: str, api: RolimonsAPI):
        self.webhook_url = webhook_url
        self.api = api
    
    def send_message(self, user_id: int, username: str, trade_count: int, trade_ad: List) -> bool:
        """send discord webhook message"""
        avatar_url = self.api.get_avatar(user_id)
        trade_content = self._format_trade(trade_ad)
        value = self._calc_value(trade_ad)
        
        color = 15844367 if trade_count <= 10 or trade_count <= MAX_TRADE_ADS * 0.1 else 5763719
        
        embed = {
            "title": f"🔥 New plug found: {username}",
            "description": f"User has posted **{trade_count:,}** trade ads",
            "color": color,
            "url": f"https://www.rolimons.com/player/{user_id}",
            "thumbnail": {"url": avatar_url} if avatar_url else {},
            "fields": [
                {
                    "name": "📊 Statistics",
                    "value": f"**Trade Ads:** {trade_count:,}\n**Trade Ad Value:** {value:,}",
                    "inline": True
                },
                {
                    "name": "💰 Trade Ad Content",
                    "value": trade_content,
                    "inline": False
                },
                {
                    "name": "🔗 Links",
                    "value": f"[Profile](https://www.rolimons.com/player/{user_id}) • [Trade Ad](https://www.rolimons.com/tradead/{trade_ad[0]}) • [Send Trade](https://www.roblox.com/users/{user_id}/trade)",
                    "inline": False
                }
            ],
            "footer": {"text": f"Found at {datetime.now().strftime('%H:%M:%S')}"}
        }
        
        try:
            response = requests.post(self.webhook_url, json={"embeds": [embed]})
            return response.status_code == 204
        except Exception as e:
            print(f"Discord webhook failed: {e}")
            return False
    
    def _format_trade(self, trade_ad: List) -> str:
        """format for discord embed"""
        items = trade_ad[4]["items"]
        if not items:
            return "*No items*"
        
        formatted = []
        for item_id in items[:5]:
            if item_id in self.api.item_details:
                item = self.api.item_details[item_id]
                name = item["name"]
                acronym = f" ({item['acronym']})" if item["acronym"] else ""
                value = f"{item['value']:,}" if item['value'] else "N/A"
                formatted.append(f"**{name}**{acronym} - {value}")
            else:
                formatted.append(f"Unknown Item (ID: {item_id})")
        
        if len(items) > 5:
            formatted.append(f"*...and {len(items) - 5} more items*")
        
        return "\n".join(formatted)
    
    def _calc_value(self, trade_ad: List) -> int:
        """calculate total value of items in trade ad"""
        return sum(self.api.item_details.get(item_id, {}).get("value", 0) 
                  for item_id in trade_ad[4]["items"])

async def process_trades(api: RolimonsAPI, notifier: DiscordNotifier, ignore_manager: IgnoreManager):
    """process recent trade ads"""
    trade_ads = api.get_recent_ads()
    if not trade_ads:
        return
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for ad in trade_ads:
            user_id, username = ad[2], ad[3]
            
            if not ignore_manager.should_ignore(user_id):
                tasks.append(check_user(session, api, notifier, ignore_manager, user_id, username, ad))
        
        if tasks:
            await asyncio.gather(*tasks)

async def check_user(session, api: RolimonsAPI, notifier: DiscordNotifier, 
                    ignore_manager: IgnoreManager, user_id: int, username: str, trade_ad: List):
    trade_count = await api.get_tradead_count(session, user_id)
    
    if trade_count is None:
        return
    
    if trade_count <= MAX_TRADE_ADS:
        if notifier.send_message(user_id, username, trade_count, trade_ad):
            ignore_manager.add_to_temp_ignore(user_id, username, trade_count)
    else:
        ignore_manager.add_to_perm_ignore(user_id)

def main():
    print("Starting Rolimons plug finder...")
    
    proxies = load_file("proxies.txt")
    api = RolimonsAPI(proxies)
    notifier = DiscordNotifier(WEBHOOK_URL, api)
    ignore_manager = IgnoreManager()
    
    if not api.item_details:
        print("Failed to load item details. Exiting.")
        return
    
    print(f"Loaded {len(proxies)} proxies" if proxies else "No proxies loaded")
    print(f"Checking every {FETCH_INTERVAL}s for users with ≤{MAX_TRADE_ADS} trade ads\n")
    
    try:
        while True:
            print(f"{datetime.now().strftime('%H:%M:%S')} - Checking for plugs...")
            asyncio.run(process_trades(api, notifier, ignore_manager))
            time.sleep(FETCH_INTERVAL)
    except KeyboardInterrupt:
        print("\nStopped by user")

if __name__ == "__main__":
    main()
