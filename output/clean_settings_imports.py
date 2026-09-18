from pathlib import Path
p = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx')
text = p.read_text(encoding='utf-8')
# remove unused lucide icons and api imports carefully
replacements = [
    ('  Cpu,\n', ''),
    ('  Gamepad2,\n', ''),
    ('  connectTeleopHand,\n', ''),
    ('  disconnectTeleopHand,\n', ''),
    ('  captureMotionOrigin,\n', ''),
    ('  homeMotionSide,\n', ''),
    ('  restorePreviousMotionOrigin,\n', ''),
    ('  setTeleopGravityCompensation,\n', ''),
    ('  zeroTeleopForceFeedback,\n', ''),
    ('  axisHardwareSpecs,\n', ''),
    ('  hardwareChannelLabel,\n', ''),
    ('  motionCardModelByNo,\n', ''),
    ('import { motionSideReturnOriginReady } from \'../motionReturnReady\'\n', ''),
    (", type TeleopHandFrameSlice", ''),
    ('  ArmMotionProfile,\n', ''),
]
for a, b in replacements:
    if a in text:
        text = text.replace(a, b, 1)
        print('ok', repr(a[:40]))
    else:
        print('miss', repr(a[:40]))

# remove unused local functions by commenting? better delete via line markers
# originDriftFromError, formatOriginDrift, formatWorkOriginPosition, physicalText, formatAxisValue, configSoftLimitValue, motionSnapshotScope, rotationLimitRows

import re
# delete function originDriftFromError ... through formatWorkOriginPosition end
# safer: replace function bodies that are unused with nothing if they're standalone

def drop_func(src, name):
    # remove "function name(...)" through its closing "}" at column 0
    pattern = re.compile(rf'function {name}\([^\)]*\)[^{{]*\{{.*?\n\}}\n', re.S)
    new, n = pattern.subn('', src, count=1)
    print('drop', name, n)
    return new

for name in ['originDriftFromError', 'formatOriginDrift', 'formatWorkOriginPosition', 'physicalText', 'formatAxisValue', 'configSoftLimitValue', 'motionSnapshotScope']:
    text = drop_func(text, name)

# rotationLimitRows const
text = re.sub(r'const rotationLimitRows = softLimitRows\.slice\(3\)\n', '', text)

p.write_text(text, encoding='utf-8')
print('lines', len(text.splitlines()))
