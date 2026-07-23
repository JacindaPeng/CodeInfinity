"""阿里云 PNVS 短信认证服务（SendSmsVerifyCode / CheckSmsVerifyCode）。"""
from __future__ import annotations

import json
import logging

from ..config import settings

logger = logging.getLogger(__name__)


def _require_credentials() -> None:
    if not settings.aliyun_sms_access_key_id or not settings.aliyun_sms_access_key_secret:
        raise RuntimeError(
            "阿里云 AccessKey 未配置，请填写 ALIYUN_SMS_ACCESS_KEY_ID / ALIYUN_SMS_ACCESS_KEY_SECRET，"
            "或开启 SMS_DEV_MODE=1"
        )
    if not settings.aliyun_pnvs_sign_name or not settings.aliyun_pnvs_template_code:
        raise RuntimeError(
            "PNVS 签名/模板未配置，请在控制台「赠送签名/模板」页选择后填写 "
            "ALIYUN_PNVS_SIGN_NAME / ALIYUN_PNVS_TEMPLATE_CODE"
        )


def _create_client():
    try:
        from alibabacloud_dypnsapi20170525.client import Client as DypnsapiClient
        from alibabacloud_tea_openapi import models as open_api_models
    except ImportError as exc:
        raise RuntimeError(
            "未安装 PNVS SDK，请执行: pip install alibabacloud_dypnsapi20170525"
        ) from exc

    config = open_api_models.Config(
        access_key_id=settings.aliyun_sms_access_key_id,
        access_key_secret=settings.aliyun_sms_access_key_secret,
    )
    config.endpoint = "dypnsapi.aliyuncs.com"
    return DypnsapiClient(config)


def _out_id(scene: str, phone: str) -> str:
    return f"{scene}:{phone}"


def _raise_pnvs_error(action: str, exc: Exception) -> None:
    """将 SDK 异常转为可读 RuntimeError，避免 500。"""
    code = str(getattr(exc, "code", "") or "")
    message = str(getattr(exc, "message", "") or exc)
    detail = f"{code}: {message}" if code else message
    logger.error("[PNVS] %s failed: %s", action, detail, exc_info=exc)

    if "Forbidden.NoPermission" in code or "NoPermission" in code:
        raise RuntimeError(
            "AccessKey 无 PNVS 权限（需 dypns:SendSmsVerifyCode / CheckSmsVerifyCode）。"
            "当前为 RAM 子用户密钥：请在 RAM 控制台为其授权系统策略 AliyunDypnsFullAccess，"
            "或改用主账号 AccessKey。详见 https://help.aliyun.com/zh/ram/developer-reference/aliyundypnsfullaccess"
        ) from exc
    if "FUNCTION_NOT_OPENED" in code:
        raise RuntimeError(
            "未开通号码认证/短信认证功能，请登录 https://dypns.console.aliyun.com/functions 开启"
        ) from exc
    raise RuntimeError(f"短信服务异常: {detail}") from exc


def send_pnvs_verify_code(phone: str, scene: str) -> None:
    """发送验证码（PNVS 自动生成并下发）。"""
    if settings.sms_dev_mode:
        logger.info("[SMS_DEV] phone=%s scene=%s", phone, scene)
        return

    _require_credentials()
    from alibabacloud_dypnsapi20170525 import models as dypns_models
    from alibabacloud_tea_util import models as util_models

    ttl_min = max(1, settings.sms_code_ttl_seconds // 60)
    request = dypns_models.SendSmsVerifyCodeRequest(
        phone_number=phone,
        sign_name=settings.aliyun_pnvs_sign_name,
        template_code=settings.aliyun_pnvs_template_code,
        template_param=json.dumps(
            {"code": "##code##", "min": str(ttl_min)},
            ensure_ascii=False,
        ),
        country_code="86",
        out_id=_out_id(scene, phone),
        valid_time=settings.sms_code_ttl_seconds,
        interval=settings.sms_send_interval_seconds,
        code_type=1,
        code_length=6,
        duplicate_policy=1,
    )
    client = _create_client()
    try:
        response = client.send_sms_verify_code_with_options(request, util_models.RuntimeOptions())
    except Exception as exc:
        _raise_pnvs_error("send", exc)
    body = getattr(response, "body", None)
    code_val = getattr(body, "code", None) if body else None
    if code_val and str(code_val).upper() != "OK":
        message = getattr(body, "message", "") or "短信发送失败"
        logger.error("[PNVS] send failed phone=%s code=%s msg=%s", phone, code_val, message)
        raise RuntimeError(f"短信发送失败: {message}")


def check_pnvs_verify_code(phone: str, scene: str, code: str) -> bool:
    """核验验证码，成功返回 True。"""
    if settings.sms_dev_mode:
        return code == settings.sms_dev_code

    _require_credentials()
    from alibabacloud_dypnsapi20170525 import models as dypns_models
    from alibabacloud_tea_util import models as util_models

    request = dypns_models.CheckSmsVerifyCodeRequest(
        phone_number=phone,
        verify_code=code,
        country_code="86",
        out_id=_out_id(scene, phone),
    )
    client = _create_client()
    try:
        response = client.check_sms_verify_code_with_options(request, util_models.RuntimeOptions())
    except Exception as exc:
        _raise_pnvs_error("check", exc)
    body = getattr(response, "body", None)
    if not body:
        return False
    success = getattr(body, "success", None)
    if success is False:
        message = getattr(body, "message", "") or "验证码核验失败"
        logger.warning("[PNVS] check failed phone=%s msg=%s", phone, message)
        return False
    model = getattr(body, "model", None)
    result = getattr(model, "verify_result", None) if model else None
    return str(result).upper() == "PASS"
