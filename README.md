# 考勤跨夜班与加班分段核算

面向制造企业薪酬核算员，处理采信、判定、核算、复核与归档。

## 启动

```bash
docker compose up --build -d
```

访问 http://localhost:18252 。初次启动自动运行脏样例，可切换 clean.csv 与 legacy.csv。顶部“运行批次”会重新计算，同源输入复用批次。

## 业务模块

- 打卡采信：`/m1_ingest`、`/api/m1_ingest`
- 班次日历：`/m2_mapping`、`/api/m2_mapping`
- 跨夜配对：`/m3_versions`、`/api/m3_versions`
- 缺卡复核：`/m4_segments`、`/api/m4_segments`
- 工时切段：`/m5_calculate`、`/api/m5_calculate`
- 薪资对账：`/m6_reconcile`、`/api/m6_reconcile`
- 可付裁决：`/m7_settle`、`/api/m7_settle`
- 周期归档：`/m8_archive`、`/api/m8_archive`

## 核心规则

跨夜按班次归属日配对，休息区间先扣除，再按法定日期和工时阈值切分倍率。完整数值、边界和异常定义见 `docs/DATA-DICTIONARY.md`。

可付裁决：每个班次在截止时只形成一份可付结果。打卡人与排班人一致按排班可付；不一致时须有截止前已批准的替班审批才付给实际打卡人，审批条款可改为调休；无有效审批、排班冲突、两人同顶一班一律挂起，挂起金额留痕但不进实发。应发合计恒等于本次实发加挂起加转调休。审批、排班或截止变化产生新批次，旧批次结果失效且禁止导出；同一输入复用同一批次，重复执行不重复付款；新输入计算失败时旧批次与原始记录保持不变。

替班样例 `substitute.csv` 需随参数提交，例如：

```json
{"roster":[{"employee":"E201","shift_day":"2026-10-01","shift_start":"22:00","shift_end":"06:00"}],
 "substitutions":[{"id":"SUB-1","shift_day":"2026-10-01","scheduled":"E201","actual":"E202","status":"已批准","approved_at":"2026-10-30T09:00:00+08:00","settle":"付薪"}],
 "cutoff":"2026-10-31T23:59:59+08:00"}
```

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

原始样例在 `sample_data/`。测试在 `tests/`。封存文件是单份CSV，含运行清单、计算证据、裁决结果、隔离原因与对账。复核需提交当前版本，陈旧复核返回409。

## 数据与限制

SQLite保存在records命名卷，普通重启与构建不会清除。确认可丢弃本项目数据后，运行 `docker compose down -v` 再启动可重置。单文件上限2MB；不接入外部业务系统；历史规则由本项目样例定义，不代表实际行业标准。
