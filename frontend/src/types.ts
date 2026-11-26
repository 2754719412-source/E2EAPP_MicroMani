/*
 * 阅读导航 02｜前端契约与状态
 * 职责：集中声明配置、遥测、录制、诊断与页面状态类型；与后端 schemas 对照阅读。
 * 先看：ConnectionState → TelemetryLinkState → TelemetryLinkStatus → LogLevel。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
export type ConnectionState = 'ok' | 'warn' | 'error' | 'checking' | 'pending'

export type TelemetryLinkState = 'connecting' | 'live' | 'stale' | 'offline'

export interface TelemetryLinkStatus {
  state: TelemetryLinkState
  lastFrameReceivedAt: number | null
}

export type LogLevel = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'

export type LogChannel =
  | '[HAL]'
  | '[BACKEND]'
  | '[CAMERA]'
  | '[FORCE]'
  | '[SAFETY]'
  | '[ZMQ]'
  | '[POLICY]'
  | '[LEROBOT]'
  | '[GRIPPER]'

export interface LogEntry {
  id: number
  ts: number
  channel: LogChannel
  level: LogLevel
  msg: string
}

export interface ProcessStatus {
  name: 'hal' | 'backend' | 'policy' | 'recorder' | 'wsl'
  label: string
  status: 'running' | 'not_running' | 'degraded' | 'error'
  pid?: number
  cpuPct: number
  memMb: number
  vramGb?: number
  autoRestart?: boolean
}

export interface DiagnosticItem {
  key: string
  label: string
  method: string
  metric: string
  status: ConnectionState
  remediation: string
  suspect?: boolean
}

export interface CameraTelemetry {
  key: DatasetCameraKeyApi
  label: string
  fps: number
  timestampSkewMs: number
  frameAgeMs: number
  health: ConnectionState
  backend?: string | null
  workerActive?: boolean | null
}

export interface CameraTuningProfile {
  autoExposure: boolean
  exposure: number
  gain: number
  autoWhiteBalance: boolean
}

export interface Omega7Telemetry {
  side: 'left' | 'right'
  connected: boolean
  physicalConnected?: boolean | null
  calibrated: boolean
  openId: number
  deviceId: number
  serial: string
  systemName: string
  leftHanded: boolean | null
  pose: number[]
  clutchPressed: boolean
  gripperPressed: boolean
  gripperGapMm: number | null
  lastReadOk: boolean
  message: string
}

export interface ForceSideStatus {
  port?: string
  connected?: boolean
  healthy?: boolean
  sampleAgeMs?: number
  sampleHz?: number
  validFrames?: number
  crcErrors?: number
  nonFiniteFrames?: number
  resyncBytes?: number
  error?: string
  axisSign?: number[]
  tareBias?: number[]
  sensorTareBias?: number[]
}

export interface ForceCalibrationSideStatus {
  bias?: number[]
  preMean?: number[]
  preStdDev?: number[]
  prePeakToPeak?: number[]
  residualMean?: number[]
  residualStdDev?: number[]
  residualPeakToPeak?: number[]
}

export interface ForceStatus {
  source?: 'nidaq' | 'hkvl_serial' | 'test' | string
  protocol?: string
  sensorRawLeft?: number[]
  sensorRawRight?: number[]
  leftRightSkewMs?: number
  calibration?: {
    state?: 'not_required' | 'waiting_sensors' | 'checking_stability' | 'taring' | 'validating' | 'ready_for_ack' | 'ready' | 'failed' | string
    progress?: number
    reason?: string
    completedAtUnixMs?: number
    sides?: { left?: ForceCalibrationSideStatus; right?: ForceCalibrationSideStatus }
  }
  sides?: {
    left?: ForceSideStatus
    right?: ForceSideStatus
  }
  safety?: {
    latched?: boolean
    reason?: string
    side?: string
    channel?: string
    value?: number
    canAcknowledge?: boolean
    acknowledgeBlocker?: string
  }
  compliance?: {
    enabled?: boolean
    left?: Record<string, unknown>
    right?: Record<string, unknown>
  }
}

/** HAL 结构化夹爪读数：同一次读取的位置、状态与 gCU 电流原码；各字段只在对应有效标志为 true 时可信。 */
export interface GripperFeedbackSample {
  seq: number
  monotonicUs: number
  timestampSource?: 'worker' | 'hal_midpoint'
  transport?: string
  positionValid: boolean
  statusValid: boolean
  currentValid: boolean
  positionRaw: number
  currentRaw: number
  gACT: number
  gGTO: number
  gSTA: number
  gOBJ: number
  fault: number
}

/** HAL 自上次重置以来的真实读数统计。 */
export interface GripperSampleStats {
  samples: number
  spanMs: number
  effectiveHz: number
  maxGapMs: number
}

/** scripts/calibrate_gripper_force.py 生成的单侧夹持力标定（硬件侧）。 */
export interface GripperForceCalibration {
  version: number
  port: string
  slaveId: number
  calibratedAtUnixMs?: number
  reference?: string
  baseline: { currentMeanRaw: number; currentStdRaw: number; currentMaxRaw: number; contactThresholdRaw: number }
  rfcToForceN: {
    slope: number
    intercept: number
    rmsResidualN: number
    hysteresisN?: number
    rfcMin: number
    rfcMax: number
    forceMinN?: number
    forceMaxN?: number
  }
  holdCurrentRaw: { slope: number; intercept: number; rmsResidualRaw?: number }
}

export interface GripperSideStatus {
  ok?: boolean | null
  message?: string
  positionMm?: number | null
  targetMm?: number | null
  lastCommandTs?: number
  sample?: GripperFeedbackSample | null
  sampleStats?: GripperSampleStats | null
  serial?: {
    port?: string
    slaveId?: number
    baudrate?: number
  }
}

export interface GripperStatus {
  nativeManaged?: boolean
  running?: boolean
  requestedRunning?: boolean
  /** HAL 实际生效的夹持力原码、worker 传输方式与读取间隔。 */
  command?: { torque?: number; speed?: number; transport?: string; sampleIntervalMs?: number } | null
  sides?: {
    left?: GripperSideStatus
    right?: GripperSideStatus
  }
}

export interface TelemetryFrame {
  timestamp: number
  elapsedSec: number
  jointPositions: number[]
  gripperPositions: number[]
  motionEnabled: { left: boolean | null; right: boolean | null }
  motionAxisEnabled: { left: Array<boolean | null>; right: Array<boolean | null> }
  motionAxisEnabledConfirmed?: { left: boolean[]; right: boolean[] }
  forceLeft: number[]
  forceRight: number[]
  forceStatus?: ForceStatus
  gripperStatus?: GripperStatus
  dangerIndex: number
  recording: boolean
  episodeCount: number
  frameCount: number
  halOk: boolean
  wsOk: boolean
  cameras: CameraTelemetry[]
  teleopHands: Omega7Telemetry[]
  queueDepth: { left: number; right: number }
  resource: { uiFps: number; wsHz: number; cpuPct: number; memMb: number }
  processStatus: ProcessStatus[]
}

export interface TelemetrySample {
  time: number
  joints: number[]
  forceLeft: number[]
  forceRight: number[]
  danger: number
  queueLeft: number
  queueRight: number
}

export interface SafetyState {
  dangerIndex: number
  estopActive: boolean
  manualOverride: number | null
  confirmedAt?: number
}

export interface MotionAxisProfile {
  startSpeed: number
  maxSpeed: number
  accTimeSec: number
  decTimeSec: number
}

export interface ArmMotionProfile {
  translation: MotionAxisProfile
  rotation: MotionAxisProfile
}

export interface ForceComplianceSideConfig {
  mappingConfirmed: boolean
  matrix: number[]
  deadbandN: number[]
  gainUmPerNs: number[]
  maxStepUm: number[]
  maxOffsetUm: number[]
}

export interface MotionKinematicsConfig {
  source: string
  axisOrder: string[]
  leftAxisMap: number[]
  rightAxisMap: number[]
  leftPhysicalAxis: number[]
  rightPhysicalAxis: number[]
  axisUnitSpec: string[]
  leftPulsePerUnit: number[]
  rightPulsePerUnit: number[]
  leftDirectionSign: number[]
  rightDirectionSign: number[]
  leftSignedPulsePerUnit: number[]
  rightSignedPulsePerUnit: number[]
  syncActionPulseCoeff: boolean
  updatedAt: string
}

export interface AxisSoftLimitConfig {
  min: number
  max: number
}

export interface ArmSoftLimitConfig {
  x: AxisSoftLimitConfig
  y: AxisSoftLimitConfig
  z: AxisSoftLimitConfig
  roll: AxisSoftLimitConfig
  pitch: AxisSoftLimitConfig
  yaw: AxisSoftLimitConfig
}

export interface RotationWorkLimitSideConfig {
  roll: AxisSoftLimitConfig
  pitch: AxisSoftLimitConfig
  yaw: AxisSoftLimitConfig
}

export interface RotationWorkLimitConfig {
  enabled: boolean
  left: RotationWorkLimitSideConfig
  right: RotationWorkLimitSideConfig
}

export interface MotionOriginConfig {
  valid: boolean
  leftValid: boolean
  rightValid: boolean
  leftPulse: number[]
  rightPulse: number[]
  updatedAt: number
  previousValid: boolean
  previousLeftPulse: number[]
  previousRightPulse: number[]
  previousUpdatedAt: number
}

export interface MotionHomeReferenceConfig {
  valid: boolean
  leftValid: boolean
  rightValid: boolean
  leftPulse: number[]
  rightPulse: number[]
  leftAxisConfirmed: boolean[]
  rightAxisConfirmed: boolean[]
  leftAxisInstanceId?: string[]
  rightAxisInstanceId?: string[]
  leftAxisLimitReference?: boolean[]
  rightAxisLimitReference?: boolean[]
  updatedAt: number
}

export interface MotionWorkOriginOffsetConfig {
  valid: boolean
  leftValid: boolean
  rightValid: boolean
  leftPulseDelta: number[]
  rightPulseDelta: number[]
  updatedAt: number
}

export interface MotionRelativeSoftLimitsConfig {
  left: ArmSoftLimitConfig
  right: ArmSoftLimitConfig
}

export type ManualControlSide = 'left' | 'right'
export type ManualControlAxis = 'X' | 'Y' | 'Z' | 'Roll' | 'Pitch' | 'Yaw'
export type ManualSpeedMode = 'fine' | 'medium' | 'coarse'
export type ManualGripperCommand = 'enable' | 'disable' | 'open' | 'close' | 'home' | 'target' | 'stop'
export type PicoVisionCameraSource = CameraTelemetry['key']
export type PicoVisionRotation = 'none' | 'cw90' | 'ccw90' | '180'
export type Omega7StabilityMode = 'track' | 'hold' | 'off'
export type TeleopControlMode = 'velocity_admittance' | 'incremental_position'

export type RecorderPhase = 'idle' | 'starting' | 'recording' | 'interrupted' | 'reviewing' | 'resetting' | 'saving' | 'discarding' | 'finishing'

export interface EpisodeRecord {
  index: number
  frameCount: number
  durationS: number
  status: 'ok' | 'emergency' | 'discarded'
  maxForceLeft: number
  maxForceRight: number
  lateFrames: number
  cameraDrops: { global: number; wristLeft: number; wristRight: number; microscope?: number }
}

export interface RecordTrainingQualitySide {
  hardwareSide?: 'left' | 'right'
  startTranslationNormUm?: number
  startRotationMaxMdeg?: number
  startStateGripperMm?: number
  startActionGripperMm?: number
  firstSecondMinActionGripperMm?: number | null
  endStateGripperMm?: number
  endActionGripperMm?: number
  translationRangeUm?: number[]
  maxTranslationRangeUm?: number
  actionGripperMinMm?: number
  actionGripperMaxMm?: number
}

export interface RecordTrainingQuality {
  version?: string
  activeDatasetSides?: Array<'left' | 'right'>
  sides?: Partial<Record<'left' | 'right', RecordTrainingQualitySide>>
}

export interface RecordQualityReason {
  severity: 'accept' | 'review' | 'rerecord'
  code: string
  message: string
}

export interface RecordQualityAssessment {
  version?: string
  recommendation: 'accept' | 'review' | 'rerecord'
  reasons: RecordQualityReason[]
  lateRate?: number
  cameraDropRates?: Partial<Record<DatasetCameraKeyApi, number>>
}

export interface RecordQualityReport extends EpisodeRecord {
  warnings: string[]
  passed: boolean
  maxSkewMs?: number
  cameraMinFps?: Partial<Record<DatasetCameraKeyApi, number>>
  cameraWorkerFallbacks?: string[]
  trainingQuality?: RecordTrainingQuality
  qualityAssessment?: RecordQualityAssessment
}

export interface Participation {
  version: 'appstation.participation.v1'
  arms: Array<'left' | 'right'>
  grippers: Array<'left' | 'right'>
}

export interface RecordSessionState {
  participation?: Participation
  startError: string | null
  datasetName: string
  task: string
  targetEpisodes: number
  episodeTimeS: number
  resetTimeS: number
  currentEpisode: number
  savedEpisodes: number
  sessionSavedEpisodes: number
  episodeHistory: EpisodeRecord[]
  latestQualityReport: RecordQualityReport | null
  phase: RecorderPhase
  phaseStartedAt: number | null
  recorderFps: number
  recorderFrameCount: number
  recorderLateFrames: number
  recorderElapsedS: number
  recorderTotalS: number
  resetPending: boolean
  resetRequiredSides: ManualControlSide[]
  resetReturnedSides: ManualControlSide[]
  resetReady: boolean
  returnOriginInFlight: boolean
  forceTareActive: boolean
  speedMode: ManualSpeedMode
}

export type DatasetEpisodeStatusApi = 'valid' | 'review' | 'invalid'
export type DatasetCameraKeyApi = 'global' | 'wrist_left' | 'wrist_right' | 'microscope'

export interface DatasetFeatureApi {
  dtype?: string
  shape?: number[]
  names?: string[]
}

export type DatasetFeatureSummaryApi = Record<string, DatasetFeatureApi>

export interface DatasetCameraResolutionApi {
  physical?: string
  capture?: string
  preview?: string
  saved?: string
}

export interface DatasetEpisodeSampleApi {
  frame: number
  leftJoints: number[]
  rightJoints: number[]
  leftPulses?: number[]
  rightPulses?: number[]
  forceLeft: number[]
  forceRight: number[]
  images?: Partial<Record<DatasetCameraKeyApi, string>>
}

export interface DatasetEpisodeMotionOriginApi {
  valid?: boolean
  leftValid?: boolean
  rightValid?: boolean
  leftPulse?: number[]
  rightPulse?: number[]
  updatedAt?: number
  positionSource?: string
  configHash?: string
}

export interface DatasetEpisodeMotionCalibrationApi {
  kinematics?: Partial<MotionKinematicsConfig>
  teleop?: {
    strategyVersion?: string
    mappingMode?: string
    leftImpulseCoeff?: number[]
    rightImpulseCoeff?: number[]
    leftDirectionSign?: number[]
    rightDirectionSign?: number[]
    syncImpulseCoeffFromKinematics?: boolean
  }
  stateUnitSpec?: string[]
  configHash?: string
}

export interface DatasetEpisodeApi {
  participation?: Participation | null
  id: string
  name: string
  task: string
  status: DatasetEpisodeStatusApi
  quality: number
  frames: number
  fps: number
  durationS: number
  createdAt: number
  warnings: string[]
  samples: DatasetEpisodeSampleApi[]
  lateFrames?: number
  cameraDrops?: Partial<Record<DatasetCameraKeyApi, number>>
  maxForceLeft?: number
  maxForceRight?: number
  features?: DatasetFeatureSummaryApi
  featureSummary?: DatasetFeatureSummaryApi
  cameraResolutions?: Partial<Record<DatasetCameraKeyApi, DatasetCameraResolutionApi>>
  motionOrigin?: DatasetEpisodeMotionOriginApi
  motionCalibration?: DatasetEpisodeMotionCalibrationApi
}

export interface DatasetApi {
  id: string
  name: string
  status: 'local' | 'dry-run' | '待审核' | string
  fps: number
  format: string
  root?: string
  createdAt?: number
  updatedAt?: number
  featureSummary?: DatasetFeatureSummaryApi
  cameraResolutions?: Partial<Record<DatasetCameraKeyApi, DatasetCameraResolutionApi>>
  episodes: DatasetEpisodeApi[]
}

export type ManualControlAction =
  | {
      id: number
      type: 'arm-axis'
      ts: number
      side: ManualControlSide
      axis: ManualControlAxis
      delta: number
      unit: 'um' | '°'
      speedMode: ManualSpeedMode
      positionAfter: number
    }
  | {
      id: number
      type: 'gripper'
      ts: number
      side: ManualControlSide
      command: ManualGripperCommand
      targetMm: number
      forceLimitN: number
      enabled: boolean
    }

export interface ManualControlMemory {
  id: number
  name: string
  createdAt: number
  durationMs: number
  actions: ManualControlAction[]
}

export interface ManualControlState {
  selectedSide: ManualControlSide
  selectedAxis: ManualControlAxis
  axisStepUm: number
  axisStepDeg: number
  speedMode: ManualSpeedMode
  axisBusyUntil: Record<string, number>
  recording: boolean
  recordingStartedAt: number | null
  draftActions: ManualControlAction[]
  memories: ManualControlMemory[]
  replayingMemoryId: number | null
  axisOffsets: Record<string, number>
}

export interface HardwareHomeSideConfig {
  positiveLimitFastVelocityUi?: number
  positiveLimitBackoffUi?: number
  positiveLimitTimeoutSec?: number
  direction: number[]
  velocityMode: number[]
  mode: number[]
  ezCount: number[]
  logic: number[]
  lowVelocityUi: number[]
  highVelocityUi: number[]
  accTimeSec: number[]
  decTimeSec: number[]
  maxSearchUi: number[]
}

export interface AppConfig {
  hal: {
    baseUrl: string
    wsUrl: string
    axisCount: number
    apiConfirmed: boolean
  }
  cameras: {
    global: string
    globalIdentity?: string
    wristLeft: string
    wristLeftIdentity?: string
    wristRight: string
    wristRightIdentity?: string
    microscopeEnabled?: boolean
    microscopeIdentity?: string
    previewResolution: string
    globalResolution?: string
    wristLeftResolution?: string
    wristRightResolution?: string
    fps: number
    tuningDefaultsVersion?: string
    tuning: Record<Exclude<DatasetCameraKeyApi, 'microscope'>, CameraTuningProfile>
  }
  force: {
    source: 'nidaq' | 'hkvl_serial'
    leftIp: string
    rightIp: string
    port: number
    sampleHz: number
    recordWindowSamples: number
    tareSamples: number
    certificateConfirmed: boolean
    calibrationEnabled: boolean
    leftCalibrationPath: string
    rightCalibrationPath: string
    inputMode: string
    voltageMin: number
    voltageMax: number
    lowpassEnabled: boolean
    lowpassCutoffHz: number
    swapHands: boolean
    serial: {
      protocol: 'hkvl_active_v1'
      leftPort: string
      rightPort: string
      baudrate: number
      expectedSampleHz: number
    }
    axisSign: {
      left: number[]
      right: number[]
    }
    compliance: {
      enabled: boolean
      left: ForceComplianceSideConfig
      right: ForceComplianceSideConfig
    }
  }
  motion: {
    leftCardNo: number
    rightCardNo: number
    motionThreadHz: number
    jogStepUm: number
    jogStepDeg: number
    yawSoftLimitDeg: number
    positionSource: 'dmc_get_position' | 'dmc_get_encoder'
    workOriginStrategyVersion: string
    homeReferenceVersion: string
    origin: MotionOriginConfig
    homeReference: MotionHomeReferenceConfig
    hardwareHome?: { left: HardwareHomeSideConfig; right: HardwareHomeSideConfig }
    workOriginOffset: MotionWorkOriginOffsetConfig
    relativeSoftLimits: MotionRelativeSoftLimitsConfig
    leftProfile: ArmMotionProfile
    rightProfile: ArmMotionProfile
    leftSoftLimits: ArmSoftLimitConfig
    rightSoftLimits: ArmSoftLimitConfig
    rotationWorkLimits: RotationWorkLimitConfig
    kinematics: MotionKinematicsConfig
  }
  gripper: {
    leftPort: string
    rightPort: string
    baudrate: number
    leftSlaveId: number
    rightSlaveId: number
    strokeMm: number
    targetLeftMm: number
    targetRightMm: number
    leftEnabled: boolean
    rightEnabled: boolean
    commandForceLimitN: number
    commandSpeed: number
    commandTorque: number
    icfTargetProtectionEnabled: boolean
    icfTargetMinGapMm: number
    sampleHz: number
    sampleStaleMs: number
    sampleEnableOnNegative: boolean
    workerCommandTimeoutSec: number
    forceFeedbackAvailable: boolean
    /** worker 访问夹爪的方式；modbus 需现场验收后启用。 */
    workerTransport?: 'dll' | 'modbus'
    forceCalibration?: {
      applyCommandForceLimit: boolean
      left: GripperForceCalibration | null
      right: GripperForceCalibration | null
    }
  }
  safety: {
    fxyWarnN: number
    fxyStopN: number
    fzWarnN: number
    fzStopN: number
    momentWarnNm: number
    momentStopNm: number
    yawSoftLimitDeg: number
    watchdogMs: number
  }
  zmq: {
    observationPush: string
    actionPull: string
    timeoutMs: number
  }
  storage: {
    datasetRoot: string
    recordFps: number
    recordForce: boolean
    videoCrf: number
    pushToHub: boolean
  }
  auto: {
    allowHardwareDispatch: boolean
    translationStepUm: number
    rotationStepDeg: number
    translationVelocityUmS: number
    rotationVelocityDegS: number
  }
  picoVision: {
    ip: string
    adbPort: number
    videoPort: number
    commandPort: number
    gateway: string
    ifIndex: number
    rotation: PicoVisionRotation
    cameraSource: PicoVisionCameraSource
  }
  teleop: {
    controlMode: TeleopControlMode
    nativeLoopHz: number
    nativeTranslationDeadzoneM: number
    nativeTranslationFullScaleM: number
    nativeRotationDeadzoneDeg: number
    nativeRotationFullScaleDeg: number
    nativeVelocitySmoothingMs: number
    kalmanFilterEnabled: boolean
    kalmanBeta: number
    kalmanMinVariance: number
    kalmanMaxVariance: number
    kalmanDtMinSec: number
    kalmanDtMaxSec: number
    kalmanTranslationPositionVariance: number
    kalmanTranslationVelocityVariance: number
    kalmanTranslationMeasurementVariance: number
    kalmanTranslationProcessPositionVariance: number
    kalmanTranslationProcessVelocityVariance: number
    kalmanRotationPositionVariance: number
    kalmanRotationVelocityVariance: number
    kalmanRotationMeasurementVariance: number
    kalmanRotationProcessPositionVariance: number
    kalmanRotationProcessVelocityVariance: number
    kalmanTranslationIntentVelocityThreshold: number
    kalmanRotationIntentVelocityThreshold: number
    coarse: number
    medium: number
    fine: number
    inputIntervalMs: number
    commandIntervalMs: number
    leftOpenId: number
    rightOpenId: number
    leftConnected: boolean
    rightConnected: boolean
    leftGravityCompensation: boolean
    rightGravityCompensation: boolean
    leftForceFeedback: boolean
    rightForceFeedback: boolean
    leftGravityScale: number
    rightGravityScale: number
    strategyVersion: string
    mappingMode: 'direct' | 'legacy'
    swapHands: boolean
    swapTeleopChannels: boolean
    leftTranslationScale: number
    rightTranslationScale: number
    leftRotationScale: number
    rightRotationScale: number
    homeBeforeStart: boolean
    leftAxisOutputScale: number[]
    rightAxisOutputScale: number[]
    translationStepUm: number
    rotationStepDeg: number
    translationStepLimitPulse: number
    rotationStepLimitPulse: number
    translationPulseDeadband: number
    rotationPulseDeadband: number
    translationDeadzone: number
    rotationDeadzone: number
    incrementalTranslationMinEffectiveDelta: number
    incrementalTranslationReverseDeadzone: number
    translationStartVelocityUmS: number
    translationMaxVelocityUmS: number
    rotationStartVelocityDegS: number
    rotationMaxVelocityDegS: number
    motionProfileAccSec: number
    motionProfileDecSec: number
    continuousIncrementMode: boolean
    translationInputEpsilon: number
    rotationInputEpsilon: number
    translationMinActivePulse: number
    rotationMinActivePulse: number
    continuousMicroConfirmTicks: number
    diagLog: boolean
    leftEnabledAxes: boolean[]
    rightEnabledAxes: boolean[]
    softLimitUnitSpec: string[]
    leftSoftLimitMin: number[]
    leftSoftLimitMax: number[]
    rightSoftLimitMin: number[]
    rightSoftLimitMax: number[]
    leftImpulseCoeff: number[]
    rightImpulseCoeff: number[]
    leftDirectionSign: number[]
    rightDirectionSign: number[]
    syncImpulseCoeffFromKinematics: boolean
    requireClutch: boolean
    stabilityMode: Omega7StabilityMode
    tcpFallbackPort: number
    gripperTeleop: {
      enabled: boolean
      loopHz: number
      leftGapMinMm: number
      leftGapMaxMm: number
      rightGapMinMm: number
      rightGapMaxMm: number
      leftGapInvert: boolean
      rightGapInvert: boolean
      openThreshold: number
      closeThreshold: number
      gripSpeed: number
      gripTorque: number
      positionDeadbandCounts: number
      minCommandIntervalMs: number
      autoGapCalibration: boolean
      autoGapMinSpanMm: number
      autoGapMarginMm: number
      releaseSpeed: number
      releaseTorque: number
      leftSourceHand: string
      rightSourceHand: string
      objectDetectMargin: number
      buttonFallback: boolean
      diagLog: boolean
    }
  }
  wsl: {
    distro: string
    condaEnv: string
    pythonPath: string
    pendingWindowsValidation: boolean
  }
}

export type ParameterSnapshotScope = 'all' | 'motion-left' | 'motion-right'

export interface MotionCardSnapshotConfig {
  cardNo: number
  motionThreadHz: number
  yawSoftLimitDeg: number
  positionSource: AppConfig['motion']['positionSource']
  profile: ArmMotionProfile
  softLimits: ArmSoftLimitConfig
  rotationWorkLimitEnabled: boolean
  rotationWorkLimits: RotationWorkLimitSideConfig
}

export type ParameterSnapshot =
  | {
      id: string
      name: string
      createdAt: number
      scope: 'all'
      config: AppConfig
    }
  | {
      id: string
      name: string
      createdAt: number
      scope: 'motion-left' | 'motion-right'
      config: MotionCardSnapshotConfig
    }

export interface QualityReport {
  episode: number
  durationSec: number
  frames: number
  task: string
  maxSkewMs: number
  jitterMs: number
  maxForceLeft: number
  maxForceRight: number
  warnings: string[]
}
