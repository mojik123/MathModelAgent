"""通用工具函数模块，提供任务 ID 生成、文件操作和文档转换等功能。"""

import os
import shutil
import datetime
import hashlib
import tomllib
import subprocess
from pathlib import Path
from app.schemas.enums import CompTemplate
from app.utils.log_util import logger
import re
import pypandoc  # type: ignore[import-unresolved]
from app.config.setting import settings
from app.utils.image_constants import IMAGE_EXTENSION_RE_FRAGMENT, is_image_file

TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def create_task_id() -> str:
    """生成基于时间戳和随机哈希的唯一任务 ID。"""
    # 生成时间戳和随机hash
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    random_hash = hashlib.md5(str(datetime.datetime.now()).encode()).hexdigest()[:8]
    return f"{timestamp}-{random_hash}"


def ensure_safe_task_id(task_id: str) -> str:
    """验证任务 ID 的合法性，防止路径遍历攻击。

    Args:
        task_id: 待验证的任务 ID。

    Returns:
        验证通过的任务 ID。

    Raises:
        ValueError: 任务 ID 不合法时抛出。
    """
    normalized = (task_id or "").strip()
    if not normalized or not TASK_ID_PATTERN.fullmatch(normalized):
        raise ValueError("非法 task_id")
    return normalized


def create_work_dir(task_id: str) -> str:
    """为指定任务创建工作目录，并复制字体文件到工作目录。

    Args:
        task_id: 任务 ID。

    Returns:
        工作目录路径。
    """
    # 设置主工作目录和子目录
    work_dir = os.path.join("project", "work_dir", task_id)

    try:
        # 创建目录，如果目录已存在也不会报错
        os.makedirs(work_dir, exist_ok=True)
        # 复制字体文件到工作目录，确保图表中文正常显示
        _copy_fonts_to_work_dir(work_dir)
        _copy_cumcm_class_to_work_dir(work_dir)
        return work_dir
    except Exception as e:
        # 捕获并记录创建目录时的异常
        logger.error(f"创建工作目录失败: {str(e)}")
        raise


# 字体源目录（backend/fonts/）
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fonts")
_CONFIG_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "config"))
_CUMCM_PANDOC_TEMPLATE = os.path.join(_CONFIG_DIR, "cumcm_pandoc_template.tex")
_CUMCM_CLASS_FILENAME = "cumcmthesis.cls"
_CUMCM_CLASS_CANDIDATES = [
    Path("/third_party/CUMCMThesis") / _CUMCM_CLASS_FILENAME,
    Path(__file__).resolve().parents[3]
    / "third_party"
    / "CUMCMThesis"
    / _CUMCM_CLASS_FILENAME,
    Path(_CONFIG_DIR) / _CUMCM_CLASS_FILENAME,
]


def _copy_fonts_to_work_dir(work_dir: str) -> None:
    """将后端字体目录中的字体文件复制到工作目录。

    Args:
        work_dir: 目标工作目录路径。
    """
    fonts_dir = os.path.normpath(_FONTS_DIR)
    if not os.path.isdir(fonts_dir):
        logger.warning(f"字体目录不存在: {fonts_dir}")
        return

    for filename in os.listdir(fonts_dir):
        if not filename.lower().endswith((".ttf", ".otf", ".ttc")):
            continue
        src = os.path.join(fonts_dir, filename)
        dst = os.path.join(work_dir, filename)
        try:
            shutil.copy2(src, dst)
            logger.debug(f"复制字体: {filename} -> {work_dir}")
        except Exception as e:
            logger.warning(f"复制字体 {filename} 失败: {e}")


def _copy_cumcm_class_to_work_dir(work_dir: str) -> None:
    """Make the CUMCM LaTeX class discoverable for xelatex."""
    target = Path(work_dir) / _CUMCM_CLASS_FILENAME
    if target.exists() and "\\RequirePackage{ulem}" not in target.read_text(
        encoding="utf-8", errors="ignore"
    ):
        return

    for source in _CUMCM_CLASS_CANDIDATES:
        if source.exists():
            try:
                content = source.read_text(encoding="utf-8", errors="ignore")
                content = content.replace(
                    "\\RequirePackage{ulem}",
                    "\n".join(
                        [
                            "% ulem.sty is not available in all slim TeX runtimes.",
                            "\\providecommand{\\ULthickness}{0.4pt}",
                            "\\newlength{\\ULdepth}",
                            "\\providecommand{\\uline}[1]{\\underline{#1}}",
                        ]
                    ),
                )
                target.write_text(content, encoding="utf-8")
                logger.debug(f"复制 CUMCM LaTeX 类文件: {source} -> {target}")
                return
            except Exception as exc:
                logger.warning(f"复制 CUMCM LaTeX 类文件失败 {source} -> {target}: {exc}")

    logger.warning(
        "未找到 cumcmthesis.cls，PDF 编译可能失败；已检查："
        + "、".join(str(path) for path in _CUMCM_CLASS_CANDIDATES)
    )


def get_work_dir(task_id: str) -> str:
    """获取指定任务的工作目录路径。

    Args:
        task_id: 任务 ID。

    Returns:
        工作目录路径。

    Raises:
        FileNotFoundError: 工作目录不存在时抛出。
    """
    work_dir = os.path.join("project", "work_dir", task_id)
    if os.path.exists(work_dir):
        return work_dir
    else:
        logger.error(f"工作目录不存在: {work_dir}")
        raise FileNotFoundError(f"工作目录不存在: {work_dir}")


# TODO: 是不是应该将 Prompt 写成一个 class
def get_config_template(comp_template: CompTemplate = CompTemplate.CHINA) -> dict:
    """获取论文模板配置。

    Args:
        comp_template: 竞赛模板类型。

    Returns:
        模板配置字典。
    """
    if comp_template == CompTemplate.CHINA:
        template = load_toml(os.path.join("app", "config", "md_template.toml"))
        template.setdefault("image_caption", template.get("image_caption", ""))
        return template
    return {}


def load_toml(path: str) -> dict:
    """加载 TOML 配置文件。

    Args:
        path: TOML 文件路径。
    """
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_markdown(path: str) -> str:
    """加载 Markdown 文件内容。

    Args:
        path: Markdown 文件路径。
    """
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_current_files(folder_path: str, type: str = "all") -> list[str]:
    """获取指定目录下的文件列表（含子目录，路径相对于 folder_path）。

    Args:
        folder_path: 目录路径。
        type: 文件类型过滤（all/md/ipynb/data/image）。
    """
    root = Path(folder_path)

    def _relative(path: Path) -> str:
        try:
            return str(path.relative_to(root).as_posix())
        except ValueError:
            return path.name

    if type == "all":
        return sorted(
            _relative(p)
            for p in root.rglob("*")
            if p.is_file() and not p.name.startswith(".")
        )
    elif type == "md":
        return sorted(
            _relative(p) for p in root.rglob("*.md") if p.is_file()
        )
    elif type == "ipynb":
        return sorted(
            _relative(p) for p in root.rglob("*.ipynb") if p.is_file()
        )
    elif type == "data":
        return sorted(
            _relative(p)
            for p in root.rglob("*")
            if p.is_file() and p.suffix.lower() in (".xlsx", ".csv")
        )
    elif type == "image":
        return sorted(
            _relative(p) for p in root.rglob("*") if p.is_file() and is_image_file(p.name)
        )
    return []


def _build_image_basename_map(work_dir: str) -> dict[str, str]:
    """构建 basename → 相对路径 的映射，用于修正仅含基名的图片引用。

    Args:
        work_dir: 任务工作目录绝对/相对路径。

    Returns:
        小写 basename 到相对路径的映射，如 ``{"fig1.png": "5.1_xxx/fig1.png"}``。
    """
    mapping: dict[str, str] = {}
    root = Path(work_dir)
    if not root.is_dir():
        return mapping
    for p in root.rglob("*"):
        if p.is_file() and is_image_file(p.name):
            rel = p.relative_to(root).as_posix()
            key = p.name.lower()
            # 子目录中的图片优先（basename 冲突时保留第一个）
            if key not in mapping or "/" in rel:
                mapping[key] = rel
    return mapping


def resolve_image_path(work_dir: str, filename: str) -> str:
    """将图片文件名解析为相对于 work_dir 的实际路径。

    如果给定路径已直接存在，原样返回；否则在子目录中查找同名文件。

    Args:
        work_dir: 任务工作目录。
        filename: 图片文件名（可能是 basename 或包含子目录的相对路径）。

    Returns:
        解析后的相对路径。
    """
    normalized = filename.replace("\\", "/")
    if os.path.isfile(os.path.join(work_dir, normalized)):
        return normalized
    # 在子目录中按 basename 查找
    basename = os.path.basename(normalized).lower()
    root = Path(work_dir)
    for p in root.rglob("*"):
        if p.is_file() and p.name.lower() == basename:
            return p.relative_to(root).as_posix()
    return normalized


def normalize_markdown_image_paths(content: str, work_dir: str) -> str:
    """修正 Markdown 中仅用 basename 引用的图片路径，补全子目录前缀。

    Args:
        content: Markdown 文本。
        work_dir: 任务工作目录。

    Returns:
        图片路径已修正的 Markdown 文本。
    """
    basename_map = _build_image_basename_map(work_dir)

    def _fix(match: re.Match) -> str:
        alt = match.group(1)
        src = match.group(2)
        normalized = src.replace("\\", "/")
        # 已包含子目录的路径不修正
        if "/" in normalized:
            return match.group(0)
        key = os.path.basename(normalized).lower()
        resolved = basename_map.get(key, normalized)
        if resolved != normalized:
            return f"![{alt}]({resolved})"
        return match.group(0)

    return re.sub(
        rf"!\[(.*?)\]\((.*?\.{IMAGE_EXTENSION_RE_FRAGMENT})\)",
        _fix,
        content,
    )


def transform_link(task_id: str, content: str):
    """将 Markdown 中的图片链接转换为静态资源 URL。

    同时将仅用 basename 引用的图片路径修正为包含子目录的完整相对路径，
    确保静态文件服务可以正确定位图片。

    Args:
        task_id: 任务 ID，用于构建 URL 路径。
        content: 包含图片链接的 Markdown 文本。
    """
    work_dir = get_work_dir(task_id)
    basename_map = _build_image_basename_map(work_dir)

    def _replace(match: re.Match) -> str:
        alt = match.group(1)
        src = match.group(2)
        normalized = src.replace("\\", "/")
        # 如果是 basename 且在子目录中有对应文件，替换为完整路径
        if "/" not in normalized:
            key = os.path.basename(normalized).lower()
            normalized = basename_map.get(key, normalized)
        return f"![{alt}]({settings.SERVER_HOST}/static/{task_id}/{normalized})"

    content = re.sub(
        rf"!\[(.*?)\]\((.*?\.{IMAGE_EXTENSION_RE_FRAGMENT})\)",
        _replace,
        content,
    )
    return content


def md_2_docx(task_id: str):
    """将 Markdown 论文转换为 DOCX 格式。

    Args:
        task_id: 任务 ID。
    """
    work_dir = get_work_dir(task_id)
    md_path = os.path.join(work_dir, "res.md")
    docx_path = os.path.join(work_dir, "res.docx")

    extra_args = [
        "--resource-path",
        str(work_dir),
        "--mathml",  # MathML 格式公式
        "--standalone",
    ]

    pypandoc.convert_file(
        source_file=md_path,
        to="docx",
        outputfile=docx_path,
        format="markdown+tex_math_dollars",
        extra_args=extra_args,
    )
    print(f"转换完成: {docx_path}")
    logger.info(f"转换完成: {docx_path}")


def md_2_tex(task_id: str) -> str:
    """将 Markdown 论文转换为 LaTeX 源文件。

    Args:
        task_id: 任务 ID。

    Returns:
        生成的 .tex 文件路径。
    """
    work_dir = get_work_dir(task_id)
    _copy_cumcm_class_to_work_dir(work_dir)
    md_path = os.path.join(work_dir, "res.md")
    tex_path = os.path.join(work_dir, "res.tex")
    title = _extract_markdown_title(md_path)
    pandoc_md_path = _write_cumcm_markdown_source(md_path, work_dir)

    extra_args = [
        "--resource-path",
        str(work_dir),
        "--standalone",
        "--wrap=none",
        f"--template={_CUMCM_PANDOC_TEMPLATE}",
        "--metadata",
        f"title={title}",
    ]

    pypandoc.convert_file(
        source_file=pandoc_md_path,
        to="latex",
        outputfile=tex_path,
        format="markdown+tex_math_dollars+tex_math_single_backslash",
        extra_args=extra_args,
    )
    print(f"转换完成: {tex_path}")
    logger.info(f"转换完成: {tex_path}")
    return tex_path


def _write_cumcm_markdown_source(md_path: str, work_dir: str) -> str:
    """Create a Pandoc source file without a duplicated first level-1 title."""
    source_path = os.path.join(work_dir, "res_cumcm_source.md")
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            source_text = f.read()

        try:
            from app.utils.paper_cleaner import clean_chinese_paper_markdown

            source_text = clean_chinese_paper_markdown(source_text)
        except Exception as exc:
            logger.warning(f"清洗 CUMCM Markdown 中间文件失败: {exc}")

        lines = source_text.splitlines(keepends=True)

        output_lines: list[str] = []
        removed_title = False
        for line in lines:
            stripped = line.strip()
            if not removed_title and not output_lines and stripped.startswith("# "):
                removed_title = True
                continue
            output_lines.append(line)

        with open(source_path, "w", encoding="utf-8") as f:
            f.writelines(output_lines)
        return source_path
    except Exception as e:
        logger.warning(f"生成 CUMCM Markdown 中间文件失败: {e}")
        return md_path


def _extract_markdown_title(md_path: str) -> str:
    """Return the first level-1 Markdown heading as the LaTeX document title."""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("# ") and not stripped.startswith("## "):
                    return stripped[2:].strip() or "数学建模论文"
    except Exception as e:
        logger.warning(f"读取 Markdown 标题失败: {e}")
    return "数学建模论文"


def tex_2_pdf(task_id: str) -> str:
    """使用 xelatex 将 res.tex 编译为 PDF。

    Raises:
        RuntimeError: LaTeX 环境缺失或编译失败，错误信息包含具体原因。
    """
    work_dir = os.path.abspath(get_work_dir(task_id))
    _copy_cumcm_class_to_work_dir(work_dir)
    tex_path = os.path.join(work_dir, "res.tex")
    pdf_path = os.path.join(work_dir, "res.pdf")

    if not os.path.exists(tex_path):
        raise RuntimeError(f"LaTeX 源文件不存在: {tex_path}")

    if shutil.which("xelatex") is None:
        raise RuntimeError(
            "未检测到 xelatex，请安装 TeX Live 并确保 xelatex 在 PATH 中"
        )

    cmd = [
        "xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-output-directory",
        work_dir,
        os.path.basename(tex_path),
    ]

    last_stderr = ""
    for _ in range(2):
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            last_stderr = result.stderr or result.stdout or ""
            # 提取关键错误行（去掉 xelatex 的冗长输出）
            error_lines = [
                line.strip()
                for line in last_stderr.split("\n")
                if line.strip()
                and (line.startswith("!") or "Error" in line or "Fatal" in line)
            ]
            key_error = "\n".join(error_lines[:10]) if error_lines else last_stderr[-500:]
            logger.error(f"PDF 编译失败:\n{key_error}")
            raise RuntimeError(f"xelatex 编译失败:\n{key_error}")

    if not os.path.exists(pdf_path):
        raise RuntimeError(
            f"xelatex 执行完成但未生成 PDF: {pdf_path}"
        )

    logger.info(f"PDF 生成完成: {pdf_path}")
    return pdf_path


def md_2_pdf(task_id: str) -> str:
    """从 Markdown 生成 res.tex，并编译为 PDF。

    Raises:
        RuntimeError: 转换或编译失败，错误信息包含具体原因。
    """
    try:
        md_2_tex(task_id)
    except Exception as e:
        raise RuntimeError(f"Markdown 转 LaTeX 失败: {e}") from e

    return tex_2_pdf(task_id)


def split_footnotes(text: str) -> tuple[str, list[tuple[str, str]]]:
    """从文本中分离正文和脚注。

    Args:
        text: 包含脚注的完整文本。

    Returns:
        (正文, 脚注列表) 的元组，脚注格式为 (编号, 内容)。
    """
    main_text = re.sub(
        r"\n\[\^\d+\]:.*?(?=\n\[\^|\n\n|\Z)", "", text, flags=re.DOTALL
    ).strip()

    # 匹配脚注定义
    footnotes = re.findall(r"\[\^(\d+)\]:\s*(.+?)(?=\n\[\^|\n\n|\Z)", text, re.DOTALL)
    logger.info(f"main_text:{main_text} \n footnotes:{footnotes}")
    return main_text, footnotes
