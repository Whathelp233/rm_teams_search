# RMUC 2026 战术情报库

覆盖 96 支队伍、613 场区域赛的交互式战术检索网页。页面提供队伍画像、伤害来源、稳定战术、逐局指标、官方坐标热力图、逐局机器人路线和双队对比。

## 在线部署

`main` 分支发生变更后，GitHub Actions 会自动执行 Vite 构建并发布到 GitHub Pages：

<https://whathelp233.github.io/rm_teams_search/>

## 本地开发

```bash
npm ci
npm run dev
```

生产构建：

```bash
VITE_BASE_PATH=/rm_teams_search/ npm run build
```

## 数据口径

- 历史比赛规则：南部赛区使用 V1.4.2，东部和北部赛区使用 V1.5.0。
- 当前反制建议和行为树设计参考 V2.0.1。
- 空间统计只采用通信协议 V2.0.0 定义的官方 28×15m 坐标。
- 蓝方坐标统一为己方视角 `(28-x, 15-y)`。
- 行为树内部地图、区域 YAML 和 `sentry2_scau_two_mode_tunnel_overlay.png` 不参与位置映射。

`public/data` 保存网页所需的生成数据，`public/heatmaps` 保存官方坐标热力图。原始比赛数据库和规则 PDF 不进入本仓库。
