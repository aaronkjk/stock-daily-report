# -*- coding: utf-8 -*-
"""
[최초 1회만 실행] 카카오 인가코드 -> refresh_token 발급.

사용법:
  1) 브라우저에서 아래 주소 열고 로그인/동의 (REST_API_KEY, REDIRECT_URI 채우기):
     https://kauth.kakao.com/oauth/authorize?client_id=REST_API_KEY&redirect_uri=REDIRECT_URI&response_type=code&scope=talk_message

  2) 리다이렉트된 주소창의 ...?code=XXXX 에서 code 값을 복사

  3) 실행:
     REST_API_KEY=... REDIRECT_URI=... python get_token.py XXXX

출력된 refresh_token 을 GitHub Secret(KAKAO_REFRESH_TOKEN)에 저장하세요.
"""

import os
import sys
import requests

if len(sys.argv) < 2:
    print("사용법: python get_token.py <인가코드>")
    sys.exit(1)

code = sys.argv[1]
data = {
    "grant_type": "authorization_code",
    "client_id": os.environ["REST_API_KEY"],
    "redirect_uri": os.environ["REDIRECT_URI"],
    "code": code,
}
secret = os.environ.get("CLIENT_SECRET")
if secret:
    data["client_secret"] = secret

r = requests.post("https://kauth.kakao.com/oauth/token", data=data, timeout=15)
print("status:", r.status_code)
body = r.json()
print("access_token :", body.get("access_token", "(없음)"))
print("refresh_token:", body.get("refresh_token", "(없음)"))
print("\n→ refresh_token 을 GitHub Secret KAKAO_REFRESH_TOKEN 에 저장하세요.")
if "error" in body:
    print("에러:", body)
