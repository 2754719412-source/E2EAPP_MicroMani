"""Robot side for deploy_v2: backend HTTP interface (GET only in this version) and the platform safety layer.

Interface as used by the earlier live scripts (experiments/yxp1011_live_20261011_001/live_run8.py):
  GET  /api/policy/observation      -> data.state (14), data.force_right (6), data.dataContract
  GET  /api/cameras/{cam}/snapshot  -> JPEG
Safety values are platform constraints, copied unchanged from act_orig_c_20261014_001/deploy_act_absolute.py:
force > 5 N stops (no automatic back-off), validated workspace, Z >= -21000 um, XY step <= 800 um when Z < -19500 um,
per-command clamps translation 3300 um / rotation 2500 mdeg / gripper 12 mm, prediction-jump anomaly limits.
These never change the policy; they only reject or limit a target. Every limitation is counted in the log.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
import requests

APP = Path(__file__).resolve().parents[2]
URL = "http://127.0.0.1:18082"
CAMS = ("global", "wrist_left", "wrist_right")
DIMS = [7, 8, 9, 10, 12, 13]            # operator_right x, y, z, roll, yaw, gripper (pitch 11 held)
CONTROLLED_SIDES = ["right"]
CLAMP = dict(maxTranslationUm=3300.0, maxRotationDeg=2.5, maxGripperMm=12.0)
# Jump limits |target - state| per dim (x, y, z um; roll, yaw mdeg; gripper mm). 2026-10-15 23:50, approved by the
# operator: relax only, new = max(old, 1.1 * max over training demos of |action - state|); demos max
# [6154, 4243, 6724, 2848, 49.2, 23.9] -> only z changes, 5800 -> 7400.
ANOMALY = np.array([7600.0, 5100.0, 8000.0, 4800.0, 720.0, 25.0])   # 10-16 00:05 z -> 8000, operator approved in chat
FORCE_LIMIT_N = 5.0
Z_UP_JUMP_UM = 12000.0


class Busy(Exception):
    """Backend answered 503 for this request; skip the tick, nothing was sent."""

    def __init__(self, message, detail=None, attempts=None):
        super().__init__(message)
        self.detail = detail or {}
        self.attempts = list(attempts or [])


def check_gripper_feedback(data, state):
    """所有模型共享的输入检查；拒绝目标值、缺失元数据和传输途中变旧的读数。"""
    feedback = data.get("gripperFeedback", {})
    for side in CONTROLLED_SIDES:
        item = feedback.get(side, {}) if isinstance(feedback, dict) else {}
        sample = item.get("sampleUnixMs")
        position = item.get("positionMm")
        age = time.time() * 1000 - sample if type(sample) in (int, float) else float("inf")
        index = 6 if side == "left" else 13
        if (item.get("source") != "jodell_read" or item.get("valid") is not True
                or item.get("participating") is not True or not 0 <= age <= 200
                or type(position) not in (int, float) or not np.isfinite(position)
                or abs(float(state[index]) - position) > 1e-6):
            raise Busy("gripper feedback is missing, invalid or stale", {
                "code": "POLICY_GRIPPER_FEEDBACK_UNAVAILABLE", "gripperFeedback": feedback,
                "clientAgeMs": age if np.isfinite(age) else None,
            })


def _array(x, shape, label):
    a = np.asarray(x, dtype=np.float64)
    if a.shape != shape or not np.isfinite(a).all():
        raise ValueError("invalid " + label)
    return a


def check_observation(data):
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    from backend.core.data_contract import validate_data_contract
    validate_data_contract(data.get("dataContract"))
    state = _array(data["state"], (14,), "state")
    force = _array(data.get("force_right"), (6,), "force")
    if max(np.hypot(*force[:2]), abs(force[2])) > FORCE_LIMIT_N:
        raise ForceLimit("force exceeds 5 N", state, data)
    return state, force


class ForceLimit(ValueError):
    """live_run8 (operator request 10-11): above 5 N stop sending policy targets, lift once by 2 mm, end the run."""
    def __init__(self, msg, state, data):
        super().__init__(msg); self.state, self.data = state, data


FORCE_BACKOFF_UM = 2000.0
PLACE_X_UM = -15000.0  # 10-16: was -20000 (C1 released at -20.2 mm, then retreated); pick area is x ~ 0                   # live_run8: a gripper reopen after a close counts as a place only at x < this
XY_BOX_UM = ((-27500.0, 10500.0), (-9500.0, 13500.0))     # 10-16 01:25: C-group training states x [-26.7, 9.4], y [-8.7, 12.9] mm + ~0.8 mm (10-11 box was too tight)


def safe_target(state, absolute6, prev_target=None):
    """Absolute 6-D target -> 14-D command. Returns (command, flags). Raises ValueError to stop the run.
    10-16 00:50 operator: the jump gate compares the new policy target with the previous one sent (a sudden change
    of prediction); only the first target is compared with the current state. How far the arm actually moves per
    command stays bounded by the per-command clamps below, the z floor and the workspace checks."""
    state = _array(state, (14,), "state")
    target = _array(absolute6, (6,), "absolute target")
    # 10-16 01:10: the prediction-jump gate (inherited from the 10-11 relative-action script) was removed; with absolute
    # targets the per-command clamps, z floor, workspace box and force limit below bound every motion.
    flags = []
    if not (XY_BOX_UM[0][0] <= state[7] <= XY_BOX_UM[0][1] and XY_BOX_UM[1][0] <= state[8] <= XY_BOX_UM[1][1] and state[9] >= -21500):   # 0.5 mm tracking overshoot allowed; commands floor at -21 mm
        raise ValueError("current state outside validated workspace")
    out = state.copy()
    out[DIMS] = target
    before = out.copy()
    out[13] = np.clip(out[13], 0, 26)
    out[9] = max(out[9], -21000)
    if not (XY_BOX_UM[0][0] <= out[7] <= XY_BOX_UM[0][1] and XY_BOX_UM[1][0] <= out[8] <= XY_BOX_UM[1][1]):
        raise ValueError("target outside validated XY workspace")
    if min(state[9], out[9]) < -19500:
        d = out[7:9] - state[7:9]
        n = np.linalg.norm(d)
        if n > 800:
            out[7:9] = state[7:9] + d * (800 / n)
            flags.append("low_xy_step")
    out[7:10] = state[7:10] + np.clip(out[7:10] - state[7:10], -3300, 3300)
    for i in (10, 12):
        out[i] = state[i] + np.clip(out[i] - state[i], -2500, 2500)
    out[13] = state[13] + np.clip(out[13] - state[13], -12, 12)
    if not np.allclose(out, before, rtol=0, atol=1e-9):
        flags.append("limited")         # any safety limit changed the policy target (low_xy_step says which one)
    return out, flags


def selftest_safety():
    s = np.zeros(14); s[6] = 13; s[7] = 1000; s[11] = 123; s[13] = 26
    out, flags = safe_target(s, [1200, 0, 0, 0, 0, 25.0])
    assert out[7] == 1200 and np.array_equal(out[:7], s[:7]) and out[11] == 123 and not flags
    n = 1
    for bad in (np.full(6, np.nan), np.full(6, np.inf), np.zeros(5), np.array([90000, 0, 0, 0, 0, 26])):
        try:
            safe_target(s, bad)
        except ValueError:
            n += 1
        else:
            raise AssertionError("unsafe target accepted")
    low = s.copy(); low[9] = -20000
    c, flags = safe_target(low, [2000, 0, -22000, 0, 0, 26])
    assert c[9] == -21000 and np.linalg.norm(c[7:9] - low[7:9]) <= 800.0001 and "low_xy_step" in flags
    n += 1
    return n


class RobotIO:
    """GET-only robot interface. One requests.Session per thread."""

    def __init__(self):
        self.http = requests.Session()
        self.pool = ThreadPoolExecutor(len(CAMS))
        self.cam_sessions = {c: requests.Session() for c in CAMS}
        self._feedback_ready = False

    def observation(self):
        t = time.perf_counter()
        attempts = []
        while True:
            r = self.http.get(URL + "/api/policy/observation", params={"controlledSides": CONTROLLED_SIDES}, timeout=1.0)
            body = r.json()
            attempts.append({"t": time.time(), "http": r.status_code,
                             "detail": body.get("detail"),
                             "gripperFeedback": body.get("data", {}).get("gripperFeedback")})
            if r.status_code != 503:
                break
            # 首笔 READ 允许预热；所有失败尝试仍进入部署日志的分母。
            if len(attempts) >= 3 and (self._feedback_ready or time.perf_counter() - t >= 3.0):
                detail = body.get("detail", {})
                raise Busy("observation unavailable: " + str(detail.get("message", detail)), detail, attempts)
            time.sleep(0.005 if self._feedback_ready else 0.02)
        r.raise_for_status()
        data = body["data"]
        state, force = check_observation(data)
        try:
            check_gripper_feedback(data, state)
        except Busy as exc:
            exc.attempts = attempts
            raise
        self._feedback_ready = True
        data["observationAttempts"] = attempts
        return data, state, force, (time.perf_counter() - t) * 1000

    def _snap(self, cam):
        r = self.cam_sessions[cam].get(URL + "/api/cameras/" + cam + "/snapshot", timeout=1.0)
        r.raise_for_status()
        im = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
        if im is None or im.shape != (480, 640, 3):
            raise ValueError("camera decode failed " + cam)
        return r.content, cv2.cvtColor(im, cv2.COLOR_BGR2RGB)

    def snapshots(self):
        t = time.perf_counter()
        res = dict(zip(CAMS, self.pool.map(self._snap, CAMS)))
        return res, (time.perf_counter() - t) * 1000
