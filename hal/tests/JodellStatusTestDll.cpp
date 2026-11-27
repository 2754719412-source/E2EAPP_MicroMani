// 替代厂商 DLL，供真实 worker 离线读取。没有串口或设备调用。
extern "C" {
__declspec(dllexport) int serialOperation(int, int, bool) { return 1; }
__declspec(dllexport) int clawEnable(int, bool) { return -1; }
__declspec(dllexport) int runWithParam(int, int, int, int) { return -1; }
__declspec(dllexport) int getClawCurrentLocation(int) {
  static int reads = 0;
  return ++reads == 2 ? -1 : 128;
}
__declspec(dllexport) int getClawCurrentStatus(int) {
  static int reads = 0;
  constexpr int values[]{3, 0, -1, 4, 2};
  return reads < 5 ? values[reads++] : 2;
}
__declspec(dllexport) int getClawCurrentTorque(int) { return 32; }
}
