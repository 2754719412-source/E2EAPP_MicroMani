"""策略只消费带 READ 来源和采样时间的夹爪反馈，不经过界面目标回填。"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from backend.core.data_contract import dataset_side_to_hardware_side
from backend.core.logging import now_ms
from backend.services.gripper_backend import native_gripper_payload


POLICY_GRIPPER_MAX_AGE_MS = 200


class PolicyGripperFeedbackUnavailable(RuntimeError):
    def __init__(self, feedback: dict[str, Any]):
        self.feedback = feedback
        failures = {side: item.get("reason") for side, item in feedback.items()
                    if item.get("participating") and not item.get("valid")}
        super().__init__(f"policy gripper feedback unavailable: {failures}")


def _number(value: Any) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


class PolicyGripperObservation:
    def __init__(self, hal: Any) -> None:
        self.hal = hal
        self._configured_payload: dict[str, object] | None = None
        self._configure_lock = asyncio.Lock()
        self._last_samples: dict[str, float] = {}

    async def read(self, config: dict[str, Any], sides: list[str], *, ensure_sampling: bool) -> tuple[list[float], dict[str, Any]]:
        hardware = {dataset_side_to_hardware_side(side) for side in sides}
        feedback = {side: {"participating": side in sides, "valid": False,
                           "source": "unavailable" if side in sides else "inactive",
                           "positionMm": None, "sampleUnixMs": None, "ageMs": None,
                           "reason": "not_sampled" if side in sides else "not_participating"}
                    for side in ("left", "right")}
        try:
            response = await self.hal.command("teleop.native.status", {})
            native = response.get("response", {})
            participating = ["left" in hardware, "right" in hardware]
            if ensure_sampling:
                payload = native_gripper_payload(config, next(iter(hardware)), 0.0)
                payload.pop("targetMm")
                payload.pop("side")
                payload.update(leftGripperParticipating=participating[0], rightGripperParticipating=participating[1])
                # 已有录制/回放读数可被观察；只读请求不切换它们的控制模式。
                legacy_sampling = native.get("gripperCommandWorkerRunning") is True
                needed = (self._configured_payload != payload or native.get("gripperFeedbackSampling") is not True
                          or native.get("gripperFeedbackParticipating") != participating)
                if needed and not legacy_sampling:
                    async with self._configure_lock:
                        response = await self.hal.command("gripper.feedback.configure", payload)
                        native = response.get("response", {})
                        self._configured_payload = dict(payload)
        except RuntimeError as exc:
            for item in feedback.values():
                if item["participating"]:
                    item.update(reason="transport_unavailable", error=str(exc))
            raise PolicyGripperFeedbackUnavailable(feedback) from exc

        positions = [0.0, 0.0]  # 未参与侧明确掩码，不用其目标值填充。
        stamp = now_ms()
        stroke = float(config.get("gripper", {}).get("strokeMm", 26.0))
        grippers = native.get("grippers", {}) if isinstance(native, dict) else {}
        for side in sides:
            hardware_side = dataset_side_to_hardware_side(side)
            detail = grippers.get(hardware_side, {}) if isinstance(grippers, dict) else {}
            detail = detail if isinstance(detail, dict) else {}
            position = _number(detail.get("positionMm"))
            sample = _number(detail.get("positionSampleTs"))
            age = stamp - sample if sample is not None and sample > 0 else None
            reason = ""
            if detail.get("positionSource") != "jodell_read":
                reason = "not_measured"
            elif detail.get("positionOk") is not True:
                reason = "read_failed"
            elif position is None or not 0 <= position <= stroke:
                reason = "invalid_position"
            elif age is None or age < 0:
                reason = "invalid_sample_time"
            elif age > POLICY_GRIPPER_MAX_AGE_MS:
                reason = "stale"
            elif sample < self._last_samples.get(hardware_side, 0):
                reason = "sample_time_regressed"
            item = feedback[side]
            item.update(valid=not reason, source=detail.get("positionSource", "unavailable"),
                        positionMm=position, sampleUnixMs=sample, ageMs=age, reason=reason,
                        readDurationMs=_number(detail.get("lastReadDurationMs")),
                        lastReadAttemptUnixMs=_number(detail.get("lastReadAttemptTs")),
                        message=str(detail.get("lastReadMessage", "")),
                        readAttempts=detail.get("readAttempts", 0), readSuccesses=detail.get("readSuccesses", 0),
                        readSkippedBusy=detail.get("readSkippedBusy", 0))
            if not reason:
                positions[0 if hardware_side == "left" else 1] = position
                self._last_samples[hardware_side] = sample
        if any(item["participating"] and not item["valid"] for item in feedback.values()):
            raise PolicyGripperFeedbackUnavailable(feedback)
        return positions, feedback
