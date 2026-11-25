# 夹爪夹持力标定（钧舵 EPG26-006）

脚本：`scripts/calibrate_gripper_force.py`；计算：`backend/core/gripper_force.py`；帧编解码：`backend/core/jodell_modbus.py`。
本文档描述的是现场步骤，离线测试只覆盖模拟夹爪，**尚未在实机上运行过**。

## 为什么需要参考测力计

- 手册 6.2.5/6.2.8：`rFC`（0x03EA 高字节，原码 0–255）设定发给电机的最大电流，手指受阻超过上限即停止并置 `gOBJ=2`。
- 手册 6.3.5：`gCU`（0x07D2 高字节）是电流标幺值，没有换算到牛顿的公式；手册示例中运动时 `gCU≈1`，夹住物体后 `gCU=254`（`rFC=255`）。
  稳定夹持时 `gCU` 主要反映“已接触 + 当前设定”，力的大小要靠 `rFC→N` 标定。
- 腕部 HKVL 六维力测的是外力，测不到两指之间的内力，所以必须在两指间夹参考测力计。
- 产品规格：26 mm 行程对应 EPG26-006，额定夹持力 2–6 N。设置页“命令力限制”上限 8 N 已超出额定范围；
  反解时不会向上外推，超过标定最大值的目标会截断到已标定的最大 `rFC`。

## 步骤

所有采集命令都需要先 **停止 HAL 和后端**，因为 Windows 串口只能被一个进程占用；同时确认手指间没有异物。
`baseline` 和 `points` 会驱动夹爪运动，必须加 `--confirm-hardware-motion`。
闭合目标会被钳到 `gripper.icfTargetMinGapMm`（默认 1.02 mm）以上，脚本不会让两指互碰。

端口和从站号按硬件侧填写，默认：硬件左 `COM8`/slave 10，硬件右 `COM9`/slave 9（以 `config.json` 为准）。

1. **空载基线**：两指之间不放东西，开合若干次，记录运动中的 `gCU`：

   ```powershell
   python scripts/calibrate_gripper_force.py baseline --session runtime/gripper_force/COM8.json `
     --port COM8 --slave 10 --cycles 5 --confirm-hardware-motion
   ```

   如果某次闭合没有到位（`gOBJ≠3`），说明有东西挡住，脚本会中止。

2. **测力点**：在两指之间夹参考测力计（推力/压力型，测头宽度要大于最小开度）。脚本每一档 `rFC` 的流程是：
   张开 → 提示放好测力计 → 闭合 → 等待 `gOBJ=2` → 保持 `--hold-s` 期间采 `gCU` → 读测力计 → 张开。
   默认 `rFC` 先升序后降序，每档重复 2 次，用来估计重复性和升降回差：

   ```powershell
   python scripts/calibrate_gripper_force.py points --session runtime/gripper_force/COM8.json `
     --port COM8 --slave 10 --reference "测力计型号/编号" --confirm-hardware-motion
   ```

   - 测力计如果有串口输出，加 `--dynamometer-port COMx --dynamometer-baudrate 9600`，脚本取每行最后一个数值；
     单位是 kgf 时加 `--dynamometer-scale 9.80665`。没有串口时按提示手动输入读数。
   - 每采完一个点就写回会话文件，中断后重新执行会接着追加。

3. **拟合**：

   ```powershell
   python scripts/calibrate_gripper_force.py fit --session runtime/gripper_force/COM8.json `
     --output runtime/gripper_force/COM8.calibration.json --report-force-n 2 4 6 8
   ```

   报告内容：`rFC→N` 斜率/截距、残差 RMS/最大值、重复差、升降回差、稳态 `gCU` 随 `rFC` 的关系、空载基线和接触阈值，
   以及若干目标力反解得到的 `rFC`。残差或回差明显偏大时先检查测力计是否夹正、是否打滑，不要直接采用。

4. **写入配置**（先停止后端；会先备份 `config.json`）：

   ```powershell
   python scripts/calibrate_gripper_force.py apply --calibration runtime/gripper_force/COM8.calibration.json `
     --config <后端运行目录>/config.json --side left
   ```

   端口/从站号必须与 `config.json` 中该硬件侧一致，否则拒绝写入。默认只写标定，不改变下发行为；
   确认结果可用后再加 `--enable-force-limit`（即 `gripper.forceCalibration.applyCommandForceLimit=true`），
   之后实际下发的 `gripTorque` 由 `commandForceLimitN` 反解得到。HAL 只有一个 `gripTorque`，所以取已启用各侧中较小的 `rFC`。
   任一已启用夹爪未标定或接线不匹配时，仍沿用 `teleop.gripperTeleop.gripTorque`，不会静默放大夹持力。

## 建议同时记录的现场片段

用于确认接触判据和电流特征（录制或脚本 trace 都行）：两指分离空载开合、首次接触、稳定夹持、释放。
**指尖互碰**需要把开口命令到 1.02 mm 以下，会越过最小开度保护，属于需要单独授权的现场操作，脚本不提供这一步。

## 数据中的记录

数据集 `meta/appstation_info.json` 的 `hardware.gripper` 段记录：各硬件侧的端口/从站、`gripTorqueRaw`、`commandForceLimitN`、
`forceCalibration`，以及 HAL 固定的位置采样间隔（`gripper.sampleHz` 没有下发到 HAL）。
`recording.recordForce` / `forceFields` 标明本数据集的六维力字段是实测值还是全 0。
