import os
import sys
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    Qt, QSettings, QTimer, QFileSystemWatcher, QUrl,
    QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
    QObject, QRunnable, QThreadPool, Signal, Slot
)
from PySide6.QtGui import (
    QAction, QDesktopServices, QKeySequence, QFont, QColor, QBrush,
    QPixmap, QIcon, QImage, QPainter, QPen
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSplitter, QTextEdit,
    QVBoxLayout, QWidget, QAbstractItemView, QHeaderView, QDialog,
    QScrollArea, QTableView, QMenu
)

APP_NAME = "STANK Archive Pro"
CURRENT_VERSION = "1.0.0"
GITHUB_OWNER = "tonyaprile-droid"
GITHUB_REPO = "STANK-Archive-Pro"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
SUPPORTED_TEXT = {".txt", ".csv", ".log", ".json", ".xml", ".md", ".py", ".ini"}
SUPPORTED_IMAGE = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
SUPPORTED_DOC = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


def resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / relative_path


def normalize_version(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lower().lstrip("v")
    parts: list[int] = []
    for piece in cleaned.replace("-", ".").split("."):
        number = ""
        for ch in piece:
            if ch.isdigit():
                number += ch
            else:
                break
        if number:
            parts.append(int(number))
    return tuple(parts or [0])


def is_newer_version(latest: str, current: str) -> bool:
    left = list(normalize_version(latest))
    right = list(normalize_version(current))
    length = max(len(left), len(right))
    left += [0] * (length - len(left))
    right += [0] * (length - len(right))
    return tuple(left) > tuple(right)


@dataclass
class ArchiveAction:
    original_path: Path
    archived_path: Path


@dataclass
class FileRecord:
    path: Path
    name: str
    modified_ts: float
    modified_text: str
    type_text: str
    size: int
    size_text: str


class FileTableModel(QAbstractTableModel):
    HEADERS = ["✓", "Name", "Modified", "Type", "Size"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records: list[FileRecord] = []
        self.checked_paths: set[str] = set()
        self.dark_mode = False
        self.icon_cache: dict[str, QIcon] = {}
        self.row_bg = QColor("#ffffff")
        self.row_fg = QColor("#15202b")
        self.checked_bg = QColor("#8ed4ff")
        self.checked_fg = QColor("#04182a")

    def set_theme(self, dark: bool):
        self.dark_mode = dark
        if dark:
            self.row_bg = QColor("#111827")
            self.row_fg = QColor("#eaf2ff")
            self.checked_bg = QColor("#1f6feb")
            self.checked_fg = QColor("#ffffff")
        else:
            self.row_bg = QColor("#ffffff")
            self.row_fg = QColor("#15202b")
            self.checked_bg = QColor("#8ed4ff")
            self.checked_fg = QColor("#04182a")
        if self.records:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.records) - 1, self.columnCount() - 1), [Qt.BackgroundRole, Qt.ForegroundRole, Qt.FontRole])

    def set_records(self, records: list[FileRecord]):
        existing = {str(r.path) for r in records}
        self.checked_paths.intersection_update(existing)
        self.beginResetModel()
        self.records = records
        self.endResetModel()

    def set_files(self, paths: list[Path]):
        records = []
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue
            modified = datetime.fromtimestamp(stat.st_mtime)
            records.append(FileRecord(
                path=path,
                name=path.name,
                modified_ts=stat.st_mtime,
                modified_text=modified.strftime("%Y-%m-%d %I:%M %p"),
                type_text=path.suffix.lower().replace(".", "") or "file",
                size=stat.st_size,
                size_text=self.human_size(stat.st_size),
            ))
        self.set_records(records)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        record = self.records[index.row()]
        checked = str(record.path) in self.checked_paths
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return "✓" if checked else ""
            if col == 1:
                return record.name
            if col == 2:
                return record.modified_text
            if col == 3:
                return record.type_text
            if col == 4:
                return record.size_text
        if role == Qt.CheckStateRole and col == 0:
            return Qt.Checked if checked else Qt.Unchecked
        if role == Qt.DecorationRole and col == 1:
            return self.file_icon_for_path(record.path)
        if role == Qt.UserRole:
            if col == 2:
                return record.modified_ts
            if col == 4:
                return record.size
            return str(record.path)
        if role == Qt.BackgroundRole:
            return QBrush(self.checked_bg if checked else self.row_bg)
        if role == Qt.ForegroundRole:
            if checked and col in (0, 1):
                return QBrush(QColor("#003f86") if not self.dark_mode else QColor("#ffffff"))
            return QBrush(self.checked_fg if checked else self.row_fg)
        if role == Qt.FontRole:
            font = QFont("Segoe UI", 12)
            font.setBold(bool(checked and col in (0, 1)))
            return font
        if role == Qt.TextAlignmentRole:
            if col == 0:
                return Qt.AlignCenter
            return Qt.AlignVCenter | Qt.AlignLeft
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False
        if role == Qt.CheckStateRole and index.column() == 0:
            path_str = str(self.records[index.row()].path)
            if value == Qt.Checked:
                self.checked_paths.add(path_str)
            else:
                self.checked_paths.discard(path_str)
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), self.columnCount() - 1), [Qt.DisplayRole, Qt.CheckStateRole, Qt.BackgroundRole, Qt.ForegroundRole, Qt.FontRole])
            return True
        return False

    def toggle_row(self, source_row: int):
        if source_row < 0 or source_row >= len(self.records):
            return
        idx = self.index(source_row, 0)
        state = Qt.Unchecked if str(self.records[source_row].path) in self.checked_paths else Qt.Checked
        self.setData(idx, state, Qt.CheckStateRole)

    def set_checked_paths_bulk(self, paths: list[Path], checked: bool):
        # High-performance bulk update: change the set once, then notify the view once.
        path_strings = {str(p) for p in paths}
        if checked:
            self.checked_paths.update(path_strings)
        else:
            self.checked_paths.difference_update(path_strings)
        if self.records:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.records) - 1, self.columnCount() - 1),
                [Qt.DisplayRole, Qt.CheckStateRole, Qt.BackgroundRole, Qt.ForegroundRole, Qt.FontRole]
            )

    def clear_checks(self):
        if not self.checked_paths:
            return
        self.checked_paths.clear()
        if self.records:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.records) - 1, self.columnCount() - 1),
                [Qt.DisplayRole, Qt.CheckStateRole, Qt.BackgroundRole, Qt.ForegroundRole, Qt.FontRole]
            )

    def path_at(self, source_row: int) -> Path | None:
        if 0 <= source_row < len(self.records):
            p = self.records[source_row].path
            return p if p.exists() else None
        return None

    def checked_existing_paths(self) -> list[Path]:
        result = []
        for record in self.records:
            if str(record.path) in self.checked_paths and record.path.exists():
                result.append(record.path)
        return result

    def file_icon_for_path(self, path: Path) -> QIcon:
        ext = path.suffix.lower() or "file"
        if ext in self.icon_cache:
            return self.icon_cache[ext]
        label, color = self.file_icon_specs(ext)
        pixmap = QPixmap(28, 28)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(5, 3, 18, 22, 4, 4)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRect(8, 8, 12, 3)
        painter.drawRect(8, 13, 12, 3)
        painter.drawRect(8, 18, 8, 3)
        painter.setPen(QPen(QColor("#ffffff")))
        font = QFont("Segoe UI", 6)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(5, 19, 18, 9, Qt.AlignCenter, label)
        painter.end()
        icon = QIcon(pixmap)
        self.icon_cache[ext] = icon
        return icon

    @staticmethod
    def file_icon_specs(ext: str) -> tuple[str, str]:
        if ext == ".pdf":
            return "PDF", "#d93025"
        if ext in {".doc", ".docx"}:
            return "DOC", "#2b66c3"
        if ext in {".xls", ".xlsx", ".csv"}:
            return "XLS", "#18864b"
        if ext in {".ppt", ".pptx"}:
            return "PPT", "#d05a26"
        if ext in SUPPORTED_IMAGE:
            return "IMG", "#3d83d9"
        if ext in SUPPORTED_TEXT:
            return "TXT", "#5d7085"
        return "FILE", "#6f7f90"

    @staticmethod
    def human_size(num: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if num < 1024:
                return f"{num:.0f} {unit}"
            num /= 1024
        return f"{num:.1f} TB"


class FileFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.setDynamicSortFilter(True)

    def set_query(self, query: str):
        self.query = query.strip().lower()
        # Qt 6.10 deprecated invalidateFilter(). Use the newer begin/end API when available.
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            try:
                self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
            except TypeError:
                self.endFilterChange()
        else:
            self.invalidate()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self.query:
            return True
        model: FileTableModel = self.sourceModel()  # type: ignore[assignment]
        if source_row < 0 or source_row >= len(model.records):
            return False
        return self.query in model.records[source_row].name.lower()

    def lessThan(self, left, right):
        model: FileTableModel = self.sourceModel()  # type: ignore[assignment]
        l = model.records[left.row()]
        r = model.records[right.row()]
        col = left.column()
        if col == 2:
            return l.modified_ts < r.modified_ts
        if col == 4:
            return l.size < r.size
        if col == 3:
            return l.type_text.lower() < r.type_text.lower()
        return l.name.lower() < r.name.lower()


class FolderScanSignals(QObject):
    finished = Signal(int, list, str)


class FolderScanTask(QRunnable):
    def __init__(self, token: int, folder: Path):
        super().__init__()
        self.token = token
        self.folder = folder
        self.signals = FolderScanSignals()

    @Slot()
    def run(self):
        records: list[FileRecord] = []
        error = ""
        try:
            paths = [p for p in self.folder.iterdir() if p.is_file()]
            for path in paths:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                modified = datetime.fromtimestamp(stat.st_mtime)
                records.append(FileRecord(
                    path=path,
                    name=path.name,
                    modified_ts=stat.st_mtime,
                    modified_text=modified.strftime("%Y-%m-%d %I:%M %p"),
                    type_text=path.suffix.lower().replace(".", "") or "file",
                    size=stat.st_size,
                    size_text=FileTableModel.human_size(stat.st_size),
                ))
            records.sort(key=lambda r: r.modified_ts, reverse=True)
        except OSError as exc:
            error = str(exc)
        self.signals.finished.emit(self.token, records, error)


class UpdateCheckSignals(QObject):
    finished = Signal(bool, str, str, str, str)


class UpdateCheckTask(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = UpdateCheckSignals()

    @Slot()
    def run(self):
        try:
            request = urllib.request.Request(
                GITHUB_API_LATEST,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "STANK-Archive-Pro",
                },
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
            latest_tag = data.get("tag_name", "").strip()
            latest_name = data.get("name", latest_tag).strip() or latest_tag
            release_url = data.get("html_url", GITHUB_RELEASES_URL)
            release_notes = data.get("body", "") or "No release notes provided."
            has_update = bool(latest_tag) and is_newer_version(latest_tag, CURRENT_VERSION)
            self.signals.finished.emit(True, latest_tag, latest_name, release_url, release_notes if has_update else "")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                self.signals.finished.emit(False, "", "", GITHUB_RELEASES_URL, "No published GitHub release was found yet. Create a release such as v1.0.0, then try again.")
            else:
                self.signals.finished.emit(False, "", "", GITHUB_RELEASES_URL, f"GitHub returned HTTP {exc.code}.")
        except Exception as exc:
            self.signals.finished.emit(False, "", "", GITHUB_RELEASES_URL, str(exc))


class DropFrame(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if Path(url.toLocalFile()).is_dir():
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                self.parent_window.set_scan_folder(path)
                event.acceptProposedAction()
                return


class FolderSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_folder = None
        self.setWindowTitle("Set Source Folder")
        self.setModal(True)
        self.resize(560, 260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)
        title = QLabel("Choose the folder you want to scan")
        title.setObjectName("DialogTitle")
        msg = QLabel("STANK Archive Pro needs a source folder first. This is where files waiting to be archived are located.")
        msg.setWordWrap(True)
        self.path_label = QLabel("No folder selected")
        self.path_label.setObjectName("PathPill")
        choose = QPushButton("Choose Folder")
        choose.setObjectName("PrimaryButton")
        choose.clicked.connect(self.choose)
        layout.addWidget(title)
        layout.addWidget(msg)
        layout.addWidget(self.path_label)
        layout.addStretch(1)
        layout.addWidget(choose)

    def choose(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose folder to scan", str(Path.home()))
        if folder:
            self.selected_folder = Path(folder)
            self.accept()


def cropped_logo_pixmap(path: Path) -> QPixmap:
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return pixmap
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    width, height = image.width(), image.height()
    min_x, min_y, max_x, max_y = width, height, -1, -1
    for y in range(height):
        for x in range(width):
            if QColor(image.pixel(x, y)).alpha() > 10:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    if max_x >= min_x and max_y >= min_y:
        pad = 2
        min_x = max(0, min_x - pad)
        min_y = max(0, min_y - pad)
        max_x = min(width - 1, max_x + pad)
        max_y = min(height - 1, max_y + pad)
        return QPixmap.fromImage(image.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1))
    return pixmap


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("TonyApps", "StankArchivePro")
        # Start with no source selected. Users must choose a source folder each session,
        # so the app never silently scans or prompts before the main window is visible.
        self.scan_folder: Path | None = None
        self.archive_folder: Path | None = None
        self.archive_folder_custom = False
        self.dark_mode = self.settings.value("dark_mode", "false") == "true"
        self.history_log = Path(self.settings.value("history_log", str(Path.home() / "StankArchivePro_history.log")))
        self.last_actions: list[ArchiveAction] = []
        self.all_files: list[Path] = []
        self.scan_token = 0
        self.thread_pool = QThreadPool.globalInstance()
        # Resize performance: avoid doing expensive repaint/layout work for every pixel while dragging.
        self._resizing = False
        self._resize_finish_timer = QTimer(self)
        self._resize_finish_timer.setSingleShot(True)
        self._resize_finish_timer.timeout.connect(self._finish_resize)
        self._cached_header_logo = None
        self._cached_about_logo = None
        self._about_dialog = None
        self.update_check_in_progress = False

        self.watcher = QFileSystemWatcher(self)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.refresh_files)
        self.watcher.directoryChanged.connect(lambda *_: self.refresh_timer.start(350))

        self.model = FileTableModel(self)
        self.proxy = FileFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        self.setWindowTitle("STANK Archive Pro")
        icon_path = resource_path("assets/app_icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1180, 700)
        self.setMinimumSize(980, 620)
        self.build_ui()
        self.build_actions()
        self.apply_theme()
        QTimer.singleShot(0, self.preload_about_dialog)
        self.show_no_source_selected()

    def build_ui(self):
        root = DropFrame(self)
        root.setObjectName("Root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        hero = QFrame()
        hero.setObjectName("HeroCard")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(16, 6, 16, 6)
        hero_layout.setSpacing(14)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("HeaderLogo")
        self.logo_label.setMinimumSize(720, 140)
        self.logo_label.setMaximumHeight(150)
        self.load_header_logo()

        self.about_button = QPushButton("About")
        self.about_button.setObjectName("HeaderButton")
        self.about_button.clicked.connect(self.show_about_dialog)
        self.dark_button = QPushButton("Light Mode" if self.dark_mode else "Dark Mode")
        self.dark_button.setObjectName("HeaderButton")
        self.dark_button.setCheckable(True)
        self.dark_button.setChecked(self.dark_mode)
        self.dark_button.clicked.connect(self.toggle_dark_mode)

        hero_layout.addWidget(self.logo_label, 1, Qt.AlignLeft | Qt.AlignVCenter)
        hero_layout.addWidget(self.dark_button)
        hero_layout.addWidget(self.about_button)
        root_layout.addWidget(hero)

        self.choose_button = QPushButton("Choose Folder")
        self.choose_button.clicked.connect(self.choose_folder)
        self.archive_folder_button = QPushButton("Change Archive Folder")
        self.archive_folder_button.clicked.connect(self.choose_archive_folder)
        self.open_archive_button = QPushButton("Open Archive Folder")
        self.open_archive_button.clicked.connect(self.open_archive_folder)
        for folder_button in (self.choose_button, self.archive_folder_button, self.open_archive_button):
            folder_button.setMinimumWidth(170)
            folder_button.setMinimumHeight(34)

        folder_cards = QHBoxLayout()
        folder_cards.setSpacing(14)
        self.source_card = QFrame()
        self.source_card.setObjectName("SourceFolderCard")
        source_layout = QVBoxLayout(self.source_card)
        source_layout.setContentsMargins(16, 10, 16, 10)
        source_layout.setSpacing(8)
        source_title = QLabel("📂 SOURCE FOLDER")
        source_title.setObjectName("SourceFolderTitle")
        self.source_path_label = QLabel()
        self.source_path_label.setObjectName("FolderPathText")
        self.source_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.source_path_label.setWordWrap(True)
        source_layout.addWidget(source_title)
        source_layout.addWidget(self.source_path_label, 1)
        source_layout.addWidget(self.choose_button, 0, Qt.AlignLeft)

        self.archive_card = QFrame()
        self.archive_card.setObjectName("ArchiveFolderCard")
        archive_layout = QVBoxLayout(self.archive_card)
        archive_layout.setContentsMargins(16, 10, 16, 10)
        archive_layout.setSpacing(8)
        archive_title = QLabel("🗄 ARCHIVE FOLDER")
        archive_title.setObjectName("ArchiveFolderTitle")
        self.archive_path_label = QLabel()
        self.archive_path_label.setObjectName("FolderPathText")
        self.archive_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.archive_path_label.setWordWrap(True)
        archive_buttons = QHBoxLayout()
        archive_buttons.setContentsMargins(0, 0, 0, 0)
        archive_buttons.setSpacing(10)
        archive_buttons.addWidget(self.archive_folder_button, 0, Qt.AlignLeft)
        archive_buttons.addWidget(self.open_archive_button, 0, Qt.AlignLeft)
        archive_buttons.addStretch(1)
        archive_layout.addWidget(archive_title)
        archive_layout.addWidget(self.archive_path_label, 1)
        archive_layout.addLayout(archive_buttons)
        folder_cards.addWidget(self.source_card, 1)
        folder_cards.addWidget(self.archive_card, 1)
        root_layout.addLayout(folder_cards)

        controls_card = QFrame()
        controls_card.setObjectName("ControlCard")
        controls = QHBoxLayout(controls_card)
        controls.setContentsMargins(14, 12, 14, 12)
        controls.setSpacing(10)
        self.select_all_button = QPushButton("✓ Select All Visible")
        self.select_all_button.setObjectName("SelectButton")
        self.select_all_button.clicked.connect(self.select_all_visible)
        self.uncheck_all_button = QPushButton("☐ Uncheck All")
        self.uncheck_all_button.setObjectName("SecondaryButton")
        self.uncheck_all_button.clicked.connect(self.clear_all_checks)
        self.archive_button = QPushButton("Archive Selected")
        self.archive_button.setObjectName("PrimaryButton")
        self.archive_button.clicked.connect(self.archive_selected)
        self.undo_button = QPushButton("Undo Archive")
        self.undo_button.setObjectName("UndoButton")
        self.undo_button.clicked.connect(self.undo_archive)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search files by name...")
        self.search.textChanged.connect(self.on_search_changed)
        for b in [self.select_all_button, self.uncheck_all_button, self.archive_button, self.undo_button]:
            b.setMinimumHeight(38)
        controls.addWidget(self.select_all_button)
        controls.addWidget(self.uncheck_all_button)
        controls.addWidget(self.archive_button)
        controls.addWidget(self.undo_button)
        controls.addSpacing(12)
        controls.addWidget(self.search, 1)
        root_layout.addWidget(controls_card)

        self.success_banner = QLabel("")
        self.success_banner.setObjectName("SuccessBanner")
        self.success_banner.setWordWrap(True)
        self.success_banner.setVisible(False)
        root_layout.addWidget(self.success_banner)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("MainSplitter")
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self.confirm_open_from_index)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_file_context_menu)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self.update_filename_preview())
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        # Interactive/fixed-ish sections resize much faster than Stretch/ResizeToContents during window drags.
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Interactive)
        header.setSectionResizeMode(4, QHeaderView.Interactive)
        header.setStretchLastSection(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 54)
        self.table.setColumnWidth(1, 430)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 90)
        self.table.setWordWrap(False)
        self.table.setToolTip("Double-click a file to open it after confirmation. Right-click a file for quick actions including Archive.")
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.proxy.sort(2, Qt.DescendingOrder)
        self.model.dataChanged.connect(lambda *_: self.after_model_check_changed())
        self.model.modelReset.connect(lambda: self.after_model_check_changed())
        self.proxy.rowsInserted.connect(lambda *_: self.update_dashboard())
        self.proxy.rowsRemoved.connect(lambda *_: self.update_dashboard())
        self.proxy.modelReset.connect(lambda: self.update_dashboard())

        right = QFrame()
        right.setObjectName("PreviewCard")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(20, 20, 20, 20)
        right_layout.setSpacing(14)
        archive_preview_header = QHBoxLayout()
        name_label = QLabel("ARCHIVED FILE NAMES")
        name_label.setObjectName("ArchiveNameTitle")
        preview_note = QLabel("Preview")
        preview_note.setObjectName("PreviewNote")
        archive_preview_header.addWidget(name_label)
        archive_preview_header.addWidget(preview_note)
        archive_preview_header.addStretch(1)
        self.filename_preview = QTextEdit()
        self.filename_preview.setObjectName("ArchivePreviewCard")
        self.filename_preview.setReadOnly(True)
        self.filename_preview.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.filename_preview.setMinimumHeight(260)
        self.filename_preview.setLineWrapMode(QTextEdit.NoWrap)
        self.status_label = QLabel("Choose a folder to begin.")
        self.status_label.setObjectName("StatusText")
        self.status_label.setWordWrap(True)
        right_layout.addLayout(archive_preview_header)
        right_layout.addWidget(self.filename_preview, 1)
        right_layout.addWidget(self.status_label)
        splitter.addWidget(self.table)
        splitter.addWidget(right)
        splitter.setSizes([760, 420])
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

    def load_header_logo(self):
        logo_path = resource_path("assets/stank_archive_logo.png")
        if logo_path.exists():
            if self._cached_header_logo is None:
                self._cached_header_logo = cropped_logo_pixmap(logo_path)
            # Scale once to the fixed header target instead of recalculating during window resize.
            self.logo_label.setPixmap(self._cached_header_logo.scaled(720, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.logo_label.setText("STANK ARCHIVE PRO")
            self.logo_label.setObjectName("AppTitle")

    def build_actions(self):
        shortcuts = [
            ("Archive", QKeySequence(Qt.Key_Return), self.archive_selected),
            ("Undo", QKeySequence("Ctrl+Z"), self.undo_archive),
            ("Refresh", QKeySequence("F5"), self.refresh_files),
            ("Select All", QKeySequence("Ctrl+A"), self.select_all_visible),
            ("Clear Selection", QKeySequence("Ctrl+D"), self.clear_all_checks),
            ("Toggle Check", QKeySequence(Qt.Key_Space), self.toggle_current_check),
        ]
        for name, shortcut, callback in shortcuts:
            action = QAction(name, self)
            action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.addAction(action)

    def apply_theme(self):
        QApplication.instance().setFont(QFont("Segoe UI", 12))
        self.model.set_theme(self.dark_mode)
        if hasattr(self, "dark_button"):
            self.dark_button.blockSignals(True)
            self.dark_button.setChecked(self.dark_mode)
            self.dark_button.setText("Light Mode" if self.dark_mode else "Dark Mode")
            self.dark_button.blockSignals(False)
        if self.dark_mode:
            self._preview_text = "#eef6ff"
            self._preview_muted = "#aab8cc"
            self._preview_item_bg = "#172033"
            self.setStyleSheet("""
            QMainWindow, QDialog, #Root { background: #0f1724; color: #eef6ff; }
            #HeroCard, #ControlCard, #PreviewCard { background: #151f2e; border: 1px solid #2c3b52; border-radius: 18px; }
            #HeaderLogo { background: transparent; }
            #SourceFolderCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #142133, stop:1 #0f1b2d); border: 1px solid #235c9c; border-left: 8px solid #2f8cff; border-radius: 20px; }
            #ArchiveFolderCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #14251d, stop:1 #102018); border: 1px solid #2b8155; border-left: 8px solid #24c56a; border-radius: 20px; }
            #SourceFolderTitle { color:#54a8ff; font-size: 15px; font-weight: 950; letter-spacing: .7px; }
            #ArchiveFolderTitle { color:#42d37a; font-size: 15px; font-weight: 950; letter-spacing: .7px; }
            #FolderPathText { font-size: 13px; font-weight: 800; color: #f0f7ff; background: rgba(10,18,30,0.82); border: 1px solid #34475f; border-radius: 11px; padding: 8px 11px; }
            #ArchiveNameTitle { color: #f3f8ff; font-size: 18px; font-weight: 950; letter-spacing: .8px; }
            #PreviewNote { color: #aab8cc; font-size: 14px; font-weight: 650; padding-left: 8px; }
            #ArchivePreviewCard { background: #101928; border: 1px solid #2f6eaa; border-left: 6px solid #2f8cff; border-radius: 16px; padding: 12px; color: #eef6ff; font-size: 12px; }
            #StatusText { color: #c4d0df; font-weight: 700; padding-top: 6px; }
            #SuccessBanner { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0f2e1f, stop:1 #132b22); color: #b6ffd2; border: 1px solid #2da863; border-left: 7px solid #28d678; border-radius: 14px; padding: 10px 14px; font-family: "Segoe UI Semibold"; font-size: 14px; font-weight: 950; }
            QLineEdit { background: #0f1724; color: #eef6ff; border: 1px solid #34475f; border-radius: 13px; padding: 8px 12px; min-height: 32px; font-size: 13px; selection-background-color: #2f8cff; }
            QTableView { background: #111827; color: #eaf2ff; border: 1px solid #2c3b52; border-radius: 18px; gridline-color: #26364a; font-size: 13px; selection-background-color: #275fae; selection-color: #ffffff; }
            QTableView::item { padding: 7px; border-bottom: 1px solid #26364a; }
            QTableView::item:selected { background: #275fae; color: #ffffff; }
            QHeaderView::section { background: #18243a; color: #f3f8ff; padding: 8px; border: 0; border-bottom: 1px solid #34475f; font-weight: 950; font-size: 13px; }
            QScrollBar:vertical { background: #172033; width: 13px; border-radius: 6px; }
            QScrollBar::handle:vertical { background: #53677e; border-radius: 6px; min-height: 40px; }
            QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1c2a3e, stop:1 #121c2b); color: #dcecff; border: 1px solid #3e5f84; padding: 8px 14px; border-radius: 13px; font-family: "Segoe UI Semibold"; font-weight: 900; font-size: 13px; }
            QPushButton:hover { background: #233553; border: 1px solid #54a8ff; }
            QPushButton#SelectButton { background: #176fe0; color: white; border: 1px solid #0d57b8; font-weight: 950; }
            QPushButton#PrimaryButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #35c978, stop:1 #158d45); color: white; border: 1px solid #0e7438; font-family: "Segoe UI Semibold"; font-weight: 950; font-size: 14px; min-width: 160px; }
            QPushButton#SecondaryButton { background: #2d2516; color: #ffe2a0; border: 1px solid #b98322; font-family: "Segoe UI Semibold"; font-weight: 900; }
            QPushButton#UndoButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f04444, stop:1 #b91c1c); color: #ffffff; border: 1px solid #991b1b; font-family: "Segoe UI Semibold"; font-weight: 950; min-width: 130px; }
            QPushButton#UndoButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ef4444, stop:1 #991b1b); color: #ffffff; border: 1px solid #7f1d1d; }
            QPushButton#UndoButton:pressed { background: #7f1d1d; color: #ffffff; border: 1px solid #641313; }
            QPushButton#HeaderButton { background: #18243a; color: #dcecff; border: 1px solid #3e5f84; min-width: 86px; }
            QLabel#AboutTitle { font-size: 24px; font-weight: 950; color: #f3f8ff; }
            QLabel#AboutTagline { font-size: 14px; font-weight: 850; color: #63adff; }
            QLabel#AboutSectionTitle { font-size: 16px; font-weight: 950; color: #f3f8ff; margin-top: 8px; }
            QLabel#AboutBody { font-size: 13px; line-height: 1.35; color: #d3deec; }
            QSplitter::handle { background: #0f1724; width: 8px; }
            """)
        else:
            self._preview_text = "#0f263d"
            self._preview_muted = "#53677e"
            self._preview_item_bg = "#f2f8ff"
            self.setStyleSheet("""
            QMainWindow, QDialog, #Root { background: #f4f7fb; color: #0f1f33; }
            #HeroCard, #ControlCard, #PreviewCard { background: #ffffff; border: 1px solid #d9e5f1; border-radius: 18px; }
            #HeaderLogo { background: transparent; }
            #SourceFolderCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffffff, stop:1 #f2f8ff); border: 1px solid #aacbf0; border-left: 8px solid #176fe0; border-radius: 20px; }
            #ArchiveFolderCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #ffffff, stop:1 #f3fff6); border: 1px solid #a9dcbc; border-left: 8px solid #1ca75b; border-radius: 20px; }
            #SourceFolderTitle { color:#176fe0; font-size: 15px; font-weight: 950; letter-spacing: .7px; }
            #ArchiveFolderTitle { color:#168b4e; font-size: 15px; font-weight: 950; letter-spacing: .7px; }
            #FolderPathText { font-size: 13px; font-weight: 800; color: #0f1f33; background: rgba(255,255,255,0.86); border: 1px solid #d9e6f2; border-radius: 11px; padding: 8px 11px; }
            #ArchiveNameTitle { color: #0f1f33; font-size: 18px; font-weight: 950; letter-spacing: .8px; }
            #PreviewNote { color: #5d7085; font-size: 14px; font-weight: 650; padding-left: 8px; }
            #ArchivePreviewCard { background: #fbfdff; border: 1px solid #b9d7f5; border-left: 6px solid #176fe0; border-radius: 16px; padding: 12px; color: #0f263d; font-size: 12px; }
            #StatusText { color: #496177; font-weight: 700; padding-top: 6px; }
            #SuccessBanner { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #e9fff2, stop:1 #f6fffa); color: #116b38; border: 1px solid #91d9ae; border-left: 7px solid #20a65a; border-radius: 14px; padding: 10px 14px; font-family: "Segoe UI Semibold"; font-size: 14px; font-weight: 950; }
            QLineEdit { background: #ffffff; color: #0f1f33; border: 1px solid #cbd9e7; border-radius: 13px; padding: 8px 12px; min-height: 32px; font-size: 13px; selection-background-color: #bde3ff; }
            QTableView { background: #ffffff; color: #0f1f33; border: 1px solid #d7e4f0; border-radius: 18px; gridline-color: #e7eef6; font-size: 13px; selection-background-color: #95d7ff; selection-color: #07182a; }
            QTableView::item { padding: 7px; border-bottom: 1px solid #edf3f8; }
            QTableView::item:selected { background: #95d7ff; color: #07182a; }
            QHeaderView::section { background: #eef5fc; color: #0f1f33; padding: 8px; border: 0; border-bottom: 1px solid #cbd9e7; font-weight: 950; font-size: 13px; }
            QScrollBar:vertical { background: #edf3f8; width: 13px; border-radius: 6px; }
            QScrollBar::handle:vertical { background: #b7c8d8; border-radius: 6px; min-height: 40px; }
            QPushButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ffffff, stop:1 #edf5ff); color: #1259ad; border: 1px solid #9cc4ef; padding: 8px 14px; border-radius: 13px; font-family: "Segoe UI Semibold"; font-weight: 900; font-size: 13px; }
            QPushButton:hover { background: #eaf4ff; border: 1px solid #167fe1; }
            QPushButton#SelectButton { background: #176fe0; color: white; border: 1px solid #0d57b8; font-weight: 950; }
            QPushButton#PrimaryButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #35c978, stop:1 #158d45); color: white; border: 1px solid #0e7438; font-family: "Segoe UI Semibold"; font-weight: 950; font-size: 14px; min-width: 160px; }
            QPushButton#SecondaryButton { background: #fff8e8; color: #6f4300; border: 1px solid #f0b548; font-family: "Segoe UI Semibold"; font-weight: 900; }
            QPushButton#UndoButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f04444, stop:1 #d32f2f); color: #ffffff; border: 1px solid #b71c1c; font-family: "Segoe UI Semibold"; font-weight: 950; min-width: 130px; }
            QPushButton#UndoButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #ef5350, stop:1 #c62828); color: #ffffff; border: 1px solid #a81919; }
            QPushButton#UndoButton:pressed { background: #b71c1c; color: #ffffff; border: 1px solid #8b1111; }
            QPushButton#HeaderButton { background: #f2f7fd; color: #174e8f; border: 1px solid #b8d0ec; min-width: 86px; }
            QLabel#AboutTitle { font-size: 24px; font-weight: 950; color: #0f1f33; }
            QLabel#AboutTagline { font-size: 14px; font-weight: 850; color: #176fe0; }
            QLabel#AboutSectionTitle { font-size: 16px; font-weight: 950; color: #0f1f33; margin-top: 8px; }
            QLabel#AboutBody { font-size: 13px; line-height: 1.35; color: #203247; }
            QSplitter::handle { background: #f4f7fb; width: 8px; }
            """)
        self.update_filename_preview()

    def toggle_dark_mode(self, checked):
        self.dark_mode = bool(checked)
        self.settings.setValue("dark_mode", "true" if self.dark_mode else "false")
        self.apply_theme()

    def show_no_source_selected(self):
        self.scan_folder = None
        self.archive_folder = None
        self.all_files = []
        self.model.set_records([])
        watched = self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)
        self.source_path_label.setText("No source folder selected")
        self.archive_path_label.setText("Choose a source folder first")
        self.status_label.setText("Choose a source folder to begin.")
        self.archive_button.setText("Archive Selected")
        self.update_dashboard()
        self.update_filename_preview()

    def choose_folder(self):
        start_folder = str(self.scan_folder) if self.scan_folder else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose folder to scan", start_folder)
        if folder:
            self.set_scan_folder(Path(folder))

    def choose_archive_folder(self):
        start_folder = str(self.archive_folder) if self.archive_folder else (str(self.scan_folder / "Archived") if self.scan_folder else str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "Choose archive folder", start_folder)
        if folder:
            chosen = Path(folder)
            if not self.ensure_archive_folder_exists(chosen):
                return
            self.archive_folder = chosen
            self.archive_folder_custom = True
            self.settings.setValue("archive_folder_custom", "true")
            self.settings.setValue("archive_folder", str(self.archive_folder))
            self.archive_path_label.setText(str(self.archive_folder))
            self.update_filename_preview()

    def ensure_archive_folder_exists(self, folder: Path | None, ask: bool = True) -> bool:
        if folder is None:
            return False
        if folder.exists():
            return True
        if ask:
            answer = QMessageBox.question(
                self,
                "Create archive folder?",
                f"The archive folder does not exist yet:\n\n{folder}\n\nDo you want to create it now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer != QMessageBox.Yes:
                return False
        try:
            folder.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Could not create archive folder", str(exc))
            return False

    def set_scan_folder(self, folder: Path, initial=False):
        self.scan_folder = folder

        # Every selected source folder uses its own local Archived folder.
        # If it exists, use it automatically. If not, ask the user after the app is open.
        default_archive = folder / "Archived"
        self.archive_folder_custom = False
        self.settings.setValue("archive_folder_custom", "false")
        if default_archive.exists():
            self.archive_folder = default_archive
            self.settings.setValue("archive_folder", str(self.archive_folder))
            self.archive_path_label.setText(str(self.archive_folder))
        else:
            answer = QMessageBox.question(
                self,
                "Create Archived folder?",
                f"Create an Archived folder inside this source folder?\n\n{default_archive}\n\nArchived copies will be saved there.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes and self.ensure_archive_folder_exists(default_archive, ask=False):
                self.archive_folder = default_archive
                self.settings.setValue("archive_folder", str(self.archive_folder))
                self.archive_path_label.setText(str(self.archive_folder))
            else:
                self.archive_folder = None
                self.settings.remove("archive_folder")
                self.archive_path_label.setText("No archive folder selected")
                self.status_label.setText("Source selected. Choose an archive folder before archiving.")

        self.settings.setValue("scan_folder", str(folder))
        self.source_path_label.setText(str(folder))
        watched = self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)
        if folder.exists() and str(folder) not in self.watcher.directories():
            self.watcher.addPath(str(folder))
        self.refresh_files()

    def refresh_files(self):
        if self.scan_folder is None:
            self.all_files = []
            self.model.set_records([])
            self.status_label.setText("Choose a source folder to begin.")
            self.update_dashboard()
            self.update_filename_preview()
            return
        if not self.scan_folder.exists():
            self.all_files = []
            self.model.set_records([])
            self.status_label.setText("Folder does not exist.")
            self.update_dashboard()
            self.update_filename_preview()
            return
        self.scan_token += 1
        token = self.scan_token
        self.status_label.setText("Loading files...")
        task = FolderScanTask(token, self.scan_folder)
        task.signals.finished.connect(self.on_folder_scan_finished)
        self.thread_pool.start(task)

    def on_folder_scan_finished(self, token: int, records: list[FileRecord], error: str):
        if token != self.scan_token:
            return
        if error:
            self.all_files = []
            self.model.set_records([])
            self.status_label.setText(error)
        else:
            self.all_files = [r.path for r in records]
            self.model.set_records(records)
            self.proxy.set_query(self.search_box.text() if hasattr(self, "search_box") else "")
            if records:
                self.status_label.setText(f"Found {len(records)} file(s). Select files, then click Archive Selected.")
            else:
                self.status_label.setText("No files found. Choose a different folder or add files to begin.")
        self.update_dashboard()
        self.update_filename_preview()

    def on_search_changed(self, text: str):
        self.proxy.set_query(text)
        self.update_dashboard()
        self.update_filename_preview()

    def visible_paths(self) -> list[Path]:
        paths = []
        for proxy_row in range(self.proxy.rowCount()):
            source_index = self.proxy.mapToSource(self.proxy.index(proxy_row, 0))
            p = self.model.path_at(source_index.row())
            if p:
                paths.append(p)
        return paths

    def path_from_proxy_index(self, proxy_index) -> Path | None:
        if not proxy_index.isValid():
            return None
        source_index = self.proxy.mapToSource(proxy_index)
        return self.model.path_at(source_index.row())

    def selected_row_paths(self) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()
        selection_model = self.table.selectionModel()
        if not selection_model:
            return paths
        for proxy_index in selection_model.selectedRows():
            path = self.path_from_proxy_index(proxy_index)
            if path and str(path) not in seen:
                paths.append(path)
                seen.add(str(path))
        return paths

    def context_target_paths(self, proxy_index) -> list[Path]:
        clicked_path = self.path_from_proxy_index(proxy_index)
        selected_paths = self.selected_row_paths()
        if clicked_path and any(str(clicked_path) == str(p) for p in selected_paths):
            return selected_paths
        return [clicked_path] if clicked_path else []

    def selected_paths(self) -> list[Path]:
        return self.model.checked_existing_paths()

    def select_all_visible(self):
        # Instant bulk selection: update checked set once and repaint once.
        paths = self.visible_paths()
        if not paths:
            self.status_label.setText("No visible files to select.")
            return
        self.table.setUpdatesEnabled(False)
        self.model.set_checked_paths_bulk(paths, True)
        self.table.setUpdatesEnabled(True)
        self.table.viewport().update()
        self.status_label.setText(f"Selected {len(paths)} visible file(s).")
        self.after_model_check_changed()

    def clear_all_checks(self):
        self.table.setUpdatesEnabled(False)
        self.model.clear_checks()
        self.table.setUpdatesEnabled(True)
        self.table.viewport().update()
        self.status_label.setText("Unchecked all files.")
        self.after_model_check_changed()

    def toggle_check_from_index(self, proxy_index):
        if not proxy_index.isValid():
            return
        source_index = self.proxy.mapToSource(proxy_index)
        self.model.toggle_row(source_index.row())

    def toggle_current_check(self):
        idx = self.table.currentIndex()
        if idx.isValid():
            self.toggle_check_from_index(idx)

    def confirm_open_from_index(self, proxy_index):
        path = self.path_from_proxy_index(proxy_index)
        if path:
            self.confirm_open_file(path)

    def confirm_open_file(self, path: Path):
        if not path.exists():
            QMessageBox.warning(self, "File not found", f"This file no longer exists:\n\n{path}")
            self.refresh_files()
            return
        answer = QMessageBox.question(
            self,
            "Open File?",
            f"Open this file with its default Windows application?\n\n{path.name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.open_path(path)

    def show_file_context_menu(self, position):
        proxy_index = self.table.indexAt(position)
        if not proxy_index.isValid():
            return
        paths = self.context_target_paths(proxy_index)
        if not paths:
            return
        clicked_path = self.path_from_proxy_index(proxy_index)

        menu = QMenu(self)
        archive_text = "📦 Archive This File" if len(paths) == 1 else f"📦 Archive {len(paths)} Selected Files"
        archive_action = menu.addAction(archive_text)
        menu.addSeparator()
        open_action = menu.addAction("📂 Open File...")
        copy_action = menu.addAction("📋 Copy Filename")
        show_action = menu.addAction("📁 Show in Explorer")

        chosen = menu.exec(self.table.viewport().mapToGlobal(position))
        if chosen == archive_action:
            self.archive_paths(paths)
        elif chosen == open_action and clicked_path:
            self.confirm_open_file(clicked_path)
        elif chosen == copy_action and clicked_path:
            QApplication.clipboard().setText(clicked_path.name)
            self.status_label.setText(f"Copied filename: {clicked_path.name}")
        elif chosen == show_action and clicked_path:
            self.show_in_explorer(clicked_path)

    def show_in_explorer(self, path: Path):
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                self.open_path(path.parent)
        except Exception as exc:
            QMessageBox.critical(self, "Show in Explorer failed", str(exc))

    def show_file_properties(self, path: Path):
        try:
            stat = path.stat()
            created = datetime.fromtimestamp(stat.st_ctime).strftime("%m-%d-%Y %I:%M %p")
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d-%Y %I:%M %p")
            QMessageBox.information(
                self,
                "File Properties",
                f"Name: {path.name}\n"
                f"Type: {path.suffix.lower().replace('.', '') or 'file'}\n"
                f"Size: {FileTableModel.human_size(stat.st_size)}\n"
                f"Created: {created}\n"
                f"Modified: {modified}\n\n"
                f"Path:\n{path}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Properties failed", str(exc))

    def after_model_check_changed(self):
        count = len(self.selected_paths())
        self.archive_button.setText(f"Archive {count} File{'s' if count != 1 else ''}" if count else "Archive Selected")
        self.update_dashboard()
        self.update_filename_preview()

    def update_dashboard(self):
        visible = self.proxy.rowCount() if hasattr(self, "proxy") else 0
        selected = len(self.selected_paths()) if hasattr(self, "model") else 0
        self.setWindowTitle(f"STANK Archive Pro — {visible} files, {selected} selected")

    def update_filename_preview(self):
        if not hasattr(self, "filename_preview"):
            return
        # Do not rebuild a rich HTML document while the window is actively resizing.
        if getattr(self, "_resizing", False):
            return
        paths = self.selected_paths()
        if not paths:
            self.filename_preview.setPlainText(
                "📄 Select files to archive\n\n"
                "Checked files will appear here using the final archived filename format."
            )
            return
        # Plain text is much faster to relayout than many HTML blocks when resizing.
        max_preview = 250
        names = [self.archived_filename_for_preview(path) for path in paths[:max_preview]]
        heading = "1 file selected" if len(paths) == 1 else f"{len(paths)} files selected"
        lines = [f"📦 {heading}", "", "Final archived filenames:", ""]
        lines.extend(f"📄 {name}" for name in names)
        if len(paths) > max_preview:
            lines.append("")
            lines.append(f"+ {len(paths) - max_preview} more selected files")
        self.filename_preview.setPlainText("\n".join(lines))

    def archive_name(self, path: Path) -> str:
        stamp = datetime.now().strftime("%m-%d-%Y-%H꞉%M")
        return f"{path.stem} (Archived {stamp}){path.suffix}"

    def unique_destination(self, path: Path) -> Path:
        if self.archive_folder is None:
            raise RuntimeError("No archive folder selected.")
        base = self.archive_folder / self.archive_name(path)
        if not base.exists():
            return base
        stem = base.stem
        suffix = base.suffix
        counter = 2
        while True:
            candidate = self.archive_folder / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    def archived_filename_for_preview(self, path: Path) -> str:
        if self.archive_folder is None:
            return self.archive_name(path)
        return self.unique_destination(path).name

    def archive_selected(self):
        paths = self.selected_paths()
        if not paths:
            self.status_label.setText("Select one or more files first.")
            return
        self.archive_paths(paths)

    def archive_paths(self, paths: list[Path]):
        paths = [p for p in paths if p and p.exists()]
        if not paths:
            self.status_label.setText("No available files to archive.")
            return
        if self.archive_folder is None:
            self.status_label.setText("Choose an archive folder before archiving.")
            self.choose_archive_folder()
            if self.archive_folder is None:
                return
        try:
            if not self.ensure_archive_folder_exists(self.archive_folder):
                self.status_label.setText("Archive cancelled. No archive folder was created.")
                return
            actions = []
            total = len(paths)
            for index, path in enumerate(paths, start=1):
                dest = self.unique_destination(path)
                self.filename_preview.setPlainText(f"Archiving...\n\n📄 {dest.name}\n\n{index} / {total}")
                QApplication.processEvents()
                shutil.copy2(str(path), str(dest))
                actions.append(ArchiveAction(path, dest))
                self.write_history(path, dest)
            self.last_actions = actions
            self.show_success_banner(len(actions))
            self.refresh_files()
        except Exception as exc:
            QMessageBox.critical(self, "Archive failed", str(exc))

    def show_success_banner(self, count: int):
        if count <= 0:
            self.status_label.setText("No archived copies were created.")
            return
        word = "file" if count == 1 else "files"
        self.show_dashboard_message(f"✓ Created {count} archived {word}.", "Original files were left in place and renamed copies were saved to the archive folder.")

    def show_undo_banner(self, count: int):
        if count <= 0:
            self.status_label.setText("No archived copies were removed.")
            return
        word = "file" if count == 1 else "files"
        self.show_dashboard_message(f"↶ Undo complete. Removed {count} archived {word}.", "Original files were not changed.")

    def show_dashboard_message(self, headline: str, detail: str):
        self.status_label.setText(headline)
        self.success_banner.setText(f"{headline} {detail}")
        self.success_banner.setVisible(True)
        QTimer.singleShot(4500, lambda: self.success_banner.setVisible(False) if hasattr(self, "success_banner") else None)

    def undo_archive(self):
        if not self.last_actions:
            self.status_label.setText("Nothing to undo.")
            return
        restored = 0
        try:
            for action in reversed(self.last_actions):
                original, archived = action.original_path, action.archived_path
                if not archived.exists():
                    continue
                archived.unlink()
                restored += 1
            self.show_undo_banner(restored)
            self.last_actions = []
            self.refresh_files()
        except Exception as exc:
            QMessageBox.critical(self, "Undo failed", str(exc))

    def open_archive_folder(self):
        try:
            if self.archive_folder is None:
                self.status_label.setText("No archive folder selected.")
                return
            if not self.ensure_archive_folder_exists(self.archive_folder):
                return
            self.open_path(self.archive_folder)
        except Exception as exc:
            QMessageBox.critical(self, "Open archive folder failed", str(exc))

    def open_path(self, path: Path):
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def write_history(self, original: Path, archived: Path):
        try:
            self.history_log.parent.mkdir(parents=True, exist_ok=True)
            with self.history_log.open("a", encoding="utf-8") as f:
                f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {original} -> {archived}\n")
        except Exception:
            pass

    def preload_about_dialog(self):
        # Build the About dialog after startup so clicking About opens instantly.
        self.ensure_about_dialog()

    def ensure_about_dialog(self):
        if self._about_dialog is not None:
            return self._about_dialog
        self._about_dialog = self.build_about_dialog()
        return self._about_dialog

    def build_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About STANK Archive Pro")
        dialog.setModal(True)
        dialog.resize(760, 640)
        dialog.setObjectName("AboutDialog")
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(22, 22, 22, 18)
        outer.setSpacing(14)

        logo = QLabel()
        logo_path = resource_path("assets/stank_archive_logo.png")
        if logo_path.exists():
            if self._cached_about_logo is None:
                pixmap = cropped_logo_pixmap(logo_path)
                self._cached_about_logo = pixmap.scaled(700, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo.setPixmap(self._cached_about_logo)
        else:
            logo.setText("STANK ARCHIVE PRO")
            logo.setObjectName("AboutTitle")
        outer.addWidget(logo, 0, Qt.AlignLeft)

        title = QLabel("STANK Archive Pro")
        title.setObjectName("AboutTitle")
        tagline = QLabel("Archive Smarter. Stay Organized.")
        tagline.setObjectName("AboutTagline")
        outer.addWidget(title)
        outer.addWidget(tagline)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 8, 0)
        content_layout.setSpacing(10)
        for widget in [
            self.about_label(f"Version {CURRENT_VERSION}", "AboutBody"),
            self.about_label("Welcome", "AboutSectionTitle"),
            self.about_label("STANK Archive Pro was created to make document archiving fast, simple, and reliable. Whether you're organizing scanned paperwork, invoices, insurance documents, or other digital files, STANK helps keep your workspace clean by creating renamed archive copies while leaving the original files in place.<br><br>Version 1.0.0 creates renamed archive copies, keeps originals in place, and includes update checking through GitHub Releases.", "AboutBody"),
            self.about_label("What STANK Means", "AboutSectionTitle"),
            self.about_label("<b>S</b> — <b>Secure</b><br>Protect your documents with reliable organization and safe archiving.<br><br><b>T</b> — <b>Tracking</b><br>Keep files organized with consistent archive naming and structure.<br><br><b>A</b> — <b>Archiving</b><br>Quickly create timestamped archive copies in your chosen archive location.<br><br><b>N</b> — <b>Naming</b><br>Automatically rename every archived file using a standardized format.<br><br><b>K</b> — <b>Kit</b><br>Everything you need for fast, professional document archiving.", "AboutBody"),
            self.about_label("Features", "AboutSectionTitle"),
            self.about_label("• Archive one or many files at once<br>• Fast model-based file list<br>• Automatic archive renaming<br>• Consistent Windows-friendly filenames<br>• Batch processing<br>• Fast file searching and sorting<br>• Light and dark modes<br>• Optimized for everyday document management", "AboutBody"),
        ]:
            content_layout.addWidget(widget)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        button_row = QHBoxLayout()
        self.about_update_button = QPushButton("Check for Updates")
        self.about_update_button.setObjectName("SecondaryButton")
        self.about_update_button.clicked.connect(self.check_for_updates)
        close_button = QPushButton("Close")
        close_button.setObjectName("PrimaryButton")
        close_button.clicked.connect(dialog.accept)
        button_row.addWidget(self.about_update_button, 0, Qt.AlignLeft)
        button_row.addStretch(1)
        button_row.addWidget(close_button, 0, Qt.AlignRight)
        outer.addLayout(button_row)
        return dialog

    def show_about_dialog(self):
        dialog = self.ensure_about_dialog()
        dialog.setStyleSheet(self.about_dialog_stylesheet())
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        dialog.exec()

    def about_dialog_stylesheet(self) -> str:
        if self.dark_mode:
            return """
            QDialog#AboutDialog { background: #0f1724; color: #eef6ff; }
            QScrollArea { background: transparent; border: none; }
            QScrollArea QWidget { background: transparent; }
            QLabel#AboutTitle { font-size: 24px; font-weight: 950; color: #f3f8ff; background: transparent; }
            QLabel#AboutTagline { font-size: 14px; font-weight: 850; color: #63adff; background: transparent; }
            QLabel#AboutSectionTitle { font-size: 16px; font-weight: 950; color: #f3f8ff; margin-top: 8px; background: transparent; }
            QLabel#AboutBody { font-size: 13px; line-height: 1.35; color: #d3deec; background: transparent; }
            QPushButton#PrimaryButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #35c978, stop:1 #158d45); color: white; border: 1px solid #0e7438; border-radius: 13px; padding: 8px 18px; font-family: "Segoe UI Semibold"; font-weight: 950; font-size: 14px; min-width: 120px; }
            QPushButton#PrimaryButton:hover { background: #24a85a; }
            QPushButton#SecondaryButton { background: #26364f; color: #eef6ff; border: 1px solid #405772; border-radius: 13px; padding: 8px 18px; font-family: "Segoe UI Semibold"; font-weight: 900; font-size: 14px; min-width: 150px; }
            QPushButton#SecondaryButton:hover { background: #314764; }
            QScrollBar:vertical { background: #172033; width: 13px; border-radius: 6px; }
            QScrollBar::handle:vertical { background: #53677e; border-radius: 6px; min-height: 40px; }
            """
        return """
            QDialog#AboutDialog { background: #f4f7fb; color: #0f1f33; }
            QScrollArea { background: transparent; border: none; }
            QScrollArea QWidget { background: transparent; }
            QLabel#AboutTitle { font-size: 24px; font-weight: 950; color: #0f1f33; background: transparent; }
            QLabel#AboutTagline { font-size: 14px; font-weight: 850; color: #176fe0; background: transparent; }
            QLabel#AboutSectionTitle { font-size: 16px; font-weight: 950; color: #0f1f33; margin-top: 8px; background: transparent; }
            QLabel#AboutBody { font-size: 13px; line-height: 1.35; color: #203247; background: transparent; }
            QPushButton#PrimaryButton { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #35c978, stop:1 #158d45); color: white; border: 1px solid #0e7438; border-radius: 13px; padding: 8px 18px; font-family: "Segoe UI Semibold"; font-weight: 950; font-size: 14px; min-width: 120px; }
            QPushButton#PrimaryButton:hover { background: #24a85a; }
            QPushButton#SecondaryButton { background: #eaf2fb; color: #0f1f33; border: 1px solid #bed0e4; border-radius: 13px; padding: 8px 18px; font-family: "Segoe UI Semibold"; font-weight: 900; font-size: 14px; min-width: 150px; }
            QPushButton#SecondaryButton:hover { background: #dceafe; }
            QScrollBar:vertical { background: #edf3f8; width: 13px; border-radius: 6px; }
            QScrollBar::handle:vertical { background: #b7c8d8; border-radius: 6px; min-height: 40px; }
            """

    def check_for_updates(self):
        if self.update_check_in_progress:
            return
        self.update_check_in_progress = True
        if hasattr(self, "about_update_button"):
            self.about_update_button.setEnabled(False)
            self.about_update_button.setText("Checking...")
        self.status_label.setText("Checking GitHub for updates...")
        task = UpdateCheckTask()
        task.signals.finished.connect(self.on_update_check_finished)
        self.thread_pool.start(task)

    def on_update_check_finished(self, ok: bool, latest_tag: str, latest_name: str, release_url: str, notes: str):
        self.update_check_in_progress = False
        if hasattr(self, "about_update_button"):
            self.about_update_button.setEnabled(True)
            self.about_update_button.setText("Check for Updates")
        if not ok:
            self.status_label.setText("Update check could not be completed.")
            QMessageBox.warning(
                self,
                "Update Check Failed",
                f"STANK Archive Pro could not check for updates.\n\n{notes}",
            )
            return
        latest_display = latest_tag or latest_name or "Unknown"
        if latest_tag and is_newer_version(latest_tag, CURRENT_VERSION):
            self.status_label.setText(f"Update available: {latest_display}")
            preview_notes = notes.strip()
            if len(preview_notes) > 900:
                preview_notes = preview_notes[:900].rstrip() + "..."
            message = (
                f"A newer version of STANK Archive Pro is available.\n\n"
                f"Current version: v{CURRENT_VERSION}\n"
                f"Latest version: {latest_display}\n\n"
                f"Release notes:\n{preview_notes}\n\n"
                f"Open the GitHub release page to download it?"
            )
            answer = QMessageBox.question(
                self,
                "Update Available",
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(release_url or GITHUB_RELEASES_URL))
        else:
            self.status_label.setText("STANK Archive Pro is up to date.")
            QMessageBox.information(
                self,
                "No Updates Found",
                f"You are running the latest version.\n\nCurrent version: v{CURRENT_VERSION}\nLatest GitHub release: {latest_display}",
            )

    def about_label(self, text: str, object_name: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName(object_name)
        return label

    def resizeEvent(self, event):
        # Keep resizing smooth: pause expensive repaints while the user is dragging the window.
        self._resizing = True
        if hasattr(self, "table"):
            self.table.setUpdatesEnabled(False)
        if hasattr(self, "filename_preview"):
            self.filename_preview.setUpdatesEnabled(False)
        self._resize_finish_timer.start(180)
        super().resizeEvent(event)

    def _finish_resize(self):
        self._resizing = False
        if hasattr(self, "table"):
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()
        if hasattr(self, "filename_preview"):
            self.filename_preview.setUpdatesEnabled(True)
            self.update_filename_preview()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    icon_path = resource_path("assets/app_icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
