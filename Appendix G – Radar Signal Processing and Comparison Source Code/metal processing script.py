import os
import re
import glob
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import zoom, gaussian_filter

# SESSION PATHS
METAL_SESSION = r" C:\radar_scan\dataset_raw\metal_object\object01\session02_200mm_1m_20.0f_20260425_192755"
BACKGROUND_SESSION = r" C:\radar_scan\dataset_raw\test\phantom01\session02_200mm_1m_20.0f_20260425_190740"

# OUTPUT FOLDER
OUTPUT_FOLDER = r"C:\radar_scan\final_figures\metal_pipeline_results"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
NUM_RX = 4
ADC_SAMPLES = 256
RANGE_BIN_START = 88
RANGE_BIN_END = 100
UPSAMPLE_FACTOR = 8
SMOOTH_SIGMA = 0.8
THRESHOLD = 0.50
def parse_xy_from_filename(filepath):
    name = os.path.basename(filepath)
    match = re.search(r"_x(-?\d+(?:\.\d+)?)_y(-?\d+(?:\.\d+)?)\.bin$", name)
    if not match:
        return None, None
    x = float(match.group(1))
    y = float(match.group(2))
    return x, y

def load_complex_adc(bin_path):
    raw = np.fromfile(bin_path, dtype=np.int16)

    if raw.size < 2:
        raise ValueError(f"File too small or empty: {bin_path}")

    #  I/Q pairing
    if raw.size % 2 != 0:
        raw = raw[:-1]

    iq = raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)

    samples_per_chirp = NUM_RX * ADC_SAMPLES
    num_chirps = iq.size // samples_per_chirp

    if num_chirps == 0:
        raise ValueError(
            f"Not enough samples in {bin_path}. "
            f"Check ADC_SAMPLES / NUM_RX settings."
        )

    iq = iq[:num_chirps * samples_per_chirp]
    iq = iq.reshape(num_chirps, NUM_RX, ADC_SAMPLES)

    return iq
# HELPER
def compute_range_profile(bin_path):
    adc = load_complex_adc(bin_path)
    adc = adc - np.mean(adc, axis=2, keepdims=True)

    window = np.hanning(ADC_SAMPLES).reshape(1, 1, ADC_SAMPLES)

    # Range FFT
    rng_fft = np.fft.fft(adc * window, axis=2)

    # Magnitude averaged over chirps and RX
    mag = np.abs(rng_fft)
    profile = np.mean(mag, axis=(0, 1))
    profile = profile[:ADC_SAMPLES]

    return profile

# =========================================================
# PROCESS ONE SESSION
# Outputs:
# - heatmap image
# - average range profile
# - *_image_linear.npy
# =========================================================
def process_session(session_folder, save_prefix, heatmap_title):
    # Find all frame .bin files
    all_bin_files = glob.glob(os.path.join(session_folder, "*.bin"))

    frame_files = []
    coords = []

    for f in all_bin_files:
        x, y = parse_xy_from_filename(f)
        if x is not None and y is not None:
            frame_files.append(f)
            coords.append((x, y))

    if len(frame_files) == 0:
        raise FileNotFoundError(
            f"No frame .bin files with x/y coordinates found in:\n{session_folder}"
        )

    xs = sorted(set([c[0] for c in coords]))
    ys = sorted(set([c[1] for c in coords]))

    x_to_idx = {x: i for i, x in enumerate(xs)}
    y_to_idx = {y: i for i, y in enumerate(ys)}

    image_linear = np.zeros((len(ys), len(xs)), dtype=np.float32)
    all_profiles = []

    print(f"\nProcessing session: {session_folder}")
    print(f"Found {len(frame_files)} frame files")
    print(f"Grid size = {len(xs)} x {len(ys)}")

    for file_path, (x, y) in zip(frame_files, coords):
        try:
            profile = compute_range_profile(file_path)
            all_profiles.append(profile)

            # Window max in selected range
            window = profile[RANGE_BIN_START:RANGE_BIN_END + 1]
            value = np.max(window)

            xi = x_to_idx[x]
            yi = y_to_idx[y]
            image_linear[yi, xi] = value

        except Exception as e:
            print(f"Skipping file بسبب error: {file_path}")
            print("Error:", e)

    if len(all_profiles) == 0:
        raise RuntimeError(f"No valid profiles were generated for {session_folder}")

    avg_profile = np.mean(np.array(all_profiles), axis=0)

    # Save linear image
    linear_npy_path = os.path.join(OUTPUT_FOLDER, f"{save_prefix}_image_linear.npy")
    np.save(linear_npy_path, image_linear)
    print("Saved:", linear_npy_path)

    # Plot average range profile
    plt.figure(figsize=(10, 6))
    plt.plot(avg_profile, linewidth=2, label="Average profile")
    plt.axvline(RANGE_BIN_START, linestyle="--", linewidth=2, label=f"Window start {RANGE_BIN_START}")
    plt.axvline(RANGE_BIN_END, linestyle="--", linewidth=2, label=f"Window end {RANGE_BIN_END}")
    plt.xlabel("Range bin")
    plt.ylabel("Average magnitude")
    plt.title("Average range profile over all scan positions")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()

    avg_profile_png = os.path.join(OUTPUT_FOLDER, f"{save_prefix}_avg_range_profile.png")
    plt.savefig(avg_profile_png, dpi=300)
    plt.close()
    print("Saved:", avg_profile_png)

    # -----------------------------------------------------
    # Convert heatmap to relative dB for display
    # -----------------------------------------------------
    eps = 1e-12
    max_val = np.max(image_linear) + eps
    heatmap_db = 20 * np.log10((image_linear + eps) / max_val)

    # Clamp lower display floor
    heatmap_db = np.clip(heatmap_db, -40, 0)

    # -----------------------------------------------------
    # Plot heatmap
    # -----------------------------------------------------
    extent = [min(xs), max(xs), min(ys), max(ys)]

    plt.figure(figsize=(8, 6))
    im = plt.imshow(
        heatmap_db,
        origin="lower",
        extent=extent,
        aspect="auto",
        cmap="jet",
        vmin=-40,
        vmax=0
    )
    cbar = plt.colorbar(im)
    cbar.set_label("Relative magnitude (dB)")

    plt.xlabel("X (mm)")
    plt.ylabel("Y (mm)")
    plt.title(f"{heatmap_title} (window max {RANGE_BIN_START}-{RANGE_BIN_END})")
    plt.tight_layout()

    heatmap_png = os.path.join(OUTPUT_FOLDER, f"{save_prefix}_heatmap.png")
    plt.savefig(heatmap_png, dpi=300)
    plt.close()
    print("Saved:", heatmap_png)

    return image_linear, xs, ys

# =========================================================
# FINAL METAL - BACKGROUND IMAGE
# =========================================================
def make_final_difference_image(metal_linear, background_linear, xs, ys):
    if metal_linear.shape != background_linear.shape:
        raise ValueError(
            f"Shape mismatch: metal {metal_linear.shape}, background {background_linear.shape}"
        )

    # Subtract background
    diff = metal_linear - background_linear

    # Keep only positive values
    diff = np.maximum(diff, 0)

    # Normalize
    if np.max(diff) > 0:
        diff = diff / np.max(diff)

    # Upsample for smoother visualization
    diff_up = zoom(diff, UPSAMPLE_FACTOR, order=3)

    # Light smoothing
    diff_smooth = gaussian_filter(diff_up, sigma=SMOOTH_SIGMA)

    # Normalize again
    if np.max(diff_smooth) > 0:
        diff_smooth = diff_smooth / np.max(diff_smooth)

    # Threshold weak clutter
    diff_smooth[diff_smooth < THRESHOLD] = 0

    # Normalize again after thresholding
    if np.max(diff_smooth) > 0:
        diff_smooth = diff_smooth / np.max(diff_smooth)

    extent = [min(xs), max(xs), min(ys), max(ys)]

    plt.figure(figsize=(8, 6))
    im = plt.imshow(
        diff_smooth,
        origin="lower",
        extent=extent,
        aspect="auto",
        cmap="jet",
        vmin=0,
        vmax=1,
        interpolation="nearest"
    )
    cbar = plt.colorbar(im)
    cbar.set_label("Normalized magnitude")

    plt.xlabel("X (mm)")
    plt.ylabel("Y (mm)")
    plt.title("FFT-based style no-tumor response image")
    plt.tight_layout()

    final_png = os.path.join(OUTPUT_FOLDER, "session3_notumor_20.0f_minus_background_final.png")
    plt.savefig(final_png, dpi=300)
    plt.show()
    print("Saved:", final_png)

# =========================================================
# MAIN
# =========================================================
def main():
    # 1) Process background
    background_linear, bg_xs, bg_ys = process_session(
        session_folder=BACKGROUND_SESSION,
        save_prefix="background3",
        heatmap_title="Background scan heatmap3"
    )

    # 2) Process metal
    metal_linear, metal_xs, metal_ys = process_session(
        session_folder=METAL_SESSION,
        save_prefix="session3notumor",
        heatmap_title="session3notumor scan heatmap"
    )

    # 3) Check grid consistency
    if bg_xs != metal_xs or bg_ys != metal_ys:
        raise ValueError(
            "Background and metal scans do not have the same x/y grid.\n"
            "Make sure both scans used the same scan area and step size."
        )

    # 4) Final difference image
    make_final_difference_image(
        metal_linear=metal_linear,
        background_linear=background_linear,
        xs=metal_xs,
        ys=metal_ys
    )

    print("\nAll processing finished.")
    print("Check results here:")
    print(OUTPUT_FOLDER)

if __name__ == "__main__":
    main()

