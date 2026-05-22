"""使用 LLM Vision 为生成图片自动生成专业描述文字。"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from app.config.setting import ApiType
from app.utils.log_util import logger

# --------------------------------------------------------------------------- #
# Prompt                                                                       #
# --------------------------------------------------------------------------- #

_DESCRIBE_PROMPT = (
    "请根据图片内容生成一段适合前端展示的图片描述文字，控制在100字左右。"
    "必须包含以下信息："
    "这张图主要用于做什么；"
    "图中的主要元素是什么；"
    "从图中可以看出什么结论、趋势或意义。"
    "要求语言简洁、专业、自然，符合数学建模论文的表达风格，"
    "不要写成分点列表，直接输出描述文字，不要有任何前缀或说明。"
)


# --------------------------------------------------------------------------- #
# Image helpers                                                                #
# --------------------------------------------------------------------------- #

def _encode_image(image_path: str) -> tuple[str, str]:
    """读取图片并返回 (base64_data, media_type)。"""
    suffix = Path(image_path).suffix.lower()
    media_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/png")
    with open(image_path, "rb") as fh:
        return base64.b64encode(fh.read()).decode(), media_type


def _openai_messages(prompt: str, b64: str, media_type: str) -> list[dict]:
    """构建 OpenAI 多模态 messages。"""
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{b64}",
                        "detail": "low",
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]


def _anthropic_messages(prompt: str, b64: str, media_type: str) -> list[dict]:
    """构建 Anthropic 多模态 messages。"""
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

async def generate_image_description(
    image_path: str,
    section_label: str,
    provider,  # app.core.llm.providers.base.BaseProvider
    model: str,
    api_key: str,
    base_url: str | None,
    api_type: ApiType | None,
    max_tokens: int = 300,
) -> str:
    """调用 LLM Vision 为单张图片生成专业描述。

    Args:
        image_path: 图片文件的绝对路径。
        section_label: 图片所属的章节描述（如"问题1的模型建立与求解"）。
        provider: LLM Provider 实例（BaseProvider 子类），直接复用 WriterAgent 的模型。
        model: 模型 ID。
        api_key: API 密钥。
        base_url: API base URL（可选）。
        api_type: API 类型，用于选择多模态消息格式（OpenAI / Anthropic）。
        max_tokens: 最大生成 token 数，默认 300 足够生成约 100 字描述。

    Returns:
        生成的图片描述文字，失败时返回空字符串。
    """
    if not os.path.exists(image_path):
        logger.warning(f"图片不存在，跳过 LLM 描述生成: {image_path}")
        return ""

    try:
        b64, media_type = _encode_image(image_path)
    except Exception as exc:
        logger.warning(f"读取图片失败，跳过描述生成: {image_path}: {exc}")
        return ""

    prompt = _DESCRIBE_PROMPT

    try:
        if api_type == ApiType.ANTHROPIC:
            messages = _anthropic_messages(prompt, b64, media_type)
        else:
            messages = _openai_messages(prompt, b64, media_type)

        response = await provider.call(
            messages=messages,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=max_tokens,
        )
        description = (response.content or "").strip()
        if description:
            logger.info(
                f"LLM 图片描述生成成功 [{Path(image_path).name}]: {description[:60]}…"
            )
        return description

    except Exception as exc:
        logger.warning(
            f"LLM 图片描述生成失败 [{Path(image_path).name}]: {exc}"
        )
        return ""
