from fastapi import Header, HTTPException, status
import hmac
import hashlib
import time
import json
from urllib.parse import parse_qsl

from typing import Optional

def validate_init_data(bot_token: str, init_data: str) -> Optional[dict]:
    try:
        # Parse query string
        params = dict(parse_qsl(init_data))
        if 'hash' not in params:
            return None

        received_hash = params.pop('hash')

        # Sort key-value pairs alphabetically
        sorted_params = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))

        # Create secret key: HMAC-SHA256 of bot token with "WebAppData" as key
        secret_key = hmac.new(b"WebAppData", bot_token.encode('utf-8'), hashlib.sha256).digest()

        # Calculate hash
        calculated_hash = hmac.new(secret_key, sorted_params.encode('utf-8'), hashlib.sha256).hexdigest()

        if received_hash != calculated_hash:
            return None

        # Check auth_date freshness (allow up to 1 hour)
        auth_date = int(params.get('auth_date', 0))
        now = int(time.time())
        if now - auth_date > 3600:
            return None

        # Parse user data
        user_str = params.get('user')
        if not user_str:
            return None

        return json.loads(user_str)
    except Exception as e:
        print("initData validation error:", e)
        return None

def get_auth_dependency(bot_token: str):
    async def dependency(x_telegram_init_data: str = Header(None, alias="X-Telegram-Init-Data")):
        if not x_telegram_init_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing initData"
            )
        
        user = validate_init_data(bot_token, x_telegram_init_data)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired initData"
            )
        
        return user
    return dependency
