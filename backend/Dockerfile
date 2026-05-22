# 使用官方推荐的 Python 基础镜像
ARG PYTHON_IMAGE=dockerproxy.com/library/python:3.12-slim
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_LINK_MODE=copy

# 安装中文字体和 LaTeX PDF 编译环境（用于生成数学建模论文 PDF）
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk fonts-wqy-microhei \
    texlive-xetex \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-lang-chinese \
    latexmk \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv。使用 PyPI 镜像源，避免依赖 ghcr.io 镜像拉取。
RUN pip install --no-cache-dir uv

WORKDIR /app

# 先复制依赖文件，利用 Docker 层缓存
COPY pyproject.toml uv.lock ./

# 安装依赖（不安装项目本身，加快后续构建）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project

# 再复制项目代码
COPY . .

# 安装项目本身
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

EXPOSE 8000

# 开发模式下启用热重载，并把监听范围限制在 app 目录，减少无关文件扫描
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app", "--ws-ping-interval", "60", "--ws-ping-timeout", "120"]
