"""仅静态扫描源码并生成学习索引；不导入项目模块或执行其代码。"""
from __future__ import annotations

import ast
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

ROOT = Path('D:/E2EAPP_MicroMani')
OUT = ROOT / 'docs/平台源码知识索引.md'
WORK = ROOT / 'output/knowledge-framework-20260917'

cmd = ['rg', '--files', '--hidden', 'frontend/src', 'frontend/scripts', 'backend', 'hal', 'scripts']
for glob in ['!**/vendor/**', '!**/node_modules/**', '!**/.venv/**', '!**/runtime/**', '!**/build/**',
             '!**/output/**', '!**/__pycache__/**', '!**/*.pyc', '!**/*.pyd', '!**/*.dll',
             '!**/*.lib', '!**/*.exe', '!**/*.obj', '!**/.git/**']:
    cmd += ['-g', glob]
raw = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8').stdout
paths: set[str] = set()
for name in raw.splitlines():
    name = name.replace('\\', '/')
    p = Path(name)
    if name.startswith(('frontend/src/', 'frontend/scripts/', 'scripts/')):
        paths.add(name)
    elif name.startswith('backend/') and (p.suffix == '.py' or name == 'backend/pyproject.toml'
        or (name.startswith('backend/native/') and p.suffix in {'.cpp', '.cmd'})
        or name == 'backend/tests/HOME_SETTINGS_TEST_PLAN.md'):
        paths.add(name)
    elif name.startswith(('hal/include/', 'hal/src/', 'hal/dds/', 'hal/tests/')) or name in {'hal/CMakeLists.txt', 'hal/build_hal.cmd'}:
        paths.add(name)
for p in (ROOT / 'frontend').iterdir():
    if p.is_file() and (p.name in {'.gitignore', 'index.html', 'package.json', 'package-lock.json', 'eslint.config.js', 'vite.config.ts'}
        or p.name.startswith('tsconfig') or p.suffix in {'.bat', '.cmd'}):
        paths.add(p.relative_to(ROOT).as_posix())
for pattern in ['Start*.cmd', 'Stop*.cmd']:
    paths.update(p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern))
if (ROOT / 'mypy.ini').exists():
    paths.add('mypy.ini')

FRONT = {
    'App': 'React 应用装配、路由及连接生命周期',
    'main': 'React 根节点、启动与开发检查边界',
    'types': '前后端契约、配置及遥测 TypeScript 类型',
    'data': '前端默认配置、演示数据与展示元数据',
    'hardwareStatus': '硬件状态与未知/异常状态的显示判定',
    'manualMotionLimits': '手动轴动作的单位、工作范围与限位计算',
    'manualSpeed': '手动运动速度档位与参数换算',
    'motionReturnReady': '返回原点动作的准备条件',
    'gripperDisplay': '夹爪位置、反馈与不可用状态的显示规则',
    'recordDisplay': '录制状态与界面动作的显示规则',
    'teleopStatus': '遥操作手状态与可用性归纳',
    'useGripperDisplay': '从共享状态组合夹爪显示数据的 Hook',
    'useLiveCameraSnapshot': 'MJPEG 图像流 URL、刷新与释放 Hook；名称保留 Snapshot',
    'useMotionEnable': '运动使能操作的 Hook 与状态反馈',
    'ActionCompareModal': '操作前后参数及影响对比对话框',
    'AppLayout': '主界面框架、导航、连接与安全提示',
    'CameraPreview': '相机画面组件与连接/失败处理',
    'Charts': '遥测曲线绘制与数据呈现',
    'ControlLeaseStatus': '控制租约状态及恢复入口展示',
    'GlobalEmergencyStopButton': '全局急停 UI 与请求触发',
    'LogPanel': '结构化日志的筛选与列表显示',
    'MetricPill': '紧凑数值/状态指标组件',
    'ModuleErrorBoundary': '模块级 React 异常边界',
    'RouteErrorBoundary': '路由级异常隔离与恢复界面',
    'SafetyOverlay': '安全锁存及恢复提示覆盖层',
    'StatusBar': '连接、运行与资源状态栏',
    'ui': '本地通用 UI 组件及交互封装',
    'ArmOverviewPanel': '单侧机械手运动/反馈概览',
    'ModuleStatusGrid': '硬件与运行模块状态总览',
    'PlatformOverview': '平台总体运行状态视图',
    'ReadinessSummary': '控制和录制前准备条件归纳',
    'CameraPanel': '录制页面相机分组显示',
    'EpisodeControlPanel': 'episode 保存、丢弃、复位与会话操作',
    'EpisodeHistoryCard': '已录 episode 历史与操作',
    'HardwareStatusCard': '录制所需硬件连接状态',
    'KalmanFilterCard': '遥操作滤波参数编辑界面；算法执行需追踪 HAL',
    'PreCheckModal': '录制前检查条件与阻断原因显示',
    'QualityReportModal': 'episode 质量统计和警告展示',
    'RecordTelemetryPanel': '录制中的运动、力与状态显示',
    'SafetyMonitorCard': '录制中的安全指标展示',
    'controlLease': '控制会话、挑战应答、到期与撤销状态',
    'frameSelectors': '从遥测状态选择局部字段并控制订阅范围',
    'motionCommands': '使能/断使能请求、遥测确认与命令状态协调',
    'telemetry': 'Zustand 共享状态、连接与遥测生命周期',
    'telemetryIngress': '网络遥测与日志进入状态前的结构校验',
    'AutoView': '自动执行控制面板与动作队列展示',
    'DashboardView': '平台仪表盘页面组合',
    'DatasetView': '数据集、episode、回看及管理界面',
    'FineTuneView': '微调任务计划界面；不代表后台已运行训练',
    'ModelView': '模型登记与启动状态界面；不代表已加载权重',
    'RecordPage': '遥操作录制页面及会话流程',
    'SettingsView': '设置页面装配、参数提交及操作确认',
    'CameraCard': '相机设备、格式、曝光等参数设置',
    'ForceSensorCard': '力源、标定、去皮和相关设置',
    'GripperCards': '双侧夹爪配置与控制入口',
    'HalCard': 'HAL 状态、连接及部署信息设置',
    'ManualControlPanel': '手动运动控件与请求协调',
    'MotionCards': '运动卡、原点、轴配置与限位界面',
    'motionHelpers': '运动设置界面的换算、比较和辅助规则',
    'ParameterSnapshotMenu': '参数快照创建、应用与删除菜单',
    'PicoVisionCard': 'PICO 网络、ADB 和视觉连接设置',
    'SafetyCard': '安全阈值及相关参数编辑',
    'StorageCard': '数据存储及录制参数编辑',
    'TeleopHandCard': '遥操作手连接与映射参数界面',
    'shared': '设置模块共享类型、格式化和状态展示组件',
    'controlFaults': '全局脚本异常/未处理 Promise 拒绝与控制撤销',
    'controlSafety': '前端控制可用性与安全动作判定',
}

BACK = {
    'app': 'FastAPI HTTP/WS 入口、服务生命周期和控制会话绑定',
    'app_factory': 'AppServices 依赖装配与共享安全服务连接',
    'config': '配置合并、迁移、校验、原子保存与参数快照',
    'defaults': '设备、运动、相机、力与存储的默认配置',
    'force_config': '力源/标定/安全参数校验及 HAL 载荷',
    'gripper_protection': '夹爪保护间距与目标限制',
    'logging': '结构化日志、会话编号、增量读取与配置哈希',
    'motion_limits': '工作原点、机械范围、旋转范围与恢复方向',
    'motion_safety': '共享运动安全代际、锁存及任务资源互斥',
    'operator_view': '操作者侧与历史硬件侧转换',
    'schemas': 'Pydantic 请求、配置、快照与遥测结构',
    'units': '脉冲、UI μm/degree 与 LeRobot mdeg 换算',
    'camera_opencv': 'OpenCV 采集、缓存、JPEG 与可选进程隔离',
    'force_nidaq': '可选 NI-DAQ 采样、校准、去皮及滤波',
    'gripper_rs485': '保留的 Python Jodell SDK/串口驱动及诊断',
    'pico_adb': 'ADB 命令和外部 PICO 视觉脚本调用',
    'bounded_lane': '有界无排队原生阻塞调用通道',
    'client': 'HAL 抽象、测试替身及保留的 HTTP 客户端',
    'dds_client': '真实 DDS 异步命令/状态适配、期限及故障隔离',
    'dds_runtime': 'ctypes 调用自有 Fast-DDS C ABI DLL',
    'dds_types': 'DDS 主题、domain、信封和命令请求/应答类型',
    'protocol': 'HAL 命令名、载荷和超时/安全重试策略',
    'command_service': '手动运动、工作原点、夹爪与安全命令校验',
    'control_watchdog': '浏览器挑战应答、HAL 执行租约及失联急停',
    'dataset_recorder': '采样缓存、组帧、LeRobot 写线程及数据集管理',
    'gripper_backend': 'HAL-native 夹爪协议适配与状态载荷',
    'gripper_router': '当前始终选择 native 夹爪后端的路由层',
    'hardware_service': 'Python 相机、NI-DAQ、夹爪和 PICO 驱动聚合',
    'pico_network': 'PICO 网络地址与接口信息发现',
    'policy_bridge': '14 维状态/动作转换、分侧动作计划与限幅',
    'policy_service': '模型登记、有限动作队列及微调计划状态',
    'stability_monitor': '稳定性观察任务与 HAL/相机/力状态记录',
    'telemetry_hub': '显示遥测聚合、缓存与后台硬件读取',
    'teleop_mapping': 'native 遥操作配置、来源管理、启动停止与状态采样',
    'camera_capture_worker': '可选独立相机进程、stdin/stdout IPC 与 JPEG 回传',
}

BT = {
    'app': 'API 路由、错误处理与应用服务交互',
    'camera_format': '相机角色、格式、采集与回退',
    'command_diagnostic_logging': '运动命令诊断日志字段',
    'control_stop_races': '急停、恢复和异步返回之间的竞争条件',
    'control_watchdog': '浏览器心跳、HAL 租约与明确恢复',
    'dataset_recorder': 'episode 顺序、原生写入、对齐、质量与清理',
    'dds_blocking_isolation': '阻塞 DLL 隔离、有界容量与停止续租',
    'diagnostic_logging': '结构化日志格式、哈希和限流',
    'force_axis_calibration': '双侧力轴符号与标定契约',
    'force_config': '力源和安全配置校验',
    'force_nidaq_driver': 'NI-DAQ 采样、标定、滤波与任务复用',
    'gripper_driver': 'Python 夹爪驱动/SDK 替身',
    'gripper_router': '夹爪 native 路由与状态/命令',
    'hal_dds_client': 'DDS 缓存、请求匹配、应答和错误',
    'hal_native_acceptance_report': 'HAL-native 验收报告解析及约束',
    'hal_protocol': 'HAL 命令载荷、超时和重试策略',
    'hal_source_contracts': '跨语言 HAL 源码契约静态检查',
    'hal_transport_selection': '真实模式 DDS 选择及 HTTP 拒绝',
    'hardware_defaults': '默认设备参数与配置迁移契约',
    'import_icf_teleop_config': 'ICF 参数导入及迁移',
    'module_isolation': '单模块失败不饿死遥测/日志或资源清理',
    'normalize_origin': '原点归一化辅助工具',
    'operator_view': '操作者与硬件左右映射',
    'pico_adb_driver': 'ADB 连接/离线及视觉脚本调用',
    'pico_network': '网卡、路由与 PICO 地址发现',
    'policy_bridge': '14 维动作语义与单位/限幅',
    'probe_jodell_dual_com': '双串口夹爪诊断工具解析',
    'review_remediation': '控制会话、并发拒绝、参数及数据保留回归',
    'stability_monitor': '稳定性监测任务状态与异常',
    'stack_scripts': '启动停止脚本的静态行为约束',
    'telemetry_hub': '遥测真机/测试语义与缓存',
    'teleop_mapping': 'native 遥操作来源、配置、原点及恢复',
    'units': '脉冲与 UI/LeRobot 单位换算',
}

HAL = {
    'CommandDeadline': '执行命令有效期和迟到请求拒绝',
    'ControlLeaseGuardian': '执行租约失效检查与守护执行',
    'ControlLeaseState': '执行租约会话、序号和新鲜度状态',
    'EmergencyStopState': '急停代际、确认与恢复状态',
    'ForceComplianceController': '力柔顺控制计算、限幅与偏移',
    'ForceControlRuntime': '力采样、安全和柔顺的运行时组织',
    'ForceSafetyLatch': '力阈值/异常触发的执行侧安全锁存',
    'HalCommandDispatcher': 'HAL 命令分类、参数解析和执行路由',
    'HalDdsControlServer': 'DDS 状态发布和命令/急停接收',
    'HalHttpServer': 'HAL HTTP 服务实现；实际开放能力须看处理分支',
    'HalJson': 'HAL 状态与命令结果的 JSON 表达',
    'HalTypes': 'HAL 共享状态与控制载荷结构',
    'HkvlForceDriver': 'HKVL 串口六维力采集与状态管理',
    'HkvlForceProtocol': 'HKVL 字节流分帧、校验和数值解析',
    'HttpConnectionWorkers': 'HTTP 连接任务数量与并发资源管理',
    'JodellGripperDriver': 'Jodell 夹爪 SDK、通信及 worker 交互',
    'JodellGripperWorker': '独立夹爪工作进程入口与命令处理',
    'LTDMCDriver': '雷赛运动控制卡 SDK 包装、读状态与轴命令',
    'MotionControlThread': '运动状态周期轮询、线程启停与异常处理',
    'NativeTeleopController': '原生遥操作生命周期、映射与夹爪协同',
    'Omega7Driver': 'Omega.7 SDK 主手读取、重力补偿与力输出',
    'TeleopDdsTypes': '遥操作 DDS 数据类型与序列化契约',
    'TeleopFollowerTargetSubscriber': '从端目标订阅与状态读取',
    'TeleopHardwareTargetExecutor': '遥操作目标进入真实运动执行的边界',
    'TeleopLeaderPublisher': '主手状态发布与采样链路',
    'TeleopMappingNode': '主手到从端增量/目标的映射与滤波',
    'WorkerExceptionBoundary': '工作循环异常捕获与错误报告边界',
    'HalServer': 'HAL 进程启动、驱动/线程/服务装配',
}
HT = {
    'ControlLeaseTests': '执行租约期限、序号及失效路径',
    'EmergencyStopTests': '急停、确认、并发代际与恢复',
    'ForceCoreTests': '力协议、阈值锁存和柔顺控制',
    'ThreadStabilityTests': '线程与连接工作资源稳定性',
    'WorkerResilienceTests': '工作循环异常与恢复边界',
}
SCRIPTS = {
    'accept-hal-native-teleop': 'HAL-native 遥操作验收采集；先审参数和设备副作用',
    'benchmark_jodell_gripper': '夹爪通信/动作性能测量；非纯离线脚本',
    'capture-hkvl-force': 'HKVL 力状态采集和诊断记录',
    'check-hal': 'HAL 进程、接口与运行状态诊断',
    'diagnose-teleop-latency': '遥操作链路延迟与状态诊断',
    'import_icf_teleop_config': '从参考工程导入遥操作/设备参数',
    'launch-app': '桌面启动编排与前端打开方式',
    'normalize_origin': '配置与数据原点归一化辅助工具',
    'probe_jodell_dual_com': '双 COM 夹爪串口与 SDK 诊断',
    'push_dataset_to_hub': '原生数据集上传 Hub 的辅助进程',
    'run-act-deploy': 'ACT 外部策略部署脚本参数装配；可能启动设备栈',
    'run-act-jepa-deploy': 'ACT-JEPA 外部策略部署和平滑参数装配',
    'start-hal': 'HAL 构建产物部署、配置与进程启动',
    'start-stack': '后端、前端与 HAL 全栈启动编排',
    'start-stack-dds': 'DDS 模式的启动包装与参数传递',
    'start-ui': '界面测试栈启动；依赖具体脚本隔离策略',
    'stop-stack': '按进程/端口停止运行栈及资源清理',
    'verify-hal-native-teleop-report': '离线验收报告检查与失败条件',
}
SPECIAL = {
    'frontend/src/api/index.ts': 'HTTP/WS 地址与请求、控制会话头、错误和超时封装',
    'frontend/src/index.css': '全局样式、布局、响应式与组件视觉规则',
    'frontend/src/test/setup.ts': 'Vitest 测试环境补丁、清理与浏览器替身',
    'frontend/scripts/serve-dist.mjs': '构建产物的本地 HTTP 静态服务与路由回退',
    'frontend/scripts/visual-check.mjs': '构建、启动预览与 Playwright 视觉检查；辅助验收入口',
    'frontend/scripts/find-lines.py': '历史辅助检索：读取 SettingsView 定位待替换片段；非运行入口',
    'frontend/eslint.config.js': 'ESLint 前端规则与文件范围',
    'frontend/vite.config.ts': 'Vite 构建/开发与 Vitest 配置',
    'frontend/index.html': '浏览器页面骨架与前端脚本入口',
    'frontend/package.json': 'npm 命令、依赖和包元数据',
    'frontend/package-lock.json': 'npm 依赖解析锁定；保留的可复现配置，不是应用入口',
    'frontend/tsconfig.json': 'TypeScript 工程引用关系',
    'frontend/tsconfig.app.json': '浏览器应用 TypeScript 编译/检查选项',
    'frontend/tsconfig.node.json': 'Node 工具配置文件的 TypeScript 选项',
    'frontend/.gitignore': '前端依赖、构建与本机文件的 Git 排除规则',
    'backend/pyproject.toml': 'Python 基础/可选依赖、pytest、Ruff 与 mypy 配置',
    'backend/native/appstation_fastdds_transport.cpp': 'Python 调用的 C ABI、Fast-DDS 缓存及命令应答同步',
    'backend/native/build_fastdds_transport.cmd': 'Fast-DDS 原生绑定 DLL 的构建与产物路径',
    'backend/tests/HOME_SETTINGS_TEST_PLAN.md': '设置/原点人工验证计划；不是已通过的测试报告',
    'hal/dds/appstation_hal.idl': 'HAL DDS 类型、字段与序列化契约定义',
    'hal/CMakeLists.txt': 'HAL/C++ 测试构建目标、编译配置和 SDK 依赖',
    'hal/build_hal.cmd': 'Windows HAL 构建、链接与产物部署脚本',
    'hal/tests/fixtures/hkvl_active_v1_frames.hex': 'HKVL 协议字节流测试样本；数据夹具',
    'Start-App.cmd': '桌面应用启动包装；继续追踪所调用 PowerShell',
    'Start-UI.cmd': '界面测试启动包装；继续追踪所调用 PowerShell',
    'Stop-App.cmd': '应用停止包装；继续追踪所调用 PowerShell',
    'frontend/启动真实前端.bat': '真实前端启动辅助包装；先审目标脚本和模式',
    'frontend/打开前端.bat': '打开前端的辅助包装；不是 React 源码',
    'mypy.ini': '仓库级 Python 静态类型检查范围与忽略规则',
}

PREFERRED = {
    'backend/app.py': ['create_app', 'make_hal_client'],
    'backend/app_factory.py': ['AppServices', 'create_services'],
    'backend/services/dataset_recorder.py': ['DatasetRecorderService', 'FrameAssembler', 'LeRobotWriterThread'],
    'backend/services/command_service.py': ['CommandService', 'manual_axis_move'],
    'backend/core/config.py': ['SettingsService', 'save_config'],
    'backend/core/units.py': ['pulse_to_ui', 'ui_to_lerobot_state'],
    'backend/hal_client/client.py': ['HalClient', 'TestHalClient'],
    'backend/drivers/camera_opencv.py': ['OpenCVCameraDriver', '_process_capture_enabled'],
    'backend/drivers/force_nidaq.py': ['NidaqForceDriver', '_PersistentTask'],
}

GROUPS = [
    ('前端入口、契约与纯逻辑', 'frontend_base'),
    ('前端共享状态、Hook 与 API', 'frontend_state'),
    ('前端通用组件及 dashboard / record 组件', 'frontend_components'),
    ('前端页面与设置子模块', 'frontend_views'),
    ('前端测试与测试环境', 'frontend_tests'),
    ('前端静态资源', 'frontend_assets'),
    ('前端配置与辅助脚本', 'frontend_tools'),
    ('后端应用、core 与业务 services', 'backend_app'),
    ('后端驱动、workers 与 HAL 客户端', 'backend_io'),
    ('后端测试与验证计划', 'backend_tests'),
    ('后端原生绑定与构建/类型配置', 'backend_native'),
    ('HAL 头文件', 'hal_headers'),
    ('HAL 实现文件', 'hal_sources'),
    ('HAL DDS 与构建配置', 'hal_build'),
    ('HAL 测试及夹具', 'hal_tests'),
    ('平台启动、部署和诊断脚本', 'scripts'),
    ('根目录与前端快捷启动包装', 'launchers'),
]

def group_for(name: str) -> str:
    if name in {'Start-App.cmd', 'Start-UI.cmd', 'Stop-App.cmd'} or name.endswith(('.bat',)):
        return 'launchers'
    if name.startswith('frontend/src/'):
        if '.test.' in name or name.startswith('frontend/src/test/'):
            return 'frontend_tests'
        if name.startswith('frontend/src/assets/'):
            return 'frontend_assets'
        if name.startswith(('frontend/src/api/', 'frontend/src/stores/', 'frontend/src/hooks/')):
            return 'frontend_state'
        if name.startswith('frontend/src/components/'):
            return 'frontend_components'
        if name.startswith('frontend/src/views/'):
            return 'frontend_views'
        return 'frontend_base'
    if name.startswith('frontend/'):
        return 'frontend_tools'
    if name.startswith('backend/tests/'):
        return 'backend_tests'
    if name.startswith(('backend/native/',)) or name in {'backend/pyproject.toml', 'mypy.ini'}:
        return 'backend_native'
    if name.startswith(('backend/drivers/', 'backend/workers/', 'backend/hal_client/')):
        return 'backend_io'
    if name.startswith('backend/'):
        return 'backend_app'
    if name.startswith('hal/include/'):
        return 'hal_headers'
    if name.startswith('hal/src/'):
        return 'hal_sources'
    if name.startswith('hal/tests/'):
        return 'hal_tests'
    if name.startswith('hal/'):
        return 'hal_build'
    return 'scripts'

def base_stem(name: str) -> str:
    stem = Path(name).stem
    return stem.split('.')[0]

def topic(name: str) -> str:
    if name in SPECIAL:
        return SPECIAL[name]
    if name.startswith('frontend/scripts/') and Path(name).name.startswith(('patch-', 'fix-')):
        return '历史 UI 文本替换/迁移脚本；会改源码，非运行入口，不应直接重跑'
    if name.startswith('frontend/src/assets/'):
        return '静态图片/图标资源；是否实际引用需搜索文件名'
    if Path(name).name == '__init__.py':
        return 'Python 包入口；查看是否仅作包标记或显式导出'
    if name.startswith('frontend/'):
        stem = base_stem(name)
        if '.test.' in name:
            if stem == 'api':
                return '回归测试｜HTTP 客户端生命周期与控制恢复'
            if stem == 'DirectControls':
                return '回归测试｜页面直接控制入口的安全门禁'
            if stem == 'TaskPages':
                return '回归测试｜任务页面异步请求与卸载生命周期'
            return '回归测试｜' + FRONT.get(stem, stem + '行为')
        return FRONT.get(stem, '前端代码：从实际导出符号识别调用者')
    if name.startswith('backend/tests/test_'):
        return '回归测试｜' + BT.get(Path(name).stem[5:], Path(name).stem[5:])
    if name.startswith('backend/'):
        return BACK.get(Path(name).stem, '后端模块：从实际定义和调用关系阅读')
    if name.startswith('hal/tests/'):
        return 'C++ 测试｜' + HT.get(Path(name).stem, '执行行为与边界')
    if name.startswith('hal/'):
        prefix = '声明/接口｜' if name.endswith('.h') else '实现｜'
        return prefix + HAL.get(Path(name).stem, '从实际类型和方法定位职责')
    return SCRIPTS.get(Path(name).stem, '脚本：先检查参数、入口与副作用')

def line_at(text: str, index: int) -> int:
    return text.count('\n', 0, index) + 1

def unique(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    seen: set[str] = set()
    return [item for item in items if not (item[0] in seen or seen.add(item[0]))]

def symbols(name: str, text: str) -> list[tuple[str, int]]:
    suffix = Path(name).suffix
    if suffix == '.py':
        tree = ast.parse(text, filename=name)
        definitions = {n.name: n.lineno for n in ast.walk(tree) if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))}
        if name in PREFERRED:
            return [(s, definitions[s]) for s in PREFERRED[name] if s in definitions]
        if '/tests/' in name:
            return [(n.name, n.lineno) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith('test_')][:2]
        nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
        public = [n for n in nodes if not n.name.startswith('_')]
        return [(n.name, n.lineno) for n in (public or nodes)][:3]
    if suffix in {'.ts', '.tsx', '.js', '.mjs'}:
        if '.test.' in name:
            result = []
            for match in re.finditer(r'\b(?:describe|it|test)(?:\.(?:each|skip|only|todo))?\s*\(\s*([\'\"])(.*?)\1', text):
                result.append((match.group(2), line_at(text, match.start())))
            return unique(result)[:2]
        pattern = r'^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function|class|interface|type|const)\s+([A-Za-z_$][\w$]*)'
        all_defs = [(m.group(1), line_at(text, m.start())) for m in re.finditer(pattern, text, re.M)]
        exported = [(m.group(1), line_at(text, m.start())) for m in re.finditer(r'^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|const)\s+([A-Za-z_$][\w$]*)', text, re.M)]
        preferred = [s for s in all_defs if s[0] == Path(name).stem]
        return unique(preferred + exported + all_defs)[:3]
    if suffix in {'.h', '.cpp', '.idl'}:
        items = [(m.group(1), line_at(text, m.start())) for m in re.finditer(r'^\s*(?:class|struct)\s+(\w+)', text, re.M)]
        qualified = [(m.group(1), line_at(text, m.start())) for m in re.finditer(r'^\s*[\w:<>,*&\s]+?\b(\w+::(?:~?\w+))\s*\(', text, re.M)]
        qualified = [item for item in qualified if item[0].split('::')[0] not in {'std', 'this_thread', 'steady_clock', 'system_clock', 'chrono', 'filesystem'}]
        functions = [(m.group(1), line_at(text, m.start())) for m in re.finditer(r'^\s*(?:(?:static|inline|constexpr|extern)\s+)*(?:bool|void|int|double|float|std::\w+(?:<[^\n]+?>)?|uint\d+_t)\s+(\w+)\s*\(', text, re.M)]
        if '/tests/' in name:
            return unique([item for item in functions if item[0].startswith('test') or item[0] == 'main'] + functions + items)[:3]
        if suffix == '.cpp':
            return unique(qualified + functions + items)[:3]
        return unique(items + qualified + functions)[:3]
    if suffix == '.ps1':
        result = [(m.group(1), line_at(text, m.start())) for m in re.finditer(r'^\s*function\s+([\w-]+)', text, re.M | re.I)]
        return result[:3]
    return []

def question(name: str, text: str, syms: list[tuple[str, int]]) -> str:
    if name == 'frontend/scripts/find-lines.py':
        return '读取哪份 SettingsView，按哪些文本定位并打印行号？'
    if syms:
        if '.test.' in name and name.startswith('frontend/'):
            return '用例：' + '；'.join('“' + s.replace('\n', ' ') + '”' for s, _ in syms)
        return ' → '.join('`' + s + '`' for s, _ in syms)
    if Path(name).name == '__init__.py':
        return '包初始化是否含可执行语句或重导出？'
    if name.endswith('.ps1'):
        return '从 `param(...)` 到末尾执行流：调用哪些进程、写哪些文件、会不会连接设备？'
    if name.endswith(('.cmd', '.bat')):
        called = unique([(m.group(0), line_at(text, m.start())) for m in re.finditer(r'[A-Za-z_][\w-]+\.ps1', text)])
        return ('追踪 ' + '、'.join('`' + s + '`' for s, _ in called[:3])) if called else '从环境变量、编译器/进程命令和 errorlevel 判断副作用。'
    if name.endswith('.css'):
        return '从 `:root` 变量、布局类和媒体查询追踪到使用组件。' if ':root' in text else '按选择器反查组件，并检查媒体查询与覆盖顺序。'
    if name.endswith('.json'):
        try:
            keys = list(json.loads(text))[:5]
        except json.JSONDecodeError:
            keys = re.findall(r'^\s{0,4}"([^"\n]+)"\s*:', text, re.M)[:5]
        return '配置字段：' + '、'.join('`' + key + '`' for key in keys)
    if name.endswith('.toml'):
        return '`[project]` → `[project.optional-dependencies]` → `[tool.*]`'
    if name.endswith('.html'):
        return 'HTML 根节点与 module script 指向哪个 TSX 入口？'
    if name.endswith('CMakeLists.txt'):
        targets = re.findall(r'add_(?:executable|library)\s*\(\s*([^\s)]+)', text)
        return '构建目标：' + '、'.join('`' + t + '`' for t in targets[:5])
    if name.startswith('frontend/scripts/') and name.endswith('.py'):
        return '顶层 `Path/read_text/replace/write_text`：目标文件及替换前提仍成立吗？'
    if '/assets/' in name:
        return '搜索文件名确认引用；图像资源没有函数入口。'
    if name.endswith('.hex'):
        return '帧头、长度、校验及期望解析结果与协议测试如何对应？'
    if name.endswith('.md'):
        return '区分计划步骤、已执行记录与验收判据。'
    if name.endswith(('.ini', '.gitignore')):
        return '哪些目录/文件被检查、忽略或排除？'
    return '从顶层执行语句和导出对象追踪调用关系。'

def cell(value: str) -> str:
    return value.replace('|', '\\|').replace('\r', ' ').replace('\n', ' ')

records = []
issues = []
for name in sorted(paths):
    p = ROOT / name
    if p.suffix in {'.png', '.jpg', '.jpeg', '.ico'}:
        text = ''
    else:
        text = p.read_text(encoding='utf-8-sig')
    try:
        syms = symbols(name, text)
    except (SyntaxError, ValueError) as exc:
        issues.append({'file': name, 'error': str(exc)})
        syms = []
    records.append({'path': name, 'group': group_for(name), 'topic': topic(name),
                    'symbols': syms, 'question': question(name, text, syms)})

counts = Counter(r['group'] for r in records)
title_by_group = dict((key, title) for title, key in GROUPS)
lines = [
    '# 平台源码知识索引', '',
    '本索引是 **2026-09-17 当前工作区源码清单**，包含当前修改和未跟踪的自有文件，不代表全部源码已经部署或完成实机验证。配合[平台架构与全栈知识学习框架](D:/E2EAPP_MicroMani/docs/平台架构与全栈知识学习框架.md)阅读：主文档解释系统关系，本索引定位到每个文件。', '',
    '清单使用 `rg --files --hidden` 取得，并按要求排除 vendor、node_modules、.venv、runtime、build、output、缓存及二进制构建产物；保留 package-lock.json，因为它是依赖复现依据。frontend/src 的静态资源、测试夹具及后端人工验证计划单列，不把它们混称为运行代码。未纳入其他历史说明文档和根目录打包 JS。', '',
    '“先读的符号/阅读问题”来自 Python AST、TypeScript/C++/PowerShell 实际定义或实际测试标题的静态提取，未执行这些文件。每行给出少量阅读锚点，不是该文件的完整接口清单。含行号的链接指向本次提取位置，代码变化后行号可能移动。', '',
    '**辅助脚本说明：**frontend/scripts 中的 patch-*、fix-* 为保留的文本替换/迁移工具，会修改源码，既不是当前应用运行入口，也不应为了学习而直接重跑。构建、部署、诊断脚本是否连接硬件必须先读参数和执行流。测试名称表示覆盖意图，不表示本次执行通过；本次未运行任何服务、设备或测试。', '',
    f'共 **{len(records)} 个文件**。分组如下：', '',
    '| 分组 | 文件数 |', '|---|---:|',
]
for title, key in GROUPS:
    lines.append(f'| {title} | {counts[key]} |')
lines += ['', '建议顺序：入口与契约 → 状态/请求链 → 安全与单位 → 数据录制 → HAL 执行 → 同主题测试；遇到选配/兼容模块，先查看当前工厂或路由是否实际选择它。']
for title, key in GROUPS:
    lines += ['', f'## {title}（{counts[key]} 个）', '', '| 源码链接 | 知识主题/职责 | 先读的符号/阅读问题 |', '|---|---|---|']
    for record in records:
        if record['group'] != key:
            continue
        suffix = ':' + str(record['symbols'][0][1]) if record['symbols'] else ''
        target = (ROOT / record['path']).as_posix() + suffix
        lines.append(f"| [{record['path']}]({target}) | {cell(record['topic'])} | {cell(record['question'])} |")
lines += ['', '## 本次清单检查', '',
    f'- 已按文件路径去重：{len(records)} 行与 {len(paths)} 个入选文件逐一对应。',
    '- 已检查本索引的源码/资源链接及主文档链接目标存在。',
    '- 已按静态定义提取阅读锚点；没有执行 import、测试函数、构建或启动脚本。',
    '- 排除目录中的第三方库、产物、运行数据和生成物不属于本索引；配置保留兼容字段也不代表对应功能仍在默认运行链中。', '']
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text('\n'.join(lines), encoding='utf-8')
missing = []
for target in re.findall(r'\]\((D:/E2EAPP_MicroMani/[^)]+)\)', OUT.read_text(encoding='utf-8')):
    target = re.sub(r':\d+$', '', target)
    if not Path(target).exists():
        missing.append(target)
report = {'total_files': len(records), 'counts': dict(counts), 'parse_issues': issues,
          'missing_links': sorted(set(missing)), 'records': records}
(WORK / 'source_index_manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in report.items() if k != 'records'}, ensure_ascii=False, indent=2))
print(OUT)
