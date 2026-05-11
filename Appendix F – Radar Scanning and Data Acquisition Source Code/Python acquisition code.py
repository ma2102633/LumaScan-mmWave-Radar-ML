import serial
import serial.tools.list_ports
import time
import shutil
import os
import subprocess
import glob
from datetime import datetime

# USER SETTINGS
SERIAL_PORT = "COM14"
BAUD_RATE = 115200

POSTPROC_FOLDER = r"C:\ti\mmwave_studio_02_01_01_00\mmWaveStudio\PostProc"
CLI_EXE = os.path.join(POSTPROC_FOLDER, "DCA1000EVM_CLI_Control.exe")
CLI_JSON = os.path.join(POSTPROC_FOLDER, "cf.json")

# Choose one:
# "test"
# "tumour"
# "no_tumour"
SCAN_LABEL = "no_tumour"

# Optional identifiers for better dataset organization
PATIENT_ID = "phantom01"
SESSION_NAME = "session04_200mm_1m_20.0f_3"

BASE_SAVE_FOLDER = r"C:\radar_scan\dataset_raw"

# Radar timing
CAPTURE_SECONDS = 1.5
WAIT_FILE_TIMEOUT = 15.0

# Small pause after starting record before trigger
ARM_DELAY_SECONDS = 0.30

# DATASET FOLDER SETUP
timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
SAVE_FOLDER = os.path.join(
    BASE_SAVE_FOLDER,
    SCAN_LABEL,
    PATIENT_ID,
    f"{SESSION_NAME}_{timestamp_str}"
)

os.makedirs(SAVE_FOLDER, exist_ok=True)

# HELPERS
def list_ports():
    print("Available serial ports:")
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("  No COM ports found")
    for p in ports:
        print(f"  {p.device} - {p.description}")
    print()


def run_cli(command: str):
    cmd = [CLI_EXE, command, CLI_JSON]
    print("Running:", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=25,
            cwd=POSTPROC_FOLDER
        )
    except Exception as e:
        print("Failed to run command:", e)
        return False, "", str(e)

    stdout = result.stdout.strip() if result.stdout else ""
    stderr = result.stderr.strip() if result.stderr else ""

    if stdout:
        print(stdout)
    if stderr:
        print(stderr)

    return result.returncode == 0, stdout, stderr


def start_record_background():
    cmd = [CLI_EXE, "start_record", CLI_JSON]
    print("Starting record:", " ".join(cmd))
    return subprocess.Popen(
        cmd,
        cwd=POSTPROC_FOLDER,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def get_bin_files():
    return glob.glob(os.path.join(POSTPROC_FOLDER, "*.bin"))


def snapshot_bin_files():
    snapshot = {}
    for f in get_bin_files():
        try:
            snapshot[f] = (os.path.getmtime(f), os.path.getsize(f))
        except Exception:
            pass
    return snapshot


def find_updated_bin(old_snapshot, timeout=15.0):
    start = time.time()

    while time.time() - start < timeout:
        current_files = get_bin_files()
        newest_file = None
        newest_mtime = 0

        for f in current_files:
            try:
                mtime = os.path.getmtime(f)
                size = os.path.getsize(f)
            except Exception:
                continue

            old_mtime, old_size = old_snapshot.get(f, (0, 0))

            # File is considered updated if timestamp changed or size changed
            if size > 0 and (mtime > old_mtime or size != old_size):
                if mtime > newest_mtime:
                    newest_mtime = mtime
                    newest_file = f

        if newest_file:
            return newest_file

        time.sleep(1.0)

    return None


def safe_send_line(ser, text):
    try:
        ser.write((text + "\n").encode())
        return True
    except Exception as e:
        print(f"Failed to send '{text}':", e)
        return False


def safe_stop_and_origin(ser):
    try:
        print("Sending STOP...")
        safe_send_line(ser, "STOP")
        time.sleep(2)
    except Exception as e:
        print("Could not send STOP:", e)


def open_serial():
    print("Connecting to ESP32...")
    try:
        ser = serial.Serial(
            SERIAL_PORT,
            BAUD_RATE,
            timeout=1,
            dsrdtr=False,
            rtscts=False
        )

        # Prevent auto-reset issues on some boards
        ser.setDTR(False)
        ser.setRTS(False)
        time.sleep(2)

        print(f"Connected to ESP32 on {SERIAL_PORT}")

        ser.reset_input_buffer()
        ser.reset_output_buffer()

        return ser

    except Exception as e:
        print(f"Could not open {SERIAL_PORT}")
        print("Error:", e)
        raise SystemExit("Serial connection failed")


def save_metadata_file():
    meta_path = os.path.join(SAVE_FOLDER, "scan_info.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"scan_label={SCAN_LABEL}\n")
        f.write(f"patient_id={PATIENT_ID}\n")
        f.write(f"session_name={SESSION_NAME}\n")
        f.write(f"timestamp={timestamp_str}\n")
        f.write(f"serial_port={SERIAL_PORT}\n")
        f.write(f"baud_rate={BAUD_RATE}\n")
        f.write(f"capture_seconds={CAPTURE_SECONDS}\n")
        f.write(f"wait_file_timeout={WAIT_FILE_TIMEOUT}\n")
        f.write(f"postproc_folder={POSTPROC_FOLDER}\n")
        f.write(f"cli_exe={CLI_EXE}\n")
        f.write(f"cli_json={CLI_JSON}\n")


# VALIDATION
print("Checking files...")

if SCAN_LABEL not in ["test", "tumour", "no_tumour"]:
    raise ValueError("SCAN_LABEL must be one of: test, tumour, no_tumour")

if not os.path.exists(CLI_EXE):
    raise FileNotFoundError(f"Could not find CLI exe: {CLI_EXE}")

if not os.path.exists(CLI_JSON):
    raise FileNotFoundError(f"Could not find CLI json: {CLI_JSON}")

save_metadata_file()

print("Save folder is:")
print(SAVE_FOLDER)
print()

list_ports()
ser = open_serial()

print("Configuring DCA1000...")

ok, _, _ = run_cli("fpga")
if not ok:
    ser.close()
    raise SystemExit("fpga command failed")

ok, _, _ = run_cli("record")
if not ok:
    ser.close()
    raise SystemExit("record command failed")

# MAIN STATE
frame_id = 0
current_position = ("0.000", "0.000")
waiting_for_trigger = False
pending_snapshot = None
record_proc = None

print()
print("IMPORTANT:")
print("1) mmWave Studio must already be open")
print("2) Radar must already be configured")
print("3) No of Frames must be 0")
print("4) Trigger Frame must have been clicked ONCE before automation")
print(f"5) Current dataset type = {SCAN_LABEL}")
print(f"6) Current save folder  = {SAVE_FOLDER}")
print()
print("Workflow:")
print("scanner moves -> scanner stops -> radar captures -> file saves -> scanner continues")
print()
print("Press Ctrl + C anytime to stop and return to origin.")
print()

# MAIN LOOP
try:
    print("Sending START command to ESP32...")
    safe_send_line(ser, "START")

    while True:
        raw_line = ser.readline()
        if not raw_line:
            continue

        line = raw_line.decode(errors="ignore").strip()
        if not line:
            continue

        # Ignore ESP boot noise
        if (
            line.startswith("ets ")
            or line.startswith("rst:")
            or line.startswith("configsip:")
            or line.startswith("clk_drv:")
            or line.startswith("mode:")
            or line.startswith("load:")
            or line.startswith("entry ")
        ):
            continue

        print("<-", line)
        # Scanner reached a point and is waiting
        # Expected format: READY x y
        if line.startswith("READY"):
            parts = line.split()

            if len(parts) >= 3:
                current_position = (parts[1], parts[2])
                print(f"Scanner stopped at x={parts[1]} y={parts[2]}")
            else:
                print("READY received but coordinates missing")
                safe_stop_and_origin(ser)
                break

            # Snapshot old .bin state before recording
            pending_snapshot = snapshot_bin_files()

            # Start DCA recording
            record_proc = start_record_background()
            time.sleep(ARM_DELAY_SECONDS)

            # Tell ESP32 to trigger radar now
            safe_send_line(ser, "CAPTURE_NOW")
            print("Sent CAPTURE_NOW to ESP32")
            waiting_for_trigger = True

        # -------------------------------------------------
        # ESP32 says trigger pulse was sent
        # -------------------------------------------------
        elif "TRIGGER_SENT" in line and waiting_for_trigger:
            print("Trigger received. Capturing radar data...")

            time.sleep(CAPTURE_SECONDS)

            ok, stdout, stderr = run_cli("stop_record")
            stop_msg = (stdout + " " + stderr).lower()

            # Sometimes stop_record says no record process is running
            benign_stop = "no record process is running" in stop_msg

            try:
                if record_proc is not None:
                    record_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if record_proc is not None:
                    record_proc.kill()

            updated_file = find_updated_bin(pending_snapshot, WAIT_FILE_TIMEOUT)

            if updated_file is None:
                print("Warning: no .bin file in PostProc was updated")
                safe_stop_and_origin(ser)
                break

            if not ok and not benign_stop:
                print("stop_record failed")
                safe_stop_and_origin(ser)
                break

            x, y = current_position
            filename = (
                f"{SCAN_LABEL}_"
                f"{PATIENT_ID}_"
                f"{SESSION_NAME}_"
                f"frame_{frame_id:04d}_"
                f"x{x}_y{y}.bin"
            )
            destination = os.path.join(SAVE_FOLDER, filename)

            try:
                shutil.copy2(updated_file, destination)
                print("Copied from:", updated_file)
                print("Saved to   :", destination)
                frame_id += 1
            except Exception as e:
                print("Copy failed:", e)
                safe_stop_and_origin(ser)
                break

            # Tell ESP32 it can move to next point
            safe_send_line(ser, "OK")
            print("Sent OK to ESP32")

            waiting_for_trigger = False
            pending_snapshot = None
            record_proc = None

        # -------------------------------------------------
        # Scan completed normally
        # -------------------------------------------------
        elif "SCAN_DONE" in line:
            print("Scan complete")
            break

        # -------------------------------------------------
        # Scan aborted
        # -------------------------------------------------
        elif "SCAN_ABORTED" in line:
            print("Scan aborted")
            break

        # -------------------------------------------------
        # Scanner reached home/origin
        # -------------------------------------------------
        elif "AT_ORIGIN" in line:
            print("Scanner returned to origin")

        # -------------------------------------------------
        # Optional status messages
        # -------------------------------------------------
        elif line.startswith("SCAN_START"):
            print("Scanner started snake scan")

        elif line.startswith("RETURNING_TO_ORIGIN"):
            print("Scanner is returning to origin")

except KeyboardInterrupt:
    print("\nCtrl + C detected")
    safe_stop_and_origin(ser)

finally:
    try:
        ser.close()
    except Exception:
        pass
    print("Serial closed")
