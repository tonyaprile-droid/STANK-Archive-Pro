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
