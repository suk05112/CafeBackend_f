import os
import logging
import json
from datetime import datetime, timezone, timedelta

import boto3
import watchtower

from core.config import settings

KST = timezone(timedelta(hours=9))

SYSTEM_LOG_GROUP = "gifnut-backend-system"
SYSTEM_LOG_STREAM = "system"


class KSTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, KST)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y-%m-%d %H:%M:%S')


def _build_system_logger() -> logging.Logger:
    boto3_client = boto3.client(
        'logs',
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name='ap-northeast-2',
    )
    handler = watchtower.CloudWatchLogHandler(
        boto3_client=boto3_client,
        log_group_name=SYSTEM_LOG_GROUP,
        log_stream_name=SYSTEM_LOG_STREAM,
        use_queues=True,
    )
    formatter = KSTFormatter(
        '%(asctime)s [KST] - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    handler.setFormatter(formatter)
    handler.setLevel(logging.WARNING)

    log = logging.getLogger("gifnut-system")
    log.addHandler(handler)
    log.setLevel(logging.WARNING)
    log.propagate = False
    return log


system_logger = _build_system_logger()

ENV = os.getenv("ENV", "dev")


def _payload(category: str, **kwargs) -> str:
    data = {
        "env": ENV,
        "category": category,
        "timestamp": datetime.now(KST).isoformat(),
        **kwargs,
    }
    return json.dumps(data, ensure_ascii=False, default=str)


def log_external_api_error(service: str, detail: str, exc: BaseException | None = None) -> None:
    system_logger.error(_payload(
        "EXTERNAL_API_ERROR",
        service=service,
        detail=detail,
        exception_type=type(exc).__name__ if exc else None,
        message=str(exc) if exc else None,
    ))


def log_db_error(detail: str, exc: BaseException | None = None) -> None:
    system_logger.error(_payload(
        "DB_ERROR",
        detail=detail,
        exception_type=type(exc).__name__ if exc else None,
        message=str(exc) if exc else None,
    ))


def log_process_event(event: str, detail: str = "") -> None:
    """startup / shutdown 이벤트 로깅 (WARNING 레벨로 수집)"""
    system_logger.warning(_payload(
        "PROCESS_EVENT",
        event=event,
        detail=detail,
    ))


def log_scheduler_error(job: str, exc: BaseException) -> None:
    import traceback
    system_logger.error(_payload(
        "SCHEDULER_ERROR",
        job=job,
        exception_type=type(exc).__name__,
        message=str(exc),
        traceback=traceback.format_exc(),
    ))


def log_rate_limit(client_ip: str, path: str) -> None:
    system_logger.warning(_payload(
        "RATE_LIMIT_EXCEEDED",
        client_ip=client_ip,
        path=path,
    ))


def log_app_startup_snapshot(snapshot: dict) -> None:
    system_logger.warning(_payload(
        "APP_STARTUP_SNAPSHOT",
        **snapshot,
    ))
