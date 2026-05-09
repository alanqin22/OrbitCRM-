"""
Rename Amazon CDN image filenames (e.g. 618lepY8pKL._AC_SL1500_.jpg)
to normalized image_1.jpg ... image_5.jpg in the 7 Electronics product
folders that were manually downloaded before the scraper was written.
"""

import os, shutil

IMAGE_BASE = r"D:\a\crm_agent\image"

# Only Electronics folders with non-standard filenames
TARGET_FOLDERS = [
    "Apple 2026 MacBook Neo 13-inch Laptop with Apple A18 Pro chip",
    "Brother DCP-L2640DW Business Monochrome Multifunction Laser Printer",
    "LG 24U411A-B 23.8  FHD (1920x1080)  IPS  120Hz",
    "Lenovo ThinkPad T490 14'' FHD (1920 x 1080) IPS Business Laptop Computer",
    "MSI Gaming RTX 5090 32G SUPRIM SOC Graphics Card",
    "Sony Alpha ZVE10 APSC Mirrorless Interchangeable Lens Camera",
    "WD 2TB My Passport Portable External Hard Drive HDD",
]

total_renamed = 0

for folder_name in TARGET_FOLDERS:
    folder_path = os.path.join(IMAGE_BASE, "Electronics", folder_name)
    if not os.path.isdir(folder_path):
        print(f"SKIP (not found): {folder_name}")
        continue

    all_files = sorted(
        f for f in os.listdir(folder_path)
        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
    )

    # Skip if already normalized
    if all(f.startswith("image_") for f in all_files):
        print(f"OK (already normalized): {folder_name[:60]}")
        continue

    # Split: already normalized vs non-standard
    standard = [f for f in all_files if f.startswith("image_")]
    non_standard = sorted(f for f in all_files if not f.startswith("image_"))

    # Start numbering after the last existing image_N
    next_n = max((int(f.split("_")[1].split(".")[0]) for f in standard), default=0) + 1

    print(f"Renaming: {folder_name[:60]} (existing: {standard}, next_n={next_n})")
    for old_name in non_standard:
        new_name = f"image_{next_n}.jpg"
        old_path = os.path.join(folder_path, old_name)
        new_path = os.path.join(folder_path, new_name)
        os.rename(old_path, new_path)
        print(f"  {old_name} -> {new_name}")
        total_renamed += 1
        next_n += 1

print(f"\nDone. {total_renamed} files renamed.")
print("Next step: run upload_renamed_electronics.py to push to cPanel.")
