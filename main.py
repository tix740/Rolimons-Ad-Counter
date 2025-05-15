import requests
import json
import random
import os
import time
from typing import List, Dict, Any, Optional

PROXIES_FILE = 'proxies.txt'

def load_proxies() -> List[str]:
    if not os.path.exists(PROXIES_FILE):
        print(f"Warning: {PROXIES_FILE} not found. Running without proxies.")
        return []
    try:
        with open(PROXIES_FILE, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"Error loading proxies: {e}")
        return []

def get_random_proxy(proxies: List[str]) -> Optional[str]:
    return random.choice(proxies) if proxies else None
