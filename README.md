# STANK Archive Pro V3 Performance Update

## Run
```bash
pip install -r requirements.txt
python main.py
```

## Build EXE
Run:
```bash
build_exe.bat
```

## What's updated
- Removed the deprecated Qt `invalidateFilter()` calls.
- Search/filter refresh now uses the newer Qt 6 filter-change API when available.
- Folder scanning now runs in a background worker so large source folders do not lock the main window while loading.
- File records are prepared off the UI thread before being handed to the table model.
- Existing V3 fast model/view selection behavior remains in place.
- Dark mode, new logo, archive move behavior, and `Original (Archived MM-DD-YYYY-HH꞉MM).ext` naming are retained.

## Recent update
- Double-clicking a file now asks before opening it.
- Right-clicking a file opens a context menu with Archive, Open, Copy Filename, Show in Explorer, and Properties.
- Right-click Archive creates renamed archive copies while keeping the original file in place.


## Updates

STANK Archive Pro includes a built-in **Check for Updates** button in the About window.
It checks the latest published GitHub Release at:

https://github.com/tonyaprile-droid/STANK-Archive-Pro/releases

If a newer tag such as `v1.0.1` is available, the app will offer to open the release page so the user can download it.
