"""
알리고 카카오 알림톡 발송 서비스

템플릿 목록:
  - UH_9771: 정산 완료 안내    변수: #{매장명}, #{정산기간}, #{정산금액}, #{은행명}, #{계좌번호}
  - UH_9772: 입점 심사 결과 안내  변수: #{심사결과}, #{상세사유}
"""
import json
import urllib.request
import urllib.parse
from dataclasses import dataclass
from typing import Optional
from loguru import logger
from core.config import settings

ALIGO_SEND_URL = "https://kakaoapi.aligo.in/akv10/alimtalk/send/"

CHANNEL_ADD_BUTTON = {
    "button": [{
        "name": "채널 추가",
        "linkType": "AC",
        "linkTypeName": "채널 추가",
        "linkMo": "",
        "linkPc": "",
        "linkIos": "",
        "linkAnd": "",
    }]
}


@dataclass
class AlimtalkRecipient:
    receiver: str        # 수신자 전화번호
    message: str         # 알림톡 본문 (템플릿 변수 치환 완료된 문자열)
    subject: str         # 알림톡 제목
    recvname: str = ""   # 수신자 이름 (선택)
    emtitle: str = ""    # 강조표기형 타이틀 (선택)


def _send(
    tpl_code: str,
    recipients: list[AlimtalkRecipient],
    button: Optional[dict] = None,
) -> dict:
    """
    알리고 알림톡 발송 공통 함수 (최대 500명)
    """
    if not recipients:
        return {"code": -1, "message": "수신자가 없습니다."}

    params: dict = {
        "apikey": settings.aligo_api_key,
        "userid": settings.aligo_user_id,
        "senderkey": settings.aligo_sender_key,
        "tpl_code": tpl_code,
        "sender": settings.aligo_sender,
    }

    for i, r in enumerate(recipients, start=1):
        params[f"receiver_{i}"] = r.receiver
        params[f"subject_{i}"] = r.subject
        params[f"message_{i}"] = r.message
        if r.recvname:
            params[f"recvname_{i}"] = r.recvname
        if r.emtitle:
            params[f"emtitle_{i}"] = r.emtitle
        if button:
            params[f"button_{i}"] = json.dumps(button, ensure_ascii=False)

    try:
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(ALIGO_SEND_URL, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as res:
            result = json.loads(res.read().decode("utf-8"))
            if result.get("code") == 0:
                logger.info(f"[알림톡] {tpl_code} 발송 성공 | mid={result['info']['mid']} scnt={result['info']['scnt']}")
            else:
                logger.error(f"[알림톡] {tpl_code} 발송 실패 | {result.get('message')}")
            return result
    except Exception as e:
        logger.error(f"[알림톡] {tpl_code} 발송 오류: {e}")
        return {"code": -1, "message": str(e)}


# ── 템플릿별 발송 함수 ──────────────────────────────────────────────────────────

def send_settlement_complete(
    receiver: str,
    store_name: str,
    period: str,
    amount: str,
    bank_name: str,
    account_number: str,
    recvname: str = "",
) -> dict:
    """UH_9771: 정산 완료 안내"""
    message = (
        f"안녕하세요, 사장님.\n"
        f"정산대금 지급이 완료되었습니다.\n\n"
        f"▪ 매장명: {store_name}\n"
        f"▪ 정산 기간: {period}\n"
        f"▪ 정산 금액: {amount}원\n"
        f"▪ 입금 계좌: {bank_name} ({account_number})"
    )
    recipient = AlimtalkRecipient(
        receiver=receiver,
        subject="정산 완료 안내",
        message=message,
        recvname=recvname,
    )
    return _send("UH_9771", [recipient], button=CHANNEL_ADD_BUTTON)


def send_store_review_result(
    receiver: str,
    result: str,
    detail: str,
    recvname: str = "",
) -> dict:
    """UH_9772: 입점 심사 결과 안내"""
    message = (
        f"입점 심사 결과를 안내해 드립니다.\n\n"
        f"■ 심사 결과: {result}\n"
        f"■ 상세 안내: {detail}\n\n"
        f"※ 메뉴가 등록된 매장은 승인 즉시 앱에 노출됩니다. "
        f"아직 메뉴를 등록하지 않으셨다면 사장님 앱에서 등록을 완료해 주세요."
    )
    recipient = AlimtalkRecipient(
        receiver=receiver,
        subject="입점 심사 결과 안내",
        message=message,
        recvname=recvname,
        emtitle="입점 심사 결과 안내",
    )
    return _send("UH_9772", [recipient], button=CHANNEL_ADD_BUTTON)
