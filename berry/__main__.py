"""`python -m berry` / `uv run berry` 入口。"""

import uvicorn


def main() -> None:
    """启动 Berry 服务。"""
    # reload=True 在本地开发时自动重启,生产关掉
    # host=0.0.0.0 让 docker 容器外能访问
    uvicorn.run(
        "berry.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_config=None,  # 不让 uvicorn 接管 logging,我们自己用 structlog
    )


if __name__ == "__main__":
    main()
