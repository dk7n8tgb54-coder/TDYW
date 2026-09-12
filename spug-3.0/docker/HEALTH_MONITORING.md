# Docker 平台健康监控

Compose 启动 `tdyw` 后，还会启动独立的 `tdyw-health-probe` sidecar。它不运行在 `tdyw` 容器内，而是通过 Docker network 请求 `http://tdyw/api/document/health/`，验证 Nginx、Django、DB、Redis 和存储的完整链路。

## 启动

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml ps
docker logs -f tdyw-health-probe
```

`tdyw-health-probe` 使用与主服务相同的应用镜像，但覆盖 entrypoint，只运行 `docker/scripts/health_probe.py`。它每 60 秒写入一次 `/var/log/tdyw/health-probe.jsonl`。该目录通过 Docker named volume `tdyw-health-probe-logs` 与 `tdyw` 共享，主容器以只读方式读取。

## 配置

在 `docker/.env` 中可调整：

```dotenv
HEALTH_PROBE_URL=http://tdyw/api/document/health/
HEALTH_PROBE_INTERVAL=60
```

如需从真实外部入口探测，可将 `HEALTH_PROBE_URL` 改为外部域名或反向代理地址，但探针仍保持在独立容器中。

## 日志与轮转

Nginx 将结构化日志写入 `run_metrics.log`，探活 sidecar 负责按大小轮转：探活日志最多保留 30 个轮转文件，Nginx 运行日志最多保留 14 个轮转文件；大小上限分别为 50 MB 和 200 MB。轮转失败只记录为降级，不会阻塞探活请求。

## 查看状态

登录平台后进入“运维管理 → 系统监控 → 平台健康”。探活数据缺失时页面显示“未知”，不会显示为健康。具体异常详情仍在“系统告警”Tab 查看。
