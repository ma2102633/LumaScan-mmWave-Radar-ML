import os
import re
import glob
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter

# =========================================================
# CHANGE THESE 3 PATHS TO YOUR REAL SESSION FOLDERS
# =========================================================
BACKGROUND_SESSION = r"C:\radar_scan\dataset_raw\test\phantom01\session04_200mm_1m_20.0f_20260430_014929"
TUMOUR_SESSION = r"C:\radar_scan\dataset_raw\tumour\phantom01\session02_200mm_1m_20260425_034828"
NO_TUMOUR_SESSION = r"C:\radar_scan\dataset_raw\no_tumour\phantom01\session02_200mm_1m_20260425_033314"

# =========================================================
# OUTPUT FOLDER
# =========================================================
OUTPUT_FOLDER = r"C:\radar_scan\final_figures\tumour_compare_results"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# =========================================================
# RADAR / DATA SETTINGS
# Change only if your radar config is different
# =========================================================
NUM_ADC_SAMPLES = 256
NUM_RX = 4
RANGE_FFT_SIZE = 256

# =========================================================
# FEATURE EXTRACTION SETTINGS
# For tumour/no_tumour, window_sum is usually better than
# just taking one peak like the metal-object case.
# =========================================================
FEATURE_MODE = "window_sum"     # options: window_sum, window_mean, window_max
RANGE_BIN_START = 88
RANGE_BIN_END = 100

# =========================================================
# FINAL DISPLAY SETTINGS
# =========================================================
SMOOTH_SIGMA = 0.8
EPS = 1e-12

# =========================================================
# HELPERS
# =========================================================
def parse_xy_from_filename(filepath):
    """
    Extract x and y from filenames like:
    ..._x0.00_y25.00.bin
    """
    name = os.path.basename(filepath)

    mx = re.search(r'_x(-?\d+(?:\.\d+)?)', name)
    my = re.search(r'_y(-?\d+(?:\.\d+)?)\.bin$', name)

    if not mx or not my:
        raise ValueError(f"Could not parse x,y from filename: {name}")

    x = float(mx.group(1))
    y = float(my.group(1))
    return x, y


def read_dca1000_complex1x(filepath, num_adc_samples=256, num_rx=4):
    """
    Read raw DCA1000 ADC data assuming interleaved int16 I/Q.
    """
    raw = np.fromfile(filepath, dtype=np.int16)

    ints_per_chirp = num_adc_samples * num_rx * 2
    usable = (raw.size // ints_per_chirp) * ints_per_chirp
    raw = raw[:usable]

    if raw.size == 0:
        return None

    raw = raw.reshape(-1, num_rx, num_adc_samples, 2)

    complex_data = raw[..., 0].astype(np.float32) + 1j * raw[..., 1].astype(np.float32)
    return complex_data


def compute_mean_range_profile(complex_data, fft_size=256):
    """
    Compute average range FFT magnitude profile.
    """
    if complex_data is None:
        return None

    # Remove DC
    complex_data = complex_data - np.mean(complex_data, axis=-1, keepdims=True)

    # Apply Hanning window
    window = np.hanning(complex_data.shape[-1]).astype(np.float32)
    windowed = complex_data * window

    # FFT over fast-time dimension
    range_fft = np.fft.fft(windowed, n=fft_size, axis=-1)
    mag = np.abs(range_fft)

    # Average over chirps and RX channels
    mean_profile = np.mean(mag, axis=(0, 1))
    return mean_profile


def compute_point_value(mean_profile):
    """
    Extract one scalar value from the selected range window.
    """
    if mean_profile is None:
        return np.nan

    start = max(0, RANGE_BIN_START)
    end = min(len(mean_profile), RANGE_BIN_END)

    if end <= start:
        return np.nan

    roi = mean_profile[start:end]

    if FEATURE_MODE == "window_sum":
        return float(np.sum(roi))
    elif FEATURE_MODE == "window_mean":
        return float(np.mean(roi))
    elif FEATURE_MODE == "window_max":
        return float(np.max(roi))
    else:
        raise ValueError("FEATURE_MODE must be one of: window_sum, window_mean, window_max")


def build_grid(records):
    """
    Build 2D image grid from x/y/value records.
    """
    xs = sorted(set(r["x"] for r in records))
    ys = sorted(set(r["y"] for r in records))

    x_to_idx = {x: i for i, x in enumerate(xs)}
    y_to_idx = {y: i for i, y in enumerate(ys)}

    img = np.full((len(ys), len(xs)), np.nan, dtype=np.float32)

    for r in records:
        img[y_to_idx[r["y"]], x_to_idx[r["x"]]] = r["value"]

    return xs, ys, img


def save_heatmap_db(xs, ys, img, title, save_path):
    """
    Save a relative dB heatmap for one session.
    """
    if np.all(np.isnan(img)):
        raise RuntimeError("Image is all NaN")

    max_val = np.nanmax(img)
    img_db = 20 * np.log10(np.maximum(img, EPS) / max_val)

    plt.figure(figsize=(8, 6))
    extent = [min(xs), max(xs), min(ys), max(ys)]

    plt.imshow(
        img_db,
        origin="lower",
        aspect="auto",
        extent=extent,
        interpolation="nearest",
        cmap="jet",
        vmin=-40,
        vmax=0
    )
    plt.colorbar(label="Relative magnitude (dB)")
    plt.xlabel("X (mm)")
    plt.ylabel("Y (mm)")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"Saved: {save_path}")


def save_avg_profile(profile, title, save_path):
    """
    Save average range profile plot.
    """
    plt.figure(figsize=(8, 4))
    plt.plot(profile, label="Average profile")
    plt.axvline(RANGE_BIN_START, linestyle="--", label=f"Start {RANGE_BIN_START}")
    plt.axvline(RANGE_BIN_END, linestyle="--", label=f"End {RANGE_BIN_END}")
    plt.xlabel("Range bin")
    plt.ylabel("Average magnitude")
    plt.title(title)
    plt.legend()
    plt.tight_layout()
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"Saved: {save_path}")


def process_session(session_folder, save_prefix, heatmap_title):
    """
    Process one session folder into:
    - image grid
    - average range profile
    - heatmap png
    - linear npy
    """
    if not os.path.isdir(session_folder):
        raise FileNotFoundError(f"Session folder not found: {session_folder}")

    bin_files = sorted(glob.glob(os.path.join(session_folder, "*.bin")))
    if not bin_files:
        raise FileNotFoundError(f"No .bin files found in: {session_folder}")

    records = []
    all_profiles = []

    print(f"\nProcessing session: {session_folder}")
    print(f"Found {len(bin_files)} .bin files")

    for f in bin_files:
        name = os.path.basename(f)

        try:
            x, y = parse_xy_from_filename(f)

            complex_data = read_dca1000_complex1x(
                f,
                num_adc_samples=NUM_ADC_SAMPLES,
                num_rx=NUM_RX
            )

            mean_profile = compute_mean_range_profile(
                complex_data,
                fft_size=RANGE_FFT_SIZE
            )

            value = compute_point_value(mean_profile)

            records.append({
                "file": name,
                "x": x,
                "y": y,
                "value": value
            })

            if mean_profile is not None:
                all_profiles.append(mean_profile)

        except Exception as e:
            print(f"Failed on {name}: {e}")

    if not records:
        raise RuntimeError(f"No valid files processed in {session_folder}")

    xs, ys, img = build_grid(records)
    avg_profile = np.mean(np.stack(all_profiles, axis=0), axis=0)

    # Save linear image
    npy_path = os.path.join(OUTPUT_FOLDER, f"{save_prefix}_image_linear.npy")
    np.save(npy_path, img)
    print(f"Saved: {npy_path}")

    # Save heatmap
    heatmap_path = os.path.join(OUTPUT_FOLDER, f"{save_prefix}_heatmap.png")
    save_heatmap_db(xs, ys, img, heatmap_title, heatmap_path)

    # Save average profile
    profile_path = os.path.join(OUTPUT_FOLDER, f"{save_prefix}_avg_range_profile.png")
    save_avg_profile(avg_profile, f"{save_prefix} average range profile", profile_path)

    return xs, ys, img, avg_profile


def normalize_positive(img):
    """
    Keep only positive values and normalize to 0..1.
    """
    img = np.maximum(img, 0)

    if np.nanmax(img) > 0:
        img = img / np.nanmax(img)

    img = gaussian_filter(img, sigma=SMOOTH_SIGMA)

    if np.nanmax(img) > 0:
        img = img / np.nanmax(img)

    return img


def save_positive_map(xs, ys, img, title, save_path):
    """
    Save a 0..1 positive-only comparison map.
    """
    plt.figure(figsize=(8, 6))
    extent = [min(xs), max(xs), min(ys), max(ys)]

    plt.imshow(
        img,
        origin="lower",
        aspect="auto",
        extent=extent,
        interpolation="nearest",
        cmap="jet",
        vmin=0,
        vmax=1
    )
    plt.colorbar(label="Normalized magnitude")
    plt.xlabel("X (mm)")
    plt.ylabel("Y (mm)")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"Saved: {save_path}")


def save_overlay_profiles(bg_profile, tumour_profile, no_tumour_profile, save_path):
    """
    Overlay all 3 average profiles in one plot.
    """
    plt.figure(figsize=(9, 5))
    plt.plot(bg_profile, label="background")
    plt.plot(tumour_profile, label="tumour")
    plt.plot(no_tumour_profile, label="no_tumour")
    plt.axvline(RANGE_BIN_START, linestyle="--", label=f"Start {RANGE_BIN_START}")
    plt.axvline(RANGE_BIN_END, linestyle="--", label=f"End {RANGE_BIN_END}")
    plt.xlabel("Range bin")
    plt.ylabel("Average magnitude")
    plt.title("Average range profiles comparison")
    plt.legend()
    plt.tight_layout()
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"Saved: {save_path}")


# =========================================================
# MAIN
# =========================================================
def main():
    # -----------------------------------------------------
    # Process background
    # -----------------------------------------------------
    bg_xs, bg_ys, background_img, background_profile = process_session(
        BACKGROUND_SESSION,
        save_prefix="background",
        heatmap_title="Background scan heatmap"
    )

    # -----------------------------------------------------
    # Process tumour
    # -----------------------------------------------------
    tumour_xs, tumour_ys, tumour_img, tumour_profile = process_session(
        TUMOUR_SESSION,
        save_prefix="tumour",
        heatmap_title="Tumour scan heatmap"
    )

    # -----------------------------------------------------
    # Process no_tumour
    # -----------------------------------------------------
    no_xs, no_ys, no_tumour_img, no_tumour_profile = process_session(
        NO_TUMOUR_SESSION,
        save_prefix="no_tumour",
        heatmap_title="No-tumour scan heatmap"
    )

    # -----------------------------------------------------
    # Check grids match
    # -----------------------------------------------------
    if bg_xs != tumour_xs or bg_ys != tumour_ys:
        raise ValueError("Background and tumour grids do not match")
    if bg_xs != no_xs or bg_ys != no_ys:
        raise ValueError("Background and no_tumour grids do not match")

    xs = bg_xs
    ys = bg_ys

    # -----------------------------------------------------
    # Save overlay profile comparison
    # -----------------------------------------------------
    overlay_path = os.path.join(OUTPUT_FOLDER, "all_avg_profiles_comparison.png")
    save_overlay_profiles(background_profile, tumour_profile, no_tumour_profile, overlay_path)

    # -----------------------------------------------------
    # Create comparison images
    # -----------------------------------------------------
    tumour_minus_background = tumour_img - background_img
    no_tumour_minus_background = no_tumour_img - background_img

    # This is the most important map:
    # what remains stronger in tumour compared to no_tumour
    tumour_signature = tumour_minus_background - no_tumour_minus_background

    tumour_minus_background = normalize_positive(tumour_minus_background)
    no_tumour_minus_background = normalize_positive(no_tumour_minus_background)
    tumour_signature = normalize_positive(tumour_signature)

    # Save numpy arrays
    np.save(os.path.join(OUTPUT_FOLDER, "tumour_minus_background.npy"), tumour_minus_background)
    np.save(os.path.join(OUTPUT_FOLDER, "no_tumour_minus_background.npy"), no_tumour_minus_background)
    np.save(os.path.join(OUTPUT_FOLDER, "tumour_signature_vs_no_tumour.npy"), tumour_signature)

    # Save images
    save_positive_map(
        xs, ys,
        tumour_minus_background,
        "Tumour - Background",
        os.path.join(OUTPUT_FOLDER, "tumour_minus_background.png")
    )

    save_positive_map(
        xs, ys,
        no_tumour_minus_background,
        "No-tumour - Background",
        os.path.join(OUTPUT_FOLDER, "no_tumour_minus_background.png")
    )

    save_positive_map(
        xs, ys,
        tumour_signature,
        "Tumour signature vs No-tumour",
        os.path.join(OUTPUT_FOLDER, "tumour_signature_vs_no_tumour.png")
    )

    print("\nAll processing finished.")
    print("Check results here:")
    print(OUTPUT_FOLDER)


if __name__ == "__main__":
    main()
