from __future__ import annotations
import argparse
from app.auth import create_hmac_token
from app.config import get_settings

def main():
    s=get_settings();p=argparse.ArgumentParser(description="Create a short-lived AutoDraft HMAC access token")
    p.add_argument("--organization",default=s.default_organization_id);p.add_argument("--user",default=s.default_user_id)
    p.add_argument("--role",choices=["viewer","staff","lawyer","admin","owner"],default="lawyer");p.add_argument("--ttl",type=int,default=3600)
    a=p.parse_args();print(create_hmac_token(secret=s.auth_hmac_secret,organization_id=a.organization,user_id=a.user,role=a.role,ttl_seconds=a.ttl))
if __name__=="__main__":main()
