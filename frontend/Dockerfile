ARG NODE_IMAGE=dockerproxy.com/library/node:20-alpine
FROM ${NODE_IMAGE}

WORKDIR /app

# 复制依赖文件
COPY package.json pnpm-lock.yaml ./

# 安装 pnpm
RUN npm config set registry https://registry.npmmirror.com && npm install -g pnpm

# 清理 npm 缓存并安装依赖
RUN pnpm config set registry https://registry.npmmirror.com && pnpm install --frozen-lockfile

# 复制源代码
COPY . .

EXPOSE 5174

# 运行开发服务器
CMD ["pnpm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5174", "--strictPort"]
