# -*- coding: utf-8 -*-
"""
카카오톡 '나에게 보내기' 헬퍼.
- refresh_token 으로 access_token 재발급 (access token 은 몇 시간 만에 만료됨)
- 기본 텍스트 템플릿으로 나와의 채팅방에 메시지 발송 (최대 200자)

필요한 환경변수:
  KAKAO_REST_API_KEY   : 카카오 앱 REST API 키
  KAKAO_REFRESH_TOKEN  : 최초 1회 발급한 refresh token
  KAKAO_CLIENT_SECRET  : (선택) 앱에서 client secret 을 켰다면 필요
"""

import os
import json
import requests

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def get_access_token():
    data = {
        "grant_type": "refresh_token",
        "client_id": os.environ["KAKAO_REST_API_KEY"],
        "refresh_token": os.environ["KAKAO_REFRESH_TOKEN"],
    }
    secret = os.environ.get("KAKAO_CLIENT_SECRET")
    if secret:
        data["client_secret"] = secret

    r = requests.post(TOKEN_URL, data=data, timeout=15)
    r.raise_for_status()
    body = r.json()
    if "access_token" not in body:
        raise RuntimeError(f"토큰 발급 실패: {body}")
    # refresh_token 이 새로 내려오면(만료 임박 시) 로그로 남겨 갱신 유도
    if body.get("refresh_token"):
        print("[kakao] 새 refresh_token 발급됨 → GitHub Secret 갱신 권장:",
              body["refresh_token"][:8] + "...")
    return body["access_token"]


def send_kakao_memo(text, link_url=None, button_title="자세히 보기"):
    access_token = get_access_token()

    template = {
        "object_type": "text",
        "text": text,  # 최대 200자
        "link": {
            "web_url": link_url or "",
            "mobile_web_url": link_url or "",
        },
    }
    if link_url:
        template["button_title"] = button_title

    r = requests.post(
        MEMO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=15,
    )
    r.raise_for_status()
    result = r.json()
    if result.get("result_code") != 0:
        raise RuntimeError(f"메시지 발송 실패: {result}")
    return result
