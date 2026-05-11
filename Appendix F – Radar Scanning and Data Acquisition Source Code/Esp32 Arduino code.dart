#include <Arduino.h>
// PIN DEFINITIONS
static const int X_STEP_PIN = 25;
static const int X_DIR_PIN  = 26;
static const int X_EN_PIN   = 27;
static const int Y_STEP_PIN = 14;
static const int Y_DIR_PIN  = 18;
static const int Y_EN_PIN   = 13;
// DRIVER ENABLE POLARITY
static const bool ENABLE_ACTIVE_HIGH = false;
// DIRECTION POLARITY
static const bool X_FORWARD_IS_HIGH = true;
static const bool Y_FORWARD_IS_HIGH = true;
// MECHANICAL SETTINGS
// 3200 pulses/rev
// lead screw = 5 mm/rev
// steps/mm = 3200 / 5 = 640
static const float X_MAX_MM = 200.0f;
static const float Y_MAX_MM = 200.0f;
static const float X_STEPS_PER_MM = 640.0f;
static const float Y_STEPS_PER_MM = 640.0f;
// SCAN SPACING
static const float SCAN_STEP_MM = 20.0f;
// STEP TIMING
static const int STEP_PULSE_US = 5;
static const int STEP_GAP_US   = 400;
static const int DIR_SETUP_US  = 10;
static const int SETTLE_MS     = 120;
// GLOBAL STATE
volatile bool stopRequested = false;
long xSteps = 0;
long ySteps = 0;
// HELPERS
void setEnable(int enPin, bool enable) {
  if (ENABLE_ACTIVE_HIGH) {
    digitalWrite(enPin, enable ? HIGH : LOW);
  } else {
    digitalWrite(enPin, enable ? LOW : HIGH);  }} 
long mmToStepsX(float mm) {
  return lround(mm * X_STEPS_PER_MM);}
long mmToStepsY(float mm) {
  return lround(mm * Y_STEPS_PER_MM);}
float stepsToMmX(long steps) {
  return (float)steps / X_STEPS_PER_MM;}
float stepsToMmY(long steps) {
  return (float)steps / Y_STEPS_PER_MM;}
String readLineNonBlocking() {
  if (Serial.available()) {
    String s = Serial.readStringUntil('\n');
    s.trim();
    return s; }
  return "";}
bool isEspBootNoise(const String &line) {
  return line.startsWith("ets ")
      || line.startsWith("rst:")
      || line.startsWith("configsip:")
      || line.startsWith("clk_drv:")
      || line.startsWith("mode:")
      || line.startsWith("load:")
      || line.startsWith("entry ");}
void processAsyncCommands() {
  String cmd = readLineNonBlocking();
  if (cmd.length() == 0) return;
  if (isEspBootNoise(cmd)) return;
 
  if (cmd == "STOP") {
    stopRequested = true;}}
void stepPulse(int stepPin) {
  digitalWrite(stepPin, HIGH);
  delayMicroseconds(STEP_PULSE_US);
  digitalWrite(stepPin, LOW);
  delayMicroseconds(STEP_GAP_US);}
void stepAxis(int stepPin, int dirPin, long &currentPosSteps, long deltaSteps, bool forwardIsHigh) {
  if (deltaSteps == 0) return;
  bool forward = (deltaSteps > 0);
  bool dirLevel = forward ? forwardIsHigh : !forwardIsHigh;
  digitalWrite(dirPin, dirLevel ? HIGH : LOW);
  delayMicroseconds(DIR_SETUP_US);
  long totalSteps = labs(deltaSteps);
  for (long i = 0; i < totalSteps; i++) {
    processAsyncCommands();
    if (stopRequested) return;
    stepPulse(stepPin);
    if (forward) currentPosSteps++;
    else currentPosSteps--;  }}
void moveToMm(float targetXmm, float targetYmm) {
  if (targetXmm < 0) targetXmm = 0;
  if (targetXmm > X_MAX_MM) targetXmm = X_MAX_MM;
  if (targetYmm < 0) targetYmm = 0;
  if (targetYmm > Y_MAX_MM) targetYmm = Y_MAX_MM;
  long targetXsteps = mmToStepsX(targetXmm);
  long targetYsteps = mmToStepsY(targetYmm);
  long dx = targetXsteps - xSteps;
  long dy = targetYsteps - ySteps;
  // Move Y first, then X
  stepAxis(Y_STEP_PIN, Y_DIR_PIN, ySteps, dy, Y_FORWARD_IS_HIGH);
 if (stopRequested) return;
  stepAxis(X_STEP_PIN, X_DIR_PIN, xSteps, dx, X_FORWARD_IS_HIGH);
  if (stopRequested) return; 
  delay(SETTLE_MS);}
void sendReadyPosition() {
  Serial.print("READY ");
  Serial.print(stepsToMmX(xSteps), 2);
  Serial.print(" ");
  Serial.println(stepsToMmY(ySteps), 2);}
bool waitForCaptureNow() {
  while (true) {
    String cmd = readLineNonBlocking();
    if (cmd.length() == 0) {
      delay(5);
      continue;}
    if (isEspBootNoise(cmd)) continue;
    if (cmd == "STOP") {
      stopRequested = true;
      return false;}
    if (cmd == "CAPTURE_NOW") {
      return true;}}}
bool waitForOkFromPython() {
  while (true) {
    String cmd = readLineNonBlocking();
    if (cmd.length() == 0) {
      delay(5);
      continue;}
    if (isEspBootNoise(cmd)) continue;
    if (cmd == "STOP") {
      stopRequested = true;
      return false;}
    if (cmd == "OK") {
      return true;}}}
bool captureHandshakeAtCurrentPoint() {
  sendReadyPosition();
  bool gotCapture = waitForCaptureNow();
  if (!gotCapture || stopRequested) return false;
  Serial.println("TRIGGER_SENT");
  bool gotOk = waitForOkFromPython();
  if (!gotOk || stopRequested) return false;
  return true;}
void returnToOrigin() {
  Serial.println("RETURNING_TO_ORIGIN");
  bool oldStop = stopRequested;
  stopRequested = false;
  moveToMm(0.0f, 0.0f);
  Serial.println("AT_ORIGIN");
  stopRequested = oldStop;}
void runSnakeScan() {
  stopRequested = false;
  Serial.println("SCAN_START");
  moveToMm(0.0f, 0.0f);
  if (stopRequested) {
    stopRequested = false;
    returnToOrigin();
    Serial.println("SCAN_ABORTED");
    return;}
  int totalRows = (int)(Y_MAX_MM / SCAN_STEP_MM) + 1;
  int totalCols = (int)(X_MAX_MM / SCAN_STEP_MM) + 1;
  for (int row = 0; row < totalRows; row++) {
    float y = row * SCAN_STEP_MM;
    if (y > Y_MAX_MM) y = Y_MAX_MM;
 
    if (row % 2 == 0) {
      for (int col = 0; col < totalCols; col++) {
        float x = col * SCAN_STEP_MM;
        if (x > X_MAX_MM) x = X_MAX_MM;
        moveToMm(x, y);
        if (stopRequested) {
          stopRequested = false;
          returnToOrigin();
          Serial.println("SCAN_ABORTED");
          return;}
        bool ok = captureHandshakeAtCurrentPoint();
        if (!ok || stopRequested) {
          stopRequested = false;
          returnToOrigin();
          Serial.println("SCAN_ABORTED");
          return;}}}
 else {
      for (int col = totalCols - 1; col >= 0; col--) {
        float x = col * SCAN_STEP_MM;
        if (x > X_MAX_MM) x = X_MAX_MM; 
        moveToMm(x, y);
        if (stopRequested) {
          stopRequested = false;
          returnToOrigin();
          Serial.println("SCAN_ABORTED");
          return;}
        bool ok = captureHandshakeAtCurrentPoint();
        if (!ok || stopRequested) {
          stopRequested = false;
          returnToOrigin();
          Serial.println("SCAN_ABORTED");
          return; }}}}
  stopRequested = false;
  returnToOrigin();
  Serial.println("SCAN_DONE");}
void setup() {
  Serial.begin(115200);
  pinMode(X_STEP_PIN, OUTPUT);
  pinMode(X_DIR_PIN, OUTPUT);
  pinMode(X_EN_PIN, OUTPUT);
  pinMode(Y_STEP_PIN, OUTPUT);
  pinMode(Y_DIR_PIN, OUTPUT);
  pinMode(Y_EN_PIN, OUTPUT);
  digitalWrite(X_STEP_PIN, LOW);
  digitalWrite(Y_STEP_PIN, LOW);
  setEnable(X_EN_PIN, true);
  setEnable(Y_EN_PIN, true);
  xSteps = 0;
  ySteps = 0;
  Serial.println("ESP32_XY_CAPTURE_READY");
  Serial.println("Commands:");
  Serial.println("START");
  Serial.println("STOP");
  Serial.println("HOME");}
void loop() {
  String cmd = readLineNonBlocking();
  if (cmd.length() == 0) {
    delay(10);
    return;}
  if (isEspBootNoise(cmd)) return;
 
  if (cmd == "START") {
    runSnakeScan();}
  else if (cmd == "STOP") {
    stopRequested = false;
    returnToOrigin();
    Serial.println("STOPPED");}
  else if (cmd == "HOME") {
    stopRequested = false;
    returnToOrigin();}
  delay(10);}
