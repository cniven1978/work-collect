#!/bin/bash
# RSSHub Docker 部署脚本
# 用法: ./setup_rsshub.sh [install|start|stop|status|update_cookie]

set -euo pipefail

RSSHUB_DIR="${WORKSPACE:-/workspace/work-collect}/.rsshub"
COMPOSE_FILE="$RSSHUB_DIR/docker-compose.yml"
RSSHUB_PORT=1200

check_docker() {
    if ! command -v docker &>/dev/null; then
        echo "❌ Docker 未安装"
        echo ""
        echo "请先安装 Docker Desktop："
        echo "  macOS: https://docs.docker.com/desktop/install/mac-install/"
        echo "  Windows: https://docs.docker.com/desktop/install/windows-install/"
        echo "  Linux: curl -fsSL https://get.docker.com | sh"
        echo ""
        echo "安装后重新运行此脚本。"
        exit 1
    fi

    if ! docker info &>/dev/null 2>&1; then
        echo "❌ Docker 已安装但未运行"
        echo "请先启动 Docker Desktop，然后重新运行此脚本。"
        exit 1
    fi

    echo "✅ Docker 可用"
}

check_rsshub() {
    if curl -s --connect-timeout 3 "http://localhost:$RSSHUB_PORT" &>/dev/null; then
        return 0
    else
        return 1
    fi
}

do_install() {
    echo "📋 检查 Docker 环境..."
    check_docker

    echo "📁 创建 RSSHub 配置目录..."
    mkdir -p "$RSSHUB_DIR"

    echo "📝 生成 docker-compose.yml..."
    cat > "$COMPOSE_FILE" << COMPOSE
version: "3"
services:
  rsshub:
    image: diygod/rsshub:latest
    container_name: work-collect-rsshub
    restart: always
    ports:
      - "${RSSHUB_PORT}:1200"
    environment:
      NODE_ENV: production
      CACHE_TYPE: memory
      CACHE_EXPIRE: 7200
      ACCESS_KEY: \${RSSHUB_ACCESS_KEY:-}
      SOGOU_COOKIE: \${SOGOU_COOKIE:-}
      ALLOWLIST: "/wechat"
    volumes:
      - rsshub-cache:/app/lib/cache

volumes:
  rsshub-cache:
COMPOSE

    echo "🚀 拉取 RSSHub 镜像并启动..."
    cd "$RSSHUB_DIR"
    docker compose up -d

    echo "⏳ 等待 RSSHub 启动..."
    for i in $(seq 1 30); do
        if check_rsshub; then
            echo "✅ RSSHub 已启动: http://localhost:$RSSHUB_PORT"
            echo ""
            echo "测试微信路由："
            echo "  curl http://localhost:$RSSHUB_PORT/wechat/sogou/公众号微信号"
            return 0
        fi
        sleep 2
    done

    echo "❌ RSSHub 启动超时，请检查 Docker 日志："
    echo "  cd $RSSHUB_DIR && docker compose logs"
    exit 1
}

do_start() {
    check_docker
    if [ ! -f "$COMPOSE_FILE" ]; then
        echo "❌ RSSHub 未安装，请先运行: $0 install"
        exit 1
    fi
    cd "$RSSHUB_DIR"
    docker compose up -d
    echo "✅ RSSHub 已启动"
}

do_stop() {
    if [ -f "$COMPOSE_FILE" ]; then
        cd "$RSSHUB_DIR"
        docker compose down
        echo "✅ RSSHub 已停止"
    else
        echo "RSSHub 未安装"
    fi
}

do_status() {
    echo "Docker: $(command -v docker &>/dev/null && echo '✅ 已安装' || echo '❌ 未安装')"
    if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
        echo "Docker Daemon: ✅ 运行中"
    else
        echo "Docker Daemon: ❌ 未运行"
    fi
    if check_rsshub; then
        echo "RSSHub: ✅ 运行中 (http://localhost:$RSSHUB_PORT)"
    else
        echo "RSSHub: ❌ 未运行"
    fi
}

do_update_cookie() {
    local cookie="${1:?用法: $0 update_cookie 'SNUID=xxx; SUID=xxx; ABTEST=0|xxx'}"
    if [ ! -f "$COMPOSE_FILE" ]; then
        echo "❌ RSSHub 未安装"
        exit 1
    fi
    cd "$RSSHUB_DIR"
    SOGOU_COOKIE="$cookie" docker compose up -d
    echo "✅ Cookie 已更新，RSSHub 已重启"
}

case "${1:-status}" in
    install)       do_install ;;
    start)         do_start ;;
    stop)          do_stop ;;
    status)        do_status ;;
    update_cookie) do_update_cookie "${2:-}" ;;
    *)
        echo "用法: $0 {install|start|stop|status|update_cookie}"
        echo ""
        echo "命令说明："
        echo "  install        首次安装 RSSHub（检查 Docker + 拉镜像 + 启动）"
        echo "  start          启动已安装的 RSSHub"
        echo "  stop           停止 RSSHub"
        echo "  status         检查 Docker 和 RSSHub 状态"
        echo "  update_cookie  更新搜狗搜索 Cookie"
        exit 1
        ;;
esac
