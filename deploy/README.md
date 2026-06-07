# Berry 部署指南

目标:把 berry 跑在云服务器(Ubuntu 24.04),浏览器访问 `http://<server-ip>` 直接用。

## 一、服务器初始化(只做一次)

```bash
# SSH 上去,先做基础加固
ssh ubuntu@124.221.210.50

# 1) 系统更新
sudo apt update && sudo apt upgrade -y

# 2) 装 docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER     # 之后 docker 不用 sudo
newgrp docker                     # 当前会话立即生效

# 3) 防火墙:只放 SSH 和 HTTP
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw enable

# 4) 验证
docker version
docker compose version
sudo ufw status
```

## 二、上传代码

两种选择,任选其一:

```bash
# 方式 A:git clone(推荐 — 后续 git pull 升级)
sudo apt install -y git
git clone <你的仓库地址> ~/berry
cd ~/berry

# 方式 B:本地 rsync(暂时还没 push 到 git 时用)
# 在你本地机器跑:
rsync -avz --exclude='.venv' --exclude='node_modules' --exclude='data' \
    ~/PROJECT/MYSELF/berry/ ubuntu@124.221.210.50:~/berry/
```

## 三、配置凭证

```bash
cd ~/berry
cp deploy/env.production.example .env.production
nano .env.production              # 填真实的 key
chmod 600 .env.production         # 权限收紧
```

至少要填:
- `POSTGRES_PASSWORD` — 用 `openssl rand -base64 32` 生成
- `DEEPSEEK_KEY` 或 `ANTHROPIC_API_KEY` — 至少有一个

## 四、构建并启动

```bash
cd ~/berry

# 第一次构建(可能要 5-10 分钟,装依赖 + 前端构建)
docker compose build

# 启动
docker compose up -d

# 跑数据库迁移
docker compose exec berry alembic upgrade head

# 查看状态
docker compose ps
docker compose logs -f berry
```

浏览器打开 `http://124.221.210.50` 应该能看见前端。

## 五、日常运维

```bash
cd ~/berry

# 拉新代码 + 重新构建 + 重启
git pull
docker compose build
docker compose up -d
docker compose exec berry alembic upgrade head    # 如果有新迁移

# 看日志
docker compose logs -f berry           # 后端
docker compose logs -f web             # nginx
docker compose logs --since 1h berry   # 最近 1 小时

# 进容器排查
docker compose exec berry bash
docker compose exec postgres psql -U berry -d berry

# 备份数据库
docker compose exec postgres pg_dump -U berry berry > backup-$(date +%Y%m%d).sql

# 完全停掉(数据卷保留)
docker compose down

# 加上 redis(以后需要时)
docker compose --profile redis up -d
```

## 六、出问题排查

| 症状 | 看哪 |
|---|---|
| 浏览器 502 | `docker compose logs web` —— nginx 转发失败,通常是 berry 没起来 |
| 浏览器空白页 | 前端构建失败,看 `docker compose logs web` |
| API 报 DB 错 | `docker compose ps` 看 postgres 是否 healthy;迁移没跑就 `alembic upgrade head` |
| LLM 不响应 | `.env.production` 里 key 没填或填错 |
| 流式回复卡住 | nginx 的 `proxy_buffering off` 没生效,检查 `deploy/nginx.conf` |

## 七、安全提醒

- `.env.production` 永远 `chmod 600`,绝不进 git
- 只对外暴露 80 端口,8000 / 5432 都只在 docker 网络内可见
- 定期 `docker compose pull` + 重建,跟上基础镜像安全补丁
- 备份 `berry_pgdata` 卷:`docker run --rm -v berry_pgdata:/data -v $(pwd):/backup alpine tar czf /backup/pg.tar.gz /data`
