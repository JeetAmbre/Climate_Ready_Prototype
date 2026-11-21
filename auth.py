"""Google OAuth 2.0 Authentication Helper for ClimateReady.

Uses google-auth-oauthlib and requests to authenticate users with Google.
Stores user profile in database and session.
"""
import os
import requests
from flask import session
from database import SessionLocal, User

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


def is_google_auth_configured():
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def get_google_provider_cfg():
    try:
        return requests.get(GOOGLE_DISCOVERY_URL, timeout=10).json()
    except Exception as e:
        print(f"[auth] Failed to fetch Google provider config: {e}")
        return None


def get_current_user():
    user_info = session.get("user")
    return user_info


def save_user_profile(user_info):
    db = SessionLocal()
    try:
        user_id = user_info.get("sub") or user_info.get("id") or user_info.get("email")
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            user = User(
                id=user_id,
                email=user_info.get("email", ""),
                name=user_info.get("name", ""),
                picture=user_info.get("picture", "")
            )
            db.add(user)
        else:
            user.name = user_info.get("name", user.name)
            user.picture = user_info.get("picture", user.picture)
        db.commit()
        return user_id
    finally:
        db.close()
