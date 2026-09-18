from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PARTS = Path(__file__).resolve().parent
OUT = ROOT / 'docs' / '平台架构与全栈知识学习框架.md'


def module(filename, number, cut=None):
    text = (PARTS / filename).read_text(encoding='utf-8')
    text = text[text.index('## 1.'):]
    if cut:
        text = text.split(cut, 1)[0]
    return re.sub(r'^## (\d+)\.\s*', lambda m: f'### {number}.{m[1]} ', text, flags=re.M).strip()


extra = '''### 3.5 用设计方法理解目录结构

这些概念用于解释已有代码的组织方式，不表示仓库完整采用某一套架构规范。

| 设计方法 | 平台中的具体对应 | 为什么有助于理解 |
| --- | --- | --- |
| 分层与职责分离 | 页面交互 → 后端业务 → HAL 执行 | 修改页面布局不应改变驱动单位；换设备优先从接口和驱动边界考虑 |
| 组合与依赖注入 | `create_services` 构造服务并传入依赖 | 可以把真实 HAL 换成测试替身；构造参数显示依赖方向 |
| 适配器与接口契约 | `HalClient`、`NativeGripperAdapter`、相机封装 | 对外提供稳定操作，同时在内部处理不同 SDK 的细节 |
| 发布订阅 | DDS topic、WebSocket 遥测、Zustand 订阅 | 状态发布者不必知道所有消费者；消费者仍需判断新鲜度 |
| 状态机 | 录制片段、控制租约、命令确认 | 同一个操作在不同状态下具有不同合法性和结果 |
| 生产者与消费者 | 源采样、帧组装、写线程与有限队列 | 各阶段可以有不同速度，但必须处理积压与退出顺序 |
| 快照与版本 | 配置快照、原点、generation、请求编号 | 记录一项操作依据的上下文，防止旧结果污染新状态 |
| 所有权与资源生命周期 | Effect 清理、Python shutdown、C++ RAII | 谁创建连接或线程，谁负责释放，失败时也应能回收 |

阅读结构时不要只寻找“某个设计模式”。先问一个状态归谁管理、一项判断在哪个边界做、一个资源由谁释放，再看当前分层能否把责任说清楚。

### 3.6 微装配领域需要补充的知识

平台软件之外，还应学习以下领域知识；这是一份后续知识清单，并非声称这些算法均已在仓库实现。

| 领域 | 核心问题 | 与平台代码的连接点 |
| --- | --- | --- |
| 精密运动与计量 | 分辨率、精度、重复性、回差、漂移有什么区别；控制器读数能否代表末端实际位置 | 脉冲转换、工作原点、限位、标定与定位实验 |
| 显微视觉 | 视场、像素标定、工作距离、景深、曝光、畸变与遮挡如何影响观测 | 相机角色、配置、图像尺寸、采集缓存与质量统计 |
| 坐标与标定 | 主手、机构、相机、工件、力传感器各用什么坐标系 | 左右映射、轴方向、变换矩阵、配置与标定快照 |
| 接触与力测量 | 噪声、零漂、去皮、力/力矩单位与安装方向；滤波延迟如何影响接触判断 | 力驱动、标定、柔顺叠加、保护锁存 |
| 遥操作与人机交互 | 缩放、离合、死区、速度、延迟、反馈怎样影响示教质量 | 原生遥操作映射、控制状态、录制动作标签 |
| 数据与泛化评估 | 工件型号、尺寸、材质/纹理、装夹、操作者和任务阶段怎样记录与划分 | episode 元数据、配置版本、质量标签、训练/测试划分 |

科研中的“通用”应拆成可验证范围：设备接入是否可扩展、不同任务能否复用采集流程、数据语义是否一致、模型是否在未见条件下表现稳定。这四个问题需要不同证据，不能仅用平台可以录制数据来证明模型已具备跨型号泛化能力。

'''

intro = (PARTS / 'intro.md').read_text(encoding='utf-8')
intro = intro.replace('<a id="k4"></a>', extra + '<a id="k4"></a>')
sections = [
    intro.strip(),
    module('frontend.md', 4, '## 供整合者核对'),
    '<a id="k5"></a>\n\n## 5 后端与数据采集知识体系',
    module('backend.md', 5, '## 14.'),
    '<a id="k6"></a>\n\n## 6 HAL 与硬件控制知识体系',
    module('hal.md', 6),
    (PARTS / 'outro.md').read_text(encoding='utf-8').strip(),
]
text = '\n\n'.join(sections) + '\n'
text = text.replace('WS 循环默认约每 33 ms 输出，健康读缓存周期', 'WS 循环默认约每 33 ms 尝试输出，健康读缓存周期')
text = text.replace('管理共享控制器，停止一种来源不能意外停止其余有效来源，也不能在急停后借其余来源重启。', '管理共享控制器，设计上需要保证停止一种来源不会意外停止其余有效来源，并防止急停后借其余来源重启；对应行为应结合停止竞态测试阅读。')
OUT.write_text(text, encoding='utf-8')
print(f'{OUT}: {len(text.splitlines())} lines; {len(text)} characters')
