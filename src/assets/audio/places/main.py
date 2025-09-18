import os
import shutil

def copy_files_lowercase():
    cwd = os.getcwd()
    target_dir = os.path.join(cwd, "lowercase")

    os.makedirs(target_dir, exist_ok=True)

    for filename in os.listdir(cwd):
        src = os.path.join(cwd, filename)
        if os.path.isfile(src):
            new_filename = filename.lower()
            dst = os.path.join(target_dir, new_filename)

            # If conflict, skip (to avoid overwrite)
            if os.path.exists(dst):
                print(f"Skipped (conflict): {filename} -> {new_filename}")
                continue

            shutil.copy2(src, dst)
            print(f"Copied: {filename} -> {new_filename}")

if __name__ == "__main__":
    copy_files_lowercase()
