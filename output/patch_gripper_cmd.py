from pathlib import Path
p = Path(r'D:\E2EAPP_MicroMani\frontend\src\stores\telemetry.ts')
text = p.read_text(encoding='utf-8')
old1 = "  setMotionEnabled: (side: ManualControlState['selectedSide'], enabled: boolean) => void\n  parameterSnapshots: ParameterSnapshot[]"
new1 = "  setMotionEnabled: (side: ManualControlState['selectedSide'], enabled: boolean) => void\n  gripperCommand: Record<ManualControlState['selectedSide'], GripperCommandProgress>\n  parameterSnapshots: ParameterSnapshot[]"
old2 = "  setMotionEnabled: (side, enabled) => motionCommands.setEnabled(side, enabled),\n  parameterSnapshots: readParameterSnapshots(),"
new2 = "  setMotionEnabled: (side, enabled) => motionCommands.setEnabled(side, enabled),\n  gripperCommand: { left: initialGripperCommandProgress(), right: initialGripperCommandProgress() },\n  parameterSnapshots: readParameterSnapshots(),"
print('old1', old1 in text)
print('old2', old2 in text)
if old1 not in text:
    i = text.find('setMotionEnabled: (side: ManualControlState')
    print('ctx', repr(text[i:i+180]))
if old1 in text and old2 in text:
    text = text.replace(old1, new1, 1).replace(old2, new2, 1)
    p.write_text(text, encoding='utf-8')
    print('updated')
