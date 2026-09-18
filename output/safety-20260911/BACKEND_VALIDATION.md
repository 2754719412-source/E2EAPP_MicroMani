# 后端安全控制修复验证记录

验证日期：2026-09-11。工作目录：`D:\E2EAPP_MicroMani`。以下记录来自实际执行的命令与输出；追加 HAL 自动急停确认屏障修复后，只复跑原有定向范围及新增回归，未扩大到整套后端测试。

## 环境与范围

- 使用项目虚拟环境 `backend/.venv/Scripts/python.exe`，实际 Python 版本为 3.13.9。
- 未启动实机。竞态回归使用异步事件、HAL/遥测替身及临时运行目录；未通过真实 SDK 驱动设备。
- 后端共享停止代际补充执行前检查，HAL 执行侧保护由独立 HAL 修复承担。本记录不把离线通过等同于实机验证。
- 录制修复使在途启动和跳过复位操作失效，保留既有 episode 缓冲，未因急停自动丢弃未保存数据。

## 定向服务与 DDS 回归：202 项通过

运行时未设置全局 `APPSTATION_HAL_MODE`；需要特定模式的测试在各自夹具中设置。实际命令：

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_control_stop_races.py backend/tests/test_command_diagnostic_logging.py backend/tests/test_teleop_mapping.py backend/tests/test_dataset_recorder.py backend/tests/test_hal_dds_client.py backend/tests/test_hal_protocol.py backend/tests/test_gripper_router.py -q --disable-warnings
```

实际结果摘要：

```text
202 passed, 24 warnings in 3.29s
```

覆盖内容：

- 新增 `test_control_stop_races.py` 共 20 项参数展开后的回归：急停/普通停止后的旧手动操作、粗旋转剩余分段、旧原生遥操作启动、录制跳过复位、已出队策略动作、急停期间入队、迟到确认、硬件失败、遥测更新异常、急停与清理顺序、直接策略动作及重力补偿旁路，以及 HAL 自行急停而后端未接收急停请求时的确认屏障。
- DDS 丢失回包回归共 6 项：`motion.manual_axis_move`、`motion.enable_side`、`motion.acknowledge_estop`、`teleop.native.start`、`gripper.command`、`teleop.native.gripper_command` 均只发布一次，避免非幂等重发。
- 既有命令服务、遥操作来源共享/回滚、录制生命周期、DDS 协议和夹爪路由回归。

新增停止代际和重试保护前，最初的策略在途动作回归以及 5 个 DDS 丢失回包参数用例确实失败；修复后通过。确认入口补漏前，本组结果为 `199 passed, 20 warnings in 3.22s`；最新结果已计入额外 3 项 HAL 自动急停回归。

环境注意：曾对这组测试全局设置 `APPSTATION_HAL_MODE=test`，得到 197 过、1 失败；失败项 `test_dataset_recorder_gripper_source_uses_assigned_sample_time` 的既有夹具依赖其局部配置 `hal.mode=real`，全局变量覆盖了该配置。最新 202 项结果来自上述未设置全局模式的运行。

### HAL 自动急停的确认屏障补漏

确认事实：HAL 的力保护可以独立触发急停，未必经过 `CommandService.emergency_stop`。因此，仅在后端急停入口递增代际，会遗漏仍等待配置响应的旧请求和策略队列。

最小修复：`CommandService.acknowledge_safety` 在首个 await 前同步执行 `safety.interrupt(emergency=True)`，再捕获本次确认令牌；HAL 确认失败时保持本地锁存。HTTP `/api/motion/safety/acknowledge` 入口同步清空策略队列并终止 auto 运行，不等待额外清理。

新增回归：

- `test_hal_only_trip_acknowledgement_invalidates_pending_manual_config[True]`
- `test_hal_only_trip_acknowledgement_invalidates_pending_manual_config[False]`
- `test_hal_only_trip_acknowledgement_clears_old_policy_queue`

修复前使用完整 HAL 替身执行：

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_control_stop_races.py -k hal_only_trip -q --disable-warnings --tb=short
```

结果为 `3 failed, 17 deselected, 4 warnings in 1.13s`：两个在途手动请求均未被拒绝，队列用例中 auto 仍为运行状态。随后添加确认屏障，三项全部纳入上述 202 项通过结果。

## 受影响 HTTP 路由：5 项通过

实际命令：

```powershell
$env:APPSTATION_HAL_MODE='test'
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_app.py -k 'emergency_stop or acknowledge_safety or teleop_disconnect or gravity_compensation or policy_action' -q --disable-warnings
```

实际结果摘要：

```text
5 passed, 161 deselected, 23 warnings in 1.57s
```

实际选中的测试：

1. `test_teleop_gravity_compensation_saves_config_off_event_loop`
2. `test_teleop_disconnect_schedules_native_refresh_and_reports_mapped_stop`
3. `test_emergency_stop_clears_auto_policy_queue`
4. `test_emergency_stop_returns_before_slow_auto_policy_cleanup`
5. `test_acknowledge_safety_clears_latch_without_restoring_servos_or_moving_origin`

直接策略动作的新增急停竞态用例位于 `test_control_stop_races.py`，已包含在 202 项定向结果中；上述 `-k` 表达式没有额外选中对应旧测试。

## 完整 test_app.py：157 过、4 跳过、5 环境失败

此完整结果取得于确认入口补漏前；补漏后重新验证了上述 202 项定向测试及 5 项 HTTP 路由，未再次执行完整 `test_app.py`。

实际命令：

```powershell
$env:APPSTATION_HAL_MODE='test'
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_app.py -q
```

实际结果摘要：

```text
5 failed, 157 passed, 4 skipped, 479 warnings in 50.36s
```

5 个失败测试名称：

1. `test_manual_axis_move_ignores_translation_soft_limit_target`
2. `test_manual_axis_move_uses_hardware_zero_work_limit_for_rotation`
3. `test_manual_axis_move_uses_hardware_zero_yaw_work_window`
4. `test_manual_axis_move_requires_hardware_zero_not_work_origin_for_rotation_work_limit`
5. `test_manual_axis_move_allows_return_toward_limit_when_already_outside`

共同失败原因：这些既有测试通过 `monkeypatch.setenv("APPSTATION_HAL_MODE", "real")` 覆盖测试进程的全局 test 模式，但在 `create_app(tmp_path)` 前没有替换真实 DDS 客户端构造。应用装配进入 `DdsHalClient → FastDdsHalTransport → _load_library`，因本地缺少 `backend/native/build/appstation_fastdds_transport.dll` 而失败，尚未到达各自的运动断言。

共同异常摘要：

```text
FastDdsBindingUnavailableError: Fast-DDS Python bindings are required:
build backend\native\build_fastdds_transport.cmd first or set APPSTATION_FASTDDS_BINDING_DLL

RuntimeError: Real HAL DDS transport failed to start: Fast-DDS Python bindings are required: ...
```

这是实际环境限制，不记为通过。未为了这些测试启动硬件、构建/加载真实绑定或改写其业务断言；4 项跳过按测试报告保留，未扩展调查跳过原因。

## 其他检查

- 对本次修改的后端源码与测试执行 `git diff --check`，退出码为 0；仅有 Git 的 LF/CRLF 提示。
- 尝试对本次相关文件执行 `backend/.venv/Scripts/python.exe -m ruff check ... --output-format concise`，环境返回 `No module named ruff`。未安装依赖，不能声称 Ruff 已通过。
- pytest 警告主要为已有 FastAPI `on_event`、Starlette 测试客户端弃用提示，以及 `TestHalClient` 类收集提示；没有据此扩展依赖升级或生命周期重构。
