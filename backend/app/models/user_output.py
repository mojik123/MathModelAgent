"""用户输出管理模块，负责论文结果的拼接、引用处理和保存。"""

import os
import re
from app.utils.data_recorder import DataRecorder
from app.schemas.A2A import WriterResponse
import json
import uuid


def clean_final_paper_markdown(text: str) -> str:
    """Remove wrapper text around final Markdown while preserving paper content."""
    cleaned = (text or "").strip()
    fence_match = re.match(
        r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$",
        cleaned,
        re.IGNORECASE,
    )
    if fence_match:
        cleaned = fence_match.group(1).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    try:
        from app.utils.paper_cleaner import clean_chinese_paper_markdown
        cleaned = clean_chinese_paper_markdown(cleaned)
    except Exception:
        cleaned = cleaned.strip() + "\n"
    return cleaned


class UserOutput:
    """管理建模任务的输出结果，处理引用编号、脚注和最终论文拼接。"""
    def __init__(
        self, work_dir: str, ques_count: int, data_recorder: DataRecorder | None = None
    ):
        self.work_dir = work_dir
        self.res: dict[str, dict] = {}
        self.data_recorder = data_recorder
        self.cost_time = 0.0
        self.initialized = True
        self.ques_count: int = ques_count
        self.footnotes = {}
        self._init_seq()

    def _init_seq(self):
        ques_str = [f"ques{i}" for i in range(1, self.ques_count + 1)]
        self.seq = [
            "firstPage",
            "toc",
            "RepeatQues",
            "analysisQues",
            "modelAssumption",
            "symbol",
            "eda",
            *ques_str,
            "sensitivity_analysis",
            "judge",
        ]

    def set_res(self, key: str, writer_response: WriterResponse):
        self.res[key] = {
            "response_content": writer_response.response_content,
            "footnotes": writer_response.footnotes,
        }

    def get_res(self):
        return self.res

    @staticmethod
    def _clip(text: str, max_len: int = 2500) -> str:
        """截断文本到指定长度，保留更多建模细节供后续章节使用。"""
        text = re.sub(r"\s+", " ", text or "").strip()
        if len(text) <= max_len:
            return text
        return text[:max_len] + "……"

    def get_model_build_solve(self) -> str:
        parts: list[str] = []
        for key, value in self.res.items():
            if not key.startswith("ques") or key == "ques_count":
                continue
            content = ""
            if isinstance(value, dict):
                content = str(value.get("response_content") or "")
            else:
                content = str(value or "")
            parts.append(f"{key}: {self._clip(content, 900)}")
        return "\n".join(parts)

    def replace_references_with_uuid(self, text: str) -> str:
        references = re.findall(r"\{\[\^(\d+)\]:\s*(.*?)\}", text, re.DOTALL)
        for ref_num, ref_content in references:
            ref_content = ref_content.strip().rstrip(".")
            existing_uuid = None
            for uuid_key, footnote_data in self.footnotes.items():
                if footnote_data["content"] == ref_content:
                    existing_uuid = uuid_key
                    break
            if existing_uuid:
                text = re.sub(
                    rf"\{{\[\^{ref_num}\]:.*?\}}",
                    f"[{existing_uuid}]",
                    text,
                    flags=re.DOTALL,
                )
            else:
                new_uuid = str(uuid.uuid4())
                self.footnotes[new_uuid] = {"content": ref_content}
                text = re.sub(
                    rf"\{{\[\^{ref_num}\]:.*?\}}",
                    f"[{new_uuid}]",
                    text,
                    flags=re.DOTALL,
                )
        return text

    def sort_text_with_footnotes(self, replace_res: dict) -> dict:
        sort_res = {}
        ref_index = 1
        for seq_key in self.seq:
            if seq_key not in replace_res:
                continue
            text = replace_res[seq_key]["response_content"]
            uuid_list = re.findall(r"\[([a-f0-9-]{36})\]", text)
            for uid in uuid_list:
                text = text.replace(f"[{uid}]", f"[^{ref_index}]")
                if self.footnotes[uid].get("number") is None:
                    self.footnotes[uid]["number"] = ref_index
                ref_index += 1
            sort_res[seq_key] = {"response_content": text}
        return sort_res

    def append_footnotes_to_text(self, text: str) -> str:
        if not self.footnotes:
            return text
        text += "\n\n## 参考文献"
        sorted_footnotes = sorted(
            self.footnotes.items(),
            key=lambda x: x[1].get("number", 10**9),
        )
        for _, footnote in sorted_footnotes:
            text += f"\n\n[^{footnote['number']}]: {footnote['content']}"
        return text

    def get_result_to_save(self) -> str:
        self.footnotes = {}
        replace_res = {}
        for key, value in self.res.items():
            new_text = self.replace_references_with_uuid(value["response_content"])
            replace_res[key] = {"response_content": new_text}
        sort_res = self.sort_text_with_footnotes(replace_res)
        full_res_1 = "\n\n".join(
            sort_res[key]["response_content"]
            for key in self.seq
            if key in sort_res
        )
        full_res = self.append_footnotes_to_text(full_res_1)
        return full_res

    def save_result(self, final_text: str | None = None):
        with open(os.path.join(self.work_dir, "res.json"), "w", encoding="utf-8") as f:
            json.dump(self.res, f, ensure_ascii=False, indent=4)

        res_path = os.path.join(self.work_dir, "res.md")
        text_to_save = (
            clean_final_paper_markdown(final_text)
            if final_text
            else clean_final_paper_markdown(self.get_result_to_save())
        )
        try:
            from app.utils.artifact_edits import apply_artifact_patches_to_markdown
            from app.utils.paper_cleaner import clean_chinese_paper_markdown
            text_to_save = apply_artifact_patches_to_markdown(text_to_save, self.work_dir)
            text_to_save = clean_chinese_paper_markdown(text_to_save)
        except Exception as exc:
            print(f"[artifact_edits] apply patches failed: {exc}")
        # 修正仅用 basename 引用的图片路径，确保持久化后路径包含子目录
        try:
            from app.utils.common_utils import normalize_markdown_image_paths
            text_to_save = normalize_markdown_image_paths(text_to_save, self.work_dir)
        except Exception as exc:
            print(f"[normalize_image_paths] failed: {exc}")
        with open(res_path, "w", encoding="utf-8") as f:
            f.write(text_to_save)