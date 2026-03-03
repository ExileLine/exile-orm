# 异步原生 ORM 框架实现 TODO

> 目标：从 0 到 1 实现一个 Python 原生异步 ORM（`async/await`），先做可用 MVP，再逐步增强到生产级。

## 阶段 0：定义范围与技术选型

- [x] 明确首个支持数据库（建议先 `PostgreSQL`）。
- [x] 确定驱动（建议先 `asyncpg`，后续可扩展多驱动适配层）。
- [x] 明确 Python 版本（建议 `>=3.11`）。
- [x] 确定项目结构与代码风格（`ruff` + `mypy` + `pytest`）。
- [x] 定义 MVP 边界：
  - [x] 支持基础模型定义（字段、主键、默认值、可空）。
  - [x] 支持 CRUD（单表）。
  - [x] 支持简单查询（`filter/order_by/limit/offset`）。
  - [x] 支持异步事务（`async with transaction():`）。

完成标准：
- [x] 输出一页 `docs/architecture.md`（架构图、模块职责、MVP 范围）。

---

## 阶段 1：项目骨架与开发基础设施

- [x] 初始化目录结构：
  - [x] `exile_orm/core/`（连接、事务、异常）
  - [x] `exile_orm/model/`（Model、字段、元类）
  - [x] `exile_orm/query/`（表达式、SQL 生成器、QuerySet）
  - [x] `exile_orm/backends/`（postgres 实现）
  - [x] `tests/`（单元/集成测试）
  - [x] `examples/`（最小可运行示例）
- [x] 配置 `pyproject.toml`（依赖、lint、type check、pytest）。
- [x] 加入 CI（lint + type check + tests）。
- [x] 建立统一异常体系（`ORMError`, `ConnectionError`, `QueryError`, `IntegrityError` 等）。

完成标准：
- [x] 执行 `pytest` 可跑通空测试。
- [x] 执行 `ruff check`、`mypy` 无阻塞错误。

---

## 阶段 2：异步连接层（Database/Connection/Pool）

- [x] 设计 `Database` 对象：
  - [x] `connect()` / `disconnect()`
  - [x] `acquire()` / `release()`
  - [x] `execute()` / `fetch_one()` / `fetch_all()`
- [x] 封装连接池参数（最小/最大连接、超时、重试策略）。
- [x] 增加连接生命周期与上下文管理：
  - [x] `async with db.connection() as conn: ...`
- [x] 记录 SQL 执行日志（可开关，脱敏参数）。

完成标准：
- [x] 可以通过 `examples/db_ping.py` 异步连接数据库并执行 `SELECT 1`。
- [x] 连接池行为有集成测试覆盖。

---

## 阶段 3：模型系统（字段 + 元类 + 元信息）

- [x] 实现字段系统：
  - [x] `IntegerField`, `StringField`, `BooleanField`, `DateTimeField`, `JSONField`
  - [x] 字段参数：`primary_key`, `nullable`, `default`, `index`, `unique`
- [x] 实现 `ModelMeta`：
  - [x] 收集字段定义
  - [x] 生成表名与列映射
  - [x] 校验主键约束（仅一个或复合主键策略）
- [x] 实现 `Model` 基类：
  - [x] 实例序列化（`to_dict`）
  - [x] 变更跟踪（dirty fields）
  - [x] 基础校验 hook（`validate()`）

完成标准：
- [x] `User` 示例模型可正确生成元信息。
- [x] 字段定义错误时抛出可读异常。

---

## 阶段 4：SQL 表达式与查询构建器（MVP 核心）

- [x] 设计表达式对象（`Field ==`, `!=`, `>`, `<`, `in_`, `like`）。
- [x] 实现 SQL 生成器（参数化 SQL，严禁字符串拼接注入）。
- [x] 实现 `QuerySet`：
  - [x] `filter()`, `exclude()`, `order_by()`, `limit()`, `offset()`
  - [x] `all()`, `first()`, `get()`, `count()`, `exists()`
- [x] 统一方言层（先实现 PostgreSQL 方言）。

完成标准：
- [x] 可生成正确 SQL + 参数列表（单元测试覆盖核心组合场景）。
- [x] 支持 `await User.filter(User.age > 18).order_by("-id").limit(20).all()`。

---

## 阶段 5：CRUD 与事务

- [x] 实现模型实例操作：
  - [x] `await user.save()`
  - [x] `await user.delete()`
  - [x] `await User.create(...)`
  - [x] `await User.get(...)`
- [x] 实现批量操作（`bulk_create`, `bulk_update`, `bulk_delete`）。
- [x] 实现事务管理：
  - [x] `async with db.transaction(): ...`
  - [x] 支持嵌套事务/保存点（`savepoint`）。
- [x] 异常到领域错误映射（唯一键冲突、外键冲突等）。

完成标准：
- [x] CRUD 集成测试全通过。
- [x] 事务回滚行为可验证（异常触发后数据不落库）。

---

## 阶段 6：关系与预加载（增强）

- [x] 实现关系字段：
  - [x] `ForeignKey`
  - [x] `OneToOne`（可选）
  - [x] `ManyToMany`
- [x] 实现关联查询能力：
  - [x] `select_related`（join 预取）
  - [x] `prefetch_related`（分批查询）
- [x] 解决 N+1 查询问题（基于预加载策略）。

完成标准：
- [x] 一对多与多对一可用并有测试。
- [x] 典型列表页查询可在固定 SQL 次数内完成。

---

## 阶段 7：迁移系统（Schema Migration）

- [x] 定义模型快照与 diff 机制。
- [x] 支持生成迁移脚本：
  - [x] `create table`
  - [x] `add/drop/alter column`
  - [x] `create/drop index`
- [x] 支持迁移命令：
  - [x] `makemigrations`
  - [x] `migrate`
  - [x] `rollback`
- [x] 迁移版本表与幂等性保障。

完成标准：
- [x] 修改模型后可自动生成迁移并成功执行。
- [x] 回滚到指定版本可用。

---

## 阶段 8：性能与可靠性

- [x] SQL 执行耗时统计与慢查询日志。
- [x] 查询缓存策略（可选，先支持显式启用）。
- [x] 批量写优化（分块、copy/execute many）。
- [x] 连接池压测与并发行为验证。
- [x] 健壮性策略：超时、取消、重试（仅幂等查询）。

完成标准：
- [x] 提供基准测试脚本（吞吐/延迟）。
- [x] 在目标并发下无连接泄漏、无死锁（并发池稳定性集成测试 + CI PostgreSQL job + 本地 Docker 校验已通过）。

---

## 阶段 9：开发者体验与发布

- [x] 完善类型提示与 IDE 体验（泛型 QuerySet、返回类型）。
- [x] 编写文档：
  - [x] 快速开始
  - [x] 模型定义
  - [x] 查询 API
  - [x] 事务与迁移
- [x] 提供示例项目（FastAPI 集成）。
- [x] 语义化版本发布与变更日志。

完成标准：
- [x] 新用户按 `README` 可在 10 分钟内跑通 CRUD 示例（提供 Docker 一键校验脚本）。
- [ ] 发布 `v0.1.0`（MVP）与 `v0.2.0`（关系+迁移）（已完成 `0.2.0` 版本与构建，待真实集成验证后上传）。

---

## 建议迭代节奏（可直接执行）

- [x] Sprint 1（1 周）：阶段 0-2（连通数据库）
- [x] Sprint 2（1 周）：阶段 3-5（MVP 可用）
- [x] Sprint 3（1 周）：阶段 6-7（关系+迁移）
- [ ] Sprint 4（1 周）：阶段 8-9（性能+发布）

---

## 首批任务（今天就能开始）

- [x] 创建 `pyproject.toml`，锁定基础依赖：`asyncpg`, `pydantic`(可选), `pytest`, `pytest-asyncio`, `ruff`, `mypy`。
- [x] 建立 `exile_orm/core/database.py`，实现最小 `Database.connect/disconnect/execute`。
- [x] 编写 `tests/integration/test_connection.py`，验证 `SELECT 1`。
- [x] 建立 `ModelMeta` 雏形，支持读取字段定义。
- [x] 完成第一个端到端用例：`User.create -> User.get`。
