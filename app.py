# -*- coding: utf-8 -*-
import multiprocessing
import os
import sys
import shutil
import tempfile
import struct
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QApplication, QMainWindow, QScrollArea, QSizePolicy, QWidget, QHBoxLayout, 
                             QVBoxLayout, QLabel, QTreeWidget, QTreeWidgetItem, 
                             QPushButton, QComboBox, QCheckBox, QTextEdit, 
                             QFrame, QMessageBox, QHeaderView, QLineEdit, QFileDialog, QToolButton, QGroupBox, QGridLayout)
from PySide6.QtGui import QColor, QPalette, QPixmap, QImage, QIcon
from PIL import Image

from tex_core import tex_core, str_codec


def _convert_image_worker(args):
    img_p, out_img_path, chosen_ext, chosen_bpp = args
    try:
        with Image.open(img_p) as img:
            if chosen_ext in ('jpg', 'jpeg') and img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            elif chosen_bpp == '32' and img.mode != 'RGBA':
                img = img.convert('RGBA')
            elif chosen_bpp == '24' and img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(out_img_path)
        return True, None
    except Exception as e:
        return False, f"Error converting {img_p}: {e}"


class WorkerThread(QThread):
    log_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, task_fn):
        super().__init__()
        self.task_fn = task_fn

    def run(self):
        try:
            self.task_fn(self.log_signal.emit)
            self.finished_signal.emit(True, "Operation completed successfully.")
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class ModernMMPApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.mmp_tool = tex_core()
        self.added_paths = []
        self.worker = None

        self.setWindowTitle("BladeTex")
        self.resize(1200, 820)
        self.setMinimumSize(980, 700)

        icon_path = os.path.join(
            sys._MEIPASS if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__)),
            "app.ico"
        )
        self.setWindowIcon(QIcon(icon_path))
        
        self.apply_dark_theme()

        # Central Main Widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(14)

        # =========================================================================
        # LEFT PANEL: File Explorer & Drag/Drop
        # =========================================================================
        left_panel = QVBoxLayout()
        left_panel.setSpacing(8)

        # Drag and Drop Zone
        self.drop_zone = QLabel("📥 Drag & Drop Files or Folders Here")
        self.drop_zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone.setFixedHeight(55)
        self.drop_zone.setStyleSheet("""
            QLabel {
                border: 2px dashed #4c566a;
                border-radius: 8px;
                background-color: #1e222a;
                color: #d8dee9;
                font-size: 13px;
                font-weight: 600;
            }
            QLabel:hover {
                border-color: #88c0d0;
                background-color: #2e3440;
                color: #88c0d0;
            }
        """)
        self.setAcceptDrops(True)
        left_panel.addWidget(self.drop_zone)

        # File Tree Widget
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["Structure / Selection", "Format / Type", "Dimensions / Size"])
        self.file_tree.setColumnWidth(0, 300)
        self.file_tree.setColumnWidth(1, 150)
        self.file_tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.file_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        self.file_tree.setStyleSheet("""
            QTreeWidget {
                background-color: #1e222a;
                border: 1px solid #3b4252;
                border-radius: 8px;
                padding: 4px;
                color: #d8dee9;
                font-size: 12px;
            }
            QTreeWidget::item { 
                padding: 3px; 
                border-radius: 4px;
            }
            QTreeWidget::item:hover { 
                background-color: #2e3440; 
            }
            QTreeWidget::item:selected { 
                background-color: #434c5e; 
                color: #88c0d0; 
            }
            QHeaderView::section {
                background-color: #2e3440;
                color: #88c0d0;
                padding: 5px;
                border: none;
                border-bottom: 2px solid #3b4252;
                font-weight: bold;
            }
        """)
        self.file_tree.itemChanged.connect(self.on_tree_item_changed)
        self.file_tree.itemSelectionChanged.connect(self.update_preview)
        left_panel.addWidget(self.file_tree)

        # Selection Buttons
        selection_layout = QHBoxLayout()
        selection_layout.setSpacing(8)

        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self.set_global_check_state(Qt.CheckState.Checked))
        selection_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(lambda: self.set_global_check_state(Qt.CheckState.Unchecked))
        selection_layout.addWidget(deselect_all_btn)

        clear_btn = QPushButton("Clear Explorer")
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #bf616a; color: white; font-weight: bold; border: none; border-radius: 6px; padding: 6px 12px;
            }
            QPushButton:hover { background-color: #d08770; }
        """)
        clear_btn.clicked.connect(self.clear_file_list)
        selection_layout.addWidget(clear_btn)

        left_panel.addLayout(selection_layout)
        main_layout.addLayout(left_panel, stretch=5)

        # =========================================================================
        # RIGHT PANEL: Preview, Configurations, Actions & Console
        # =========================================================================
        self.right_container = QWidget()
        self.right_panel = QVBoxLayout(self.right_container)
        self.right_panel.setContentsMargins(4, 4, 8, 4)
        self.right_panel.setSpacing(10)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setWidget(self.right_container)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        main_layout.addWidget(scroll_area, stretch=4)

        # -------------------------------------------------------------------------
        # 1. TEXTURE PREVIEW BOX (SQUARE & CENTERED)
        # -------------------------------------------------------------------------
        preview_box = QGroupBox("Texture Preview")
        preview_box.setStyleSheet(self.get_groupbox_style())
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(10, 12, 10, 10)
        preview_layout.setSpacing(6)

        self.preview_container = QFrame()
        self.preview_container.setFixedSize(230, 230)
        self.preview_container.setStyleSheet("""
            QFrame {
                background-color: #181b20;
                border: 1px solid #3b4252;
                border-radius: 6px;
            }
        """)
        preview_container_layout = QVBoxLayout(self.preview_container)
        preview_container_layout.setContentsMargins(4, 4, 4, 4)

        self.preview_label = QLabel("No texture selected")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setStyleSheet("color: #7b889b; font-size: 11px; border: none;")
        preview_container_layout.addWidget(self.preview_label)

        self.preview_info_label = QLabel("Dimensions: -- | Format: --")
        self.preview_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_info_label.setStyleSheet("color: #88c0d0; font-size: 11px; font-weight: 500; border: none;")

        preview_layout.addWidget(self.preview_container, 0, Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.preview_info_label)
        self.right_panel.addWidget(preview_box)

        # -------------------------------------------------------------------------
        # 2. GLOBAL CONFIGURATIONS BOX
        # -------------------------------------------------------------------------
        config_box = QGroupBox("Global Configurations")
        config_box.setStyleSheet(self.get_groupbox_style())
        config_layout = QVBoxLayout(config_box)
        config_layout.setContentsMargins(10, 12, 10, 10)
        config_layout.setSpacing(8)

        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(8)
        grid_layout.setVerticalSpacing(6)

        bpp_label = QLabel("Target BPP:")
        bpp_label.setStyleSheet("color: #d8dee9; font-weight: 500;")
        self.bpp_combo = QComboBox()
        self.bpp_combo.addItems(["32", "24", "8", "Alpha"])
        self.bpp_combo.setStyleSheet(self.get_combo_style())
        grid_layout.addWidget(bpp_label, 0, 0)
        grid_layout.addWidget(self.bpp_combo, 0, 1)

        format_label = QLabel("Image Format:")
        format_label.setStyleSheet("color: #d8dee9; font-weight: 500;")
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "JPG", "BMP", "WEBP"])
        self.format_combo.setStyleSheet(self.get_combo_style())
        grid_layout.addWidget(format_label, 0, 2)
        grid_layout.addWidget(self.format_combo, 0, 3)

        config_layout.addLayout(grid_layout)

        self.overwrite_check = QCheckBox("Overwrite Existing Files")
        self.overwrite_check.setStyleSheet("QCheckBox { color: #d8dee9; font-weight: 500; }")
        config_layout.addWidget(self.overwrite_check)

        path_label = QLabel("Output Destination:")
        path_label.setStyleSheet("color: #88c0d0; font-weight: 600; font-size: 11px;")
        config_layout.addWidget(path_label)

        input_row = QHBoxLayout()
        input_row.setSpacing(6)
        self.custom_path_input = QLineEdit("Define custom path or leave default")
        self.custom_path_input.setStyleSheet("""
            QLineEdit {
                background-color: #1e222a; border: 1px solid #3b4252;
                border-radius: 4px; padding: 5px; color: #d8dee9; font-size: 11px;
            }
            QLineEdit:focus { border: 1px solid #88c0d0; }
        """)
        self.browse_button = QToolButton()
        self.browse_button.setText("Browse")
        self.browse_button.setStyleSheet("""
            QToolButton {
                background-color: #4c566a; color: white; border-radius: 4px; padding: 5px 10px; font-weight: 500;
            }
            QToolButton:hover { background-color: #5e81ac; }
        """)
        self.browse_button.clicked.connect(self.browse_custom_path)

        input_row.addWidget(self.custom_path_input)
        input_row.addWidget(self.browse_button)
        config_layout.addLayout(input_row)

        self.right_panel.addWidget(config_box)

        # -------------------------------------------------------------------------
        # 3. TOOL ACTIONS BOX (2-COLUMN GRID)
        # -------------------------------------------------------------------------
        actions_box = QGroupBox("Tool Actions")
        actions_box.setStyleSheet(self.get_groupbox_style())
        actions_layout = QGridLayout(actions_box)
        actions_layout.setContentsMargins(10, 12, 10, 10)
        actions_layout.setHorizontalSpacing(8)
        actions_layout.setVerticalSpacing(6)

        buttons = [
            ("Unpacking (MMP -> Images)",   self.run_unpacking,      "#5e81ac"),
            ("Packing (Images -> MMP)",     self.run_packing,        "#5e81ac"),
            ("Convert MMP Bitrate (BPP)",   self.run_tobpp,          "#4c566a"),
            ("Generate .DAT Archive",       self.run_todat,          "#4c566a"),
            ("Convert Image Format",        self.run_toimg,          "#4c566a"),
            ("Standard Unify Folders",      self.run_stdunify,       "#434c5e"),
            ("Swap RGB <=> BGR Color",      self.run_swapbgr,        "#434c5e"),
            ("Batch Texture Removal",       self.run_remove_checked, "#a3be8c"),
        ]

        self.action_buttons = []
        for idx, (text, slot, color) in enumerate(buttons):
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {color}; color: #ffffff; border: none;
                    border-radius: 5px; padding: 7px 8px; text-align: center; font-weight: 500; font-size: 11px;
                }}
                QPushButton:hover {{ background-color: #81a1c1; color: #2e3440; }}
                QPushButton:disabled {{ background-color: #3b4252; color: #616e88; }}
            """)
            btn.clicked.connect(slot)
            row = idx // 2
            col = idx % 2
            actions_layout.addWidget(btn, row, col)
            self.action_buttons.append(btn)

        self.right_panel.addWidget(actions_box)

        # -------------------------------------------------------------------------
        # 4. CONSOLE OUTPUT FEEDBACK
        # -------------------------------------------------------------------------
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setFixedHeight(100)
        self.console_output.setPlaceholderText("Console feedback logs will print here...")
        self.console_output.setStyleSheet("""
            QTextEdit {
                background-color: #181b20; border: 1px solid #3b4252;
                border-radius: 6px; color: #a3be8c; padding: 5px;
                font-family: 'Consolas', 'Courier New', monospace; font-size: 11px;
            }
        """)
        self.right_panel.addWidget(self.console_output)

        self._is_updating_checks = False

    # =========================================================================
    # STYLESHEET HELPER METHODS
    # =========================================================================
    def get_groupbox_style(self):
        return """
            QGroupBox {
                background-color: #232830;
                border: 1px solid #3b4252;
                border-radius: 8px;
                margin-top: 8px;
                font-weight: bold;
                font-size: 12px;
                color: #88c0d0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                left: 10px;
            }
        """

    def get_combo_style(self):
        return """
            QComboBox {
                background-color: #1e222a; border: 1px solid #3b4252;
                border-radius: 4px; padding: 3px 6px; color: #ffffff; font-weight: bold; font-size: 11px;
            }
            QComboBox QAbstractItemView { 
                background-color: #2e3440; selection-background-color: #434c5e; color: #ffffff;
            }
        """

    # =========================================================================
    # PREVIEW & SELECTION UPDATE LOGIC
    # =========================================================================
    def update_preview(self):
        selected_items = self.file_tree.selectedItems()
        if not selected_items:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("No texture selected")
            self.preview_info_label.setText("Dimensions: -- | Format: --")
            return
        
        item = selected_items[0]
        node_type = item.data(0, Qt.ItemDataRole.UserRole)

        if node_type == "texture_node":
            mmp_path = item.data(1, Qt.ItemDataRole.UserRole)
            tex_name = item.data(2, Qt.ItemDataRole.UserRole)
            stream = self.mmp_tool.get_texture_as_stream(mmp_path, tex_name)
            if stream:
                try:
                    img = Image.open(stream).convert('RGBA')
                    qimg = QImage(img.tobytes(), img.width, img.height, QImage.Format.Format_RGBA8888)
                    pixmap = QPixmap.fromImage(qimg)
                    scaled_pixmap = pixmap.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.preview_label.setPixmap(scaled_pixmap)
                    self.preview_info_label.setText(f"{tex_name} ({img.width}×{img.height} px)")
                except Exception:
                    self.preview_label.setText("Preview Render Error")
            else:
                self.preview_label.setText("Unable to parse texture stream")

        elif node_type == "file_node":
            file_path = item.data(1, Qt.ItemDataRole.UserRole) or item.toolTip(0)
            if file_path and file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                try:
                    img = Image.open(file_path).convert('RGBA')
                    qimg = QImage(img.tobytes(), img.width, img.height, QImage.Format.Format_RGBA8888)
                    pixmap = QPixmap.fromImage(qimg)
                    scaled_pixmap = pixmap.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    self.preview_label.setPixmap(scaled_pixmap)
                    self.preview_info_label.setText(f"{os.path.basename(file_path)} ({img.width}×{img.height} px)")
                except Exception:
                    self.preview_label.setText("Image Load Error")
            else:
                self.preview_label.setText("No preview available for non-image file")
                self.preview_info_label.setText("Dimensions: -- | Format: File")
        else:
            self.preview_label.setText("Select an individual image or texture slice")
            self.preview_info_label.setText("Dimensions: -- | Format: --")

    # =========================================================================
    # CORE PATH & FILE SYSTEM HELPERS
    # =========================================================================
    def get_unique_path(self, target_path, is_folder=False, overwrite=False):
        if overwrite or not os.path.exists(target_path):
            return target_path

        if is_folder:
            counter = 1
            new_path = f"{target_path}_{counter}"
            while os.path.exists(new_path):
                counter += 1
                new_path = f"{target_path}_{counter}"
            return new_path
        else:
            base, ext = os.path.splitext(target_path)
            counter = 1
            new_path = f"{base}_{counter}{ext}"
            while os.path.exists(new_path):
                counter += 1
                new_path = f"{base}_{counter}{ext}"
            return new_path

    def get_output_base_dir(self, input_path):
        custom_path = self.custom_path_input.text().strip()
        default_text = "Define custom path or leave default"
        
        if custom_path and custom_path != default_text:
            if not os.path.exists(custom_path):
                try:
                    os.makedirs(custom_path, exist_ok=True)
                except Exception:
                    pass
            if os.path.exists(custom_path):
                return custom_path

        clean_path = os.path.abspath(input_path).rstrip('/\\')
        return os.path.dirname(clean_path)

    def execute_async_task(self, task_fn):
        for btn in self.action_buttons:
            btn.setEnabled(False)

        self.worker = WorkerThread(task_fn)
        self.worker.log_signal.connect(self.log_message)
        self.worker.finished_signal.connect(self.on_task_finished)
        self.worker.start()

    def on_task_finished(self, success, message):
        for btn in self.action_buttons:
            btn.setEnabled(True)
        self.log_message(f"Status: {message}")
        self.update_file_display()

    # =========================================================================
    # DRAG & DROP & EXPLORER TREE MANAGEMENT
    # =========================================================================
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_zone.setStyleSheet("""
                QLabel { border: 2px dashed #88c0d0; background-color: #2e3440; color: #88c0d0; font-size: 13px; font-weight: bold; }
            """)

    def dragLeaveEvent(self, event):
        self.drop_zone.setStyleSheet("""
            QLabel { border: 2px dashed #4c566a; background-color: #1e222a; color: #d8dee9; font-size: 13px; font-weight: bold; }
        """)

    def dropEvent(self, event):
        self.dragLeaveEvent(None)
        urls = event.mimeData().urls()
        for url in urls:
            local_path = url.toLocalFile()
            if local_path and local_path not in self.added_paths:
                self.added_paths.append(local_path)
        self.update_file_display()

    def on_tree_item_changed(self, item, column):
        if column != 0 or self._is_updating_checks:
            return
        self._is_updating_checks = True
        current_state = item.checkState(0)
        
        def set_children(parent_item, state):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                child.setCheckState(0, state)
                set_children(child, state)

        set_children(item, current_state)
        self._is_updating_checks = False

    def set_global_check_state(self, state):
        self.file_tree.setUpdatesEnabled(False)
        try:
            self._is_updating_checks = True
            root_count = self.file_tree.topLevelItemCount()
            for i in range(root_count):
                item = self.file_tree.topLevelItem(i)
                item.setCheckState(0, state)
                self.on_tree_item_changed(item, 0)
            self._is_updating_checks = False
        finally:
            self.file_tree.setUpdatesEnabled(True)

    def get_active_targets(self):
        mmp_tasks = {}
        folder_images = defaultdict(set)
        folders = set()
        standalone_images = set()

        checked_items = []
        root_count = self.file_tree.topLevelItemCount()

        def collect_checked(item):
            if item.checkState(0) == Qt.CheckState.Checked:
                checked_items.append(item)
            for i in range(item.childCount()):
                collect_checked(item.child(i))

        for i in range(root_count):
            collect_checked(self.file_tree.topLevelItem(i))

        target_items = checked_items if checked_items else self.file_tree.selectedItems()

        def get_container_parent(item):
            curr = item.parent()
            while curr is not None:
                c_type = curr.data(0, Qt.ItemDataRole.UserRole)
                if c_type in ("folder_node", "mmp_node"):
                    return curr
                curr = curr.parent()
            return None

        for item in target_items:
            node_type = item.data(0, Qt.ItemDataRole.UserRole)
            path = item.toolTip(0) or item.data(1, Qt.ItemDataRole.UserRole)

            if node_type == "texture_node":
                mmp_owner = item.data(1, Qt.ItemDataRole.UserRole)
                tex_name = item.data(2, Qt.ItemDataRole.UserRole)
                if mmp_owner not in mmp_tasks or mmp_tasks[mmp_owner] is not None:
                    mmp_tasks.setdefault(mmp_owner, []).append(tex_name)

            elif node_type == "mmp_node" or (path and path.lower().endswith('.mmp')):
                mmp_tasks[path] = None

            elif node_type == "folder_node" or (path and os.path.isdir(path)):
                folders.add(path)
                for root, _, files in os.walk(path):
                    for f in files:
                        full_f = os.path.join(root, f)
                        if f.lower().endswith('.mmp'):
                            if full_f not in mmp_tasks:
                                mmp_tasks[full_f] = None
                        elif f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                            folder_images[path].add(full_f)

            elif node_type == "file_node" or (path and os.path.isfile(path)):
                if path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                    parent_container = get_container_parent(item)
                    if parent_container is not None:
                        p_type = parent_container.data(0, Qt.ItemDataRole.UserRole)
                        p_path = parent_container.data(1, Qt.ItemDataRole.UserRole) or parent_container.toolTip(0)
                        if p_type == "folder_node":
                            folder_images[p_path].add(path)
                    else:
                        standalone_images.add(path)

        return mmp_tasks, {k: list(v) for k, v in folder_images.items()}, list(folders), list(standalone_images)

    def browse_custom_path(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.custom_path_input.setText(dir_path)

    def inspect_mmp_contents(self, mmp_path, parent_item):
        try:
            with open(mmp_path, 'rb') as f:
                header = f.read(4)
                if len(header) < 4: return
                nTextures = struct.unpack('<I', header)[0]
                
                for _ in range(nTextures):
                    meta = f.read(14)
                    if len(meta) < 14: break
                    two, checksum, size, name_len = struct.unpack('<HIII', meta)
                    raw_name = f.read(name_len)
                    img_name = str_codec(raw_name)
                    
                    type_meta = f.read(12)
                    if len(type_meta) < 12: break
                    im_type, width, height = struct.unpack('<III', type_meta)
                    f.seek(size - 12, 1)
                    
                    mode_name = self.mmp_tool.getmode.get(im_type, 'RAW')
                    ext_name = "BMP" if mode_name in ('RGBA', 'RGB', 'P', 'RAW') else ("JPG" if 'JPG' in mode_name else "PNG")

                    texture_child = QTreeWidgetItem(parent_item)
                    texture_child.setText(0, f"🖼️ {img_name}")
                    texture_child.setText(1, f"Type {im_type} ({mode_name}) | {ext_name}")
                    texture_child.setText(2, f"{width} × {height} px")
                    
                    texture_child.setFlags(texture_child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    texture_child.setCheckState(0, Qt.CheckState.Unchecked)
                    
                    texture_child.setData(0, Qt.ItemDataRole.UserRole, "texture_node")
                    texture_child.setData(1, Qt.ItemDataRole.UserRole, mmp_path)
                    texture_child.setData(2, Qt.ItemDataRole.UserRole, img_name)
        except Exception as e:
            self.log_message(f"Parser Warning: {str(e)}")

    def update_file_display(self):
        expanded_paths = set()
        root_count = self.file_tree.topLevelItemCount()
        for i in range(root_count):
            item = self.file_tree.topLevelItem(i)
            if item.isExpanded(): expanded_paths.add(item.toolTip(0))

        self.file_tree.setUpdatesEnabled(False)
        self.file_tree.blockSignals(True)
        try:
            self.file_tree.clear()
            
            for p in self.added_paths:
                base_name = os.path.basename(p) if os.path.basename(p) else p
                
                if os.path.isdir(p):
                    try: files_only = [f for f in os.listdir(p) if os.path.isfile(os.path.join(p, f))]
                    except Exception: files_only = []

                    folder_item = QTreeWidgetItem(self.file_tree)
                    folder_item.setText(0, f"📁 {base_name}")
                    folder_item.setText(1, "Folder Container")
                    folder_item.setText(2, f"{len(files_only)} files")
                    folder_item.setToolTip(0, p)
                    folder_item.setData(0, Qt.ItemDataRole.UserRole, "folder_node")
                    folder_item.setData(1, Qt.ItemDataRole.UserRole, p)
                    folder_item.setFlags(folder_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    folder_item.setCheckState(0, Qt.CheckState.Unchecked)
                    
                    if p in expanded_paths: folder_item.setExpanded(True)
                    
                    for inner_file in files_only:
                        child_item = QTreeWidgetItem(folder_item)
                        child_item.setText(0, f"📄 {inner_file}")
                        full_inner_path = os.path.join(p, inner_file)
                        child_item.setToolTip(0, full_inner_path)
                        child_item.setFlags(child_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                        child_item.setCheckState(0, Qt.CheckState.Unchecked)
                        
                        if inner_file.lower().endswith('.mmp'):
                            child_item.setText(1, "MMP Archive")
                            child_item.setData(0, Qt.ItemDataRole.UserRole, "mmp_node")
                            child_item.setData(1, Qt.ItemDataRole.UserRole, full_inner_path)
                            self.inspect_mmp_contents(full_inner_path, child_item)
                        else:
                            child_item.setText(1, "Asset File")
                            child_item.setData(0, Qt.ItemDataRole.UserRole, "file_node")
                            child_item.setData(1, Qt.ItemDataRole.UserRole, full_inner_path)
                            try: child_item.setText(2, f"{os.path.getsize(full_inner_path) / 1024:.1f} KB")
                            except Exception: pass
                else:
                    file_item = QTreeWidgetItem(self.file_tree)
                    file_item.setText(0, f"📄 {base_name}")
                    file_item.setToolTip(0, p)
                    file_item.setFlags(file_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    file_item.setCheckState(0, Qt.CheckState.Unchecked)
                    
                    if p.lower().endswith('.mmp'):
                        file_item.setText(1, "MMP Archive")
                        file_item.setData(0, Qt.ItemDataRole.UserRole, "mmp_node")
                        file_item.setData(1, Qt.ItemDataRole.UserRole, p)
                        self.inspect_mmp_contents(p, file_item)
                    else:
                        file_item.setText(1, "Asset File")
                        file_item.setData(0, Qt.ItemDataRole.UserRole, "file_node")
                        file_item.setData(1, Qt.ItemDataRole.UserRole, p)
                        try: file_item.setText(2, f"{os.path.getsize(p) / 1024:.1f} KB")
                        except Exception: pass
        finally:
            self.file_tree.blockSignals(False)
            self.file_tree.setUpdatesEnabled(True)

        self.log_message(f"Explorer synced: {len(self.added_paths)} top-level items loaded.")

    def clear_file_list(self):
        self.added_paths.clear()
        self.update_file_display()
        self.update_preview()

    def log_message(self, message):
        self.console_output.append(message)
        self.console_output.ensureCursorVisible()

    # =========================================================================
    # TOOL ACTION EXECUTORS
    # =========================================================================
    def run_unpacking(self):
        mmp_tasks, _, _, _ = self.get_active_targets()
        if not mmp_tasks:
            self.log_message("Abort: No MMP archive targets selected.")
            return

        is_overwrite = self.overwrite_check.isChecked()

        def worker_task(log):
            for mmp_path, selection in mmp_tasks.items():
                mmp_name = os.path.splitext(os.path.basename(mmp_path))[0]
                base_dest = self.get_output_base_dir(mmp_path)
                
                suffix = "extracted_textures" if selection is None else "selective_extracted_textures"
                target_dir = os.path.join(base_dest, f"{mmp_name}_{suffix}")
                final_out_dir = self.get_unique_path(target_dir, is_folder=True, overwrite=is_overwrite)

                log(f"Unpacking {mmp_name} -> {final_out_dir}...")
                if selection is None:
                    self.mmp_tool.unpack_all(source=mmp_path, output=final_out_dir)
                else:
                    self.mmp_tool.unpack_subset(source=mmp_path, selection=selection, output=final_out_dir)
                log(f"Success: Unpacked {mmp_name}")

        self.execute_async_task(worker_task)

    def run_packing(self):
        mmp_tasks, folder_images, folders, standalone_images = self.get_active_targets()
        if not mmp_tasks and not folder_images and not folders and not standalone_images:
            self.log_message("Abort: No packing targets selected.")
            return

        bpp = self.bpp_combo.currentText()
        is_overwrite = self.overwrite_check.isChecked()

        def worker_task(log):
            # 1. Selective MMP Packing
            for mmp_path, selection in mmp_tasks.items():
                if selection:
                    base_dir = self.get_output_base_dir(mmp_path)
                    base_name = os.path.splitext(os.path.basename(mmp_path))[0]
                    target_mmp = os.path.join(base_dir, f"{base_name}_subset.mmp")
                    final_mmp = self.get_unique_path(target_mmp, is_folder=False, overwrite=is_overwrite)
                    
                    with tempfile.TemporaryDirectory() as temp_dir:
                        self.mmp_tool.unpack_subset(mmp_path, selection, temp_dir)
                        self.mmp_tool.packing(paths=[temp_dir], bpp=bpp, overwrite=True, output_mmp=final_mmp)
                        log(f"Success: Selective pack -> {os.path.basename(final_mmp)}")

            # 2. Entire Folder Packing
            for folder_path in folders:
                base_dir = self.get_output_base_dir(folder_path)
                folder_name = os.path.basename(folder_path.rstrip('/\\'))
                target_mmp = os.path.join(base_dir, f"{folder_name}.mmp")
                final_mmp = self.get_unique_path(target_mmp, is_folder=False, overwrite=is_overwrite)
                
                log(f"Packing folder {folder_name} -> {final_mmp}...")
                self.mmp_tool.packing(paths=[folder_path], bpp=bpp, overwrite=is_overwrite, output_mmp=final_mmp)

            # 3. Specific Subsets of Images inside Folders
            for folder_path, imgs in folder_images.items():
                if folder_path not in folders and imgs:
                    base_dir = self.get_output_base_dir(folder_path)
                    folder_name = os.path.basename(folder_path.rstrip('/\\'))
                    target_mmp = os.path.join(base_dir, f"{folder_name}_subset.mmp")
                    final_mmp = self.get_unique_path(target_mmp, is_folder=False, overwrite=is_overwrite)

                    with tempfile.TemporaryDirectory() as temp_dir:
                        staging_folder = os.path.join(temp_dir, folder_name)
                        os.makedirs(staging_folder, exist_ok=True)
                        for img in imgs:
                            shutil.copy2(img, staging_folder)
                        self.mmp_tool.packing(paths=[staging_folder], bpp=bpp, overwrite=True, output_mmp=final_mmp)
                        log(f"Success: Packed folder subset -> {os.path.basename(final_mmp)}")

            # 4. Standalone Images
            if standalone_images:
                grouped_standalone = defaultdict(list)
                for img_p in standalone_images:
                    grouped_standalone[os.path.dirname(img_p)].append(img_p)

                for img_dir, img_list in grouped_standalone.items():
                    sample_path = img_list[0]
                    base_dir = self.get_output_base_dir(sample_path)
                    target_mmp = os.path.join(base_dir, "Packed_Images.mmp")
                    final_mmp = self.get_unique_path(target_mmp, is_folder=False, overwrite=is_overwrite)
                    
                    with tempfile.TemporaryDirectory() as temp_dir:
                        staging_folder = os.path.join(temp_dir, "Packed_Images")
                        os.makedirs(staging_folder, exist_ok=True)
                        for img in img_list:
                            shutil.copy2(img, staging_folder)
                        self.mmp_tool.packing(paths=[staging_folder], bpp=bpp, overwrite=True, output_mmp=final_mmp)
                        log(f"Success: Packed standalone images -> {os.path.basename(final_mmp)}")

        self.execute_async_task(worker_task)

    def run_tobpp(self):
        mmp_tasks, _, _, _ = self.get_active_targets()
        if not mmp_tasks:
            self.log_message("Abort: No MMP archive targets selected.")
            return

        chosen_bpp = self.bpp_combo.currentText()
        is_overwrite = self.overwrite_check.isChecked()

        def worker_task(log):
            for mmp_path, selection in mmp_tasks.items():
                base_dir = self.get_output_base_dir(mmp_path)
                base_name = os.path.splitext(os.path.basename(mmp_path))[0]
                target_mmp = os.path.join(base_dir, f"{base_name}_to{chosen_bpp}bpp.mmp")
                final_mmp = self.get_unique_path(target_mmp, is_folder=False, overwrite=is_overwrite)
                
                log(f"Converting bitrate for {base_name} -> {chosen_bpp} bpp ({final_mmp})...")
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_subset = os.path.join(temp_dir, f"{base_name}.mmp")
                    if selection:
                        self.mmp_tool.create_subset_mmp(mmp_path, selection, temp_subset)
                    else:
                        shutil.copy2(mmp_path, temp_subset)
                    self.mmp_tool.tobpp(paths=[temp_subset], bpp=chosen_bpp, output_mmp=final_mmp)

        self.execute_async_task(worker_task)

    def run_todat(self):
        mmp_tasks, _, _, _ = self.get_active_targets()
        if not mmp_tasks:
            self.log_message("Abort: No MMP archive targets selected.")
            return

        is_overwrite = self.overwrite_check.isChecked()

        def worker_task(log):
            for mmp_path in mmp_tasks.keys():
                base_dir = self.get_output_base_dir(mmp_path)
                base_name = os.path.splitext(os.path.basename(mmp_path))[0]
                target_dat = os.path.join(base_dir, f"{base_name}.dat")
                final_dat = self.get_unique_path(target_dat, is_folder=False, overwrite=is_overwrite)

                log(f"Building .DAT file: {os.path.basename(final_dat)}...")
                self.mmp_tool.todat(mmp_path=mmp_path, output_dat_path=final_dat)

        self.execute_async_task(worker_task)

    def run_toimg(self):
        mmp_tasks, folder_images, folders, standalone_images = self.get_active_targets()
        if not mmp_tasks and not folder_images and not folders and not standalone_images:
            self.log_message("Abort: No convertable targets selected.")
            return

        chosen_ext = self.format_combo.currentText().lower()
        chosen_bpp = self.bpp_combo.currentText()
        is_overwrite = self.overwrite_check.isChecked()

        def worker_task(log):
            # 1. Folder images
            for folder_path, img_set in folder_images.items():
                if img_set:
                    base_dir = self.get_output_base_dir(folder_path)
                    folder_name = os.path.basename(folder_path.rstrip('/\\')) or "textures"
                    
                    target_folder = os.path.join(base_dir, f"converted_{folder_name}")
                    final_out_dir = self.get_unique_path(target_folder, is_folder=True, overwrite=is_overwrite)
                    os.makedirs(final_out_dir, exist_ok=True)

                    log(f"Transcoding {len(img_set)} images in folder '{folder_name}'...")
                    tasks = []
                    for img_p in img_set:
                        fname = os.path.splitext(os.path.basename(img_p))[0]
                        out_img_path = os.path.join(final_out_dir, f"{fname}.{chosen_ext}")
                        tasks.append((img_p, out_img_path, chosen_ext, chosen_bpp))

                    if len(tasks) > 4:
                        max_workers = min(os.cpu_count() or 4, len(tasks))
                        with ProcessPoolExecutor(max_workers=max_workers) as executor:
                            results = list(executor.map(_convert_image_worker, tasks))
                    else:
                        results = [_convert_image_worker(t) for t in tasks]

                    for ok, err in results:
                        if not ok: log(err)

            # 2. Standalone images
            if standalone_images:
                grouped_standalone = defaultdict(list)
                for img_p in standalone_images:
                    grouped_standalone[os.path.dirname(img_p)].append(img_p)

                for img_dir, img_list in grouped_standalone.items():
                    sample_img = img_list[0]
                    base_dir = self.get_output_base_dir(sample_img)
                    target_folder = os.path.join(base_dir, "converted_images")
                    final_out_dir = self.get_unique_path(target_folder, is_folder=True, overwrite=is_overwrite)
                    os.makedirs(final_out_dir, exist_ok=True)

                    log(f"Transcoding {len(img_list)} standalone images...")
                    tasks = []
                    for img_p in img_list:
                        fname = os.path.splitext(os.path.basename(img_p))[0]
                        out_img_path = os.path.join(final_out_dir, f"{fname}.{chosen_ext}")
                        tasks.append((img_p, out_img_path, chosen_ext, chosen_bpp))

                    if len(tasks) > 4:
                        max_workers = min(os.cpu_count() or 4, len(tasks))
                        with ProcessPoolExecutor(max_workers=max_workers) as executor:
                            results = list(executor.map(_convert_image_worker, tasks))
                    else:
                        results = [_convert_image_worker(t) for t in tasks]

                    for ok, err in results:
                        if not ok: log(err)

            # 3. MMP Archives
            for mmp_path, selection in mmp_tasks.items():
                mmp_name = os.path.splitext(os.path.basename(mmp_path))[0]
                base_dir = self.get_output_base_dir(mmp_path)
                target_folder = os.path.join(base_dir, f"{mmp_name}_converted")
                final_out_dir = self.get_unique_path(target_folder, is_folder=True, overwrite=is_overwrite)
                os.makedirs(final_out_dir, exist_ok=True)
                
                log(f"Extracting textures from {mmp_name} -> {final_out_dir}...")
                with tempfile.TemporaryDirectory() as temp_dir:
                    if selection:
                        self.mmp_tool.unpack_subset(mmp_path, selection, temp_dir)
                    else:
                        self.mmp_tool.unpack_all(mmp_path, temp_dir)

                    bmps = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.lower().endswith('.bmp')]
                    tasks = []
                    for bmp_p in bmps:
                        fname = os.path.splitext(os.path.basename(bmp_p))[0]
                        dest_img = os.path.join(final_out_dir, f"{fname}.{chosen_ext}")
                        tasks.append((bmp_p, dest_img, chosen_ext, chosen_bpp))

                    if len(tasks) > 4:
                        max_workers = min(os.cpu_count() or 4, len(tasks))
                        with ProcessPoolExecutor(max_workers=max_workers) as executor:
                            results = list(executor.map(_convert_image_worker, tasks))
                    else:
                        results = [_convert_image_worker(t) for t in tasks]

                    for ok, err in results:
                        if not ok: log(err)

        self.execute_async_task(worker_task)

    def run_stdunify(self):
        _, _, folders, _ = self.get_active_targets()
        if not folders:
            self.log_message("Abort: Select folders to unify.")
            return

        is_overwrite = self.overwrite_check.isChecked()

        def worker_task(log):
            for folder in folders:
                if is_overwrite:
                    target_folder = folder
                else:
                    base_dir = self.get_output_base_dir(folder)
                    folder_name = os.path.basename(folder.rstrip('/\\'))
                    raw_target = os.path.join(base_dir, f"unified_{folder_name}")
                    target_folder = self.get_unique_path(raw_target, is_folder=True, overwrite=False)
                    shutil.copytree(folder, target_folder)

                log(f"Unifying folder structure: {target_folder}...")
                self.mmp_tool.StdUnify(path=target_folder, format_=['mmp', 'bmp', 'png'], keeplevel=False, cmd=False)

        self.execute_async_task(worker_task)

    def run_swapbgr(self):
        mmp_tasks, folder_images, folders, standalone_images = self.get_active_targets()
        if not mmp_tasks and not folder_images and not folders and not standalone_images:
            self.log_message("Abort: No targets selected for color swap.")
            return

        is_overwrite = self.overwrite_check.isChecked()

        def worker_task(log):
            # 1. Folder images
            for folder_path, img_set in folder_images.items():
                if img_set:
                    base_dir = self.get_output_base_dir(folder_path)
                    folder_basename = os.path.basename(folder_path.rstrip('/\\')) or "textures"
                    
                    if is_overwrite:
                        final_out_dir = folder_path
                    else:
                        target_folder = os.path.join(base_dir, f"swapped_{folder_basename}")
                        final_out_dir = self.get_unique_path(target_folder, is_folder=True, overwrite=False)
                        os.makedirs(final_out_dir, exist_ok=True)

                    log(f"Swapping RGB <=> BGR on folder '{folder_basename}' images...")
                    dest_paths = []
                    for img_p in img_set:
                        if not is_overwrite:
                            dest_file = os.path.join(final_out_dir, os.path.basename(img_p))
                            shutil.copy2(img_p, dest_file)
                            dest_paths.append(dest_file)
                        else:
                            dest_paths.append(img_p)

                    self.mmp_tool.swapBGR(paths=dest_paths, cmd=False)

            # 2. Standalone images
            if standalone_images:
                grouped_standalone = defaultdict(list)
                for img_p in standalone_images:
                    grouped_standalone[os.path.dirname(img_p)].append(img_p)

                for img_dir, img_list in grouped_standalone.items():
                    sample_img = img_list[0]
                    base_dir = self.get_output_base_dir(sample_img)

                    if is_overwrite:
                        dest_paths = img_list
                        log("Swapping RGB <=> BGR in-place on standalone images...")
                    else:
                        target_folder = os.path.join(base_dir, "swapped_images")
                        final_out_dir = self.get_unique_path(target_folder, is_folder=True, overwrite=False)
                        os.makedirs(final_out_dir, exist_ok=True)

                        log(f"Swapping RGB <=> BGR on standalone images -> {final_out_dir}...")
                        dest_paths = []
                        for img_p in img_list:
                            dest_file = os.path.join(final_out_dir, os.path.basename(img_p))
                            shutil.copy2(img_p, dest_file)
                            dest_paths.append(dest_file)

                    self.mmp_tool.swapBGR(paths=dest_paths, cmd=False)

            # 3. MMP Archives
            for mmp_path, selection in mmp_tasks.items():
                mmp_name = os.path.splitext(os.path.basename(mmp_path))[0]
                base_dir = self.get_output_base_dir(mmp_path)
                
                target_folder = os.path.join(base_dir, f"{mmp_name}_swapped")
                final_out_dir = self.get_unique_path(target_folder, is_folder=True, overwrite=is_overwrite)
                
                log(f"Swapping color channels for MMP: {mmp_name}...")
                with tempfile.TemporaryDirectory() as temp_dir:
                    if selection:
                        self.mmp_tool.unpack_subset(mmp_path, selection, temp_dir)
                    else:
                        self.mmp_tool.unpack_all(mmp_path, temp_dir)

                    extracted = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.lower().endswith('.bmp')]
                    self.mmp_tool.swapBGR(paths=extracted, cmd=False)
                    
                    os.makedirs(final_out_dir, exist_ok=True)
                    for f in extracted:
                        shutil.copy2(f, final_out_dir)

        self.execute_async_task(worker_task)

    def run_remove_checked(self):
        mmp_tasks, _, _, _ = self.get_active_targets()
        removal_tasks = {k: v for k, v in mmp_tasks.items() if v is not None and len(v) > 0}
        
        if not removal_tasks:
            QMessageBox.information(self, "Batch Texture Removal", "No specific textures checked inside MMP archives.")
            return

        confirm = QMessageBox.question(
            self, "Confirm Processing Action",
            f"Are you sure you want to delete {sum(len(v) for v in removal_tasks.values())} texture slices?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes: return

        bpp = self.bpp_combo.currentText()
        is_overwrite = self.overwrite_check.isChecked()

        def worker_task(log):
            for mmp_file, textures_to_remove in removal_tasks.items():
                base_dir = self.get_output_base_dir(mmp_file)
                base_name = os.path.splitext(os.path.basename(mmp_file))[0]
                
                if is_overwrite:
                    final_mmp = mmp_file
                else:
                    target_mmp = os.path.join(base_dir, f"{base_name}_modified.mmp")
                    final_mmp = self.get_unique_path(target_mmp, is_folder=False, overwrite=False)

                log(f"Purging {len(textures_to_remove)} textures -> {final_mmp}...")
                with tempfile.TemporaryDirectory() as temp_dir:
                    self.mmp_tool.unpack_all(mmp_file, temp_dir)
                    
                    for tex in textures_to_remove:
                        tex_bmp = os.path.join(temp_dir, f"{tex}.bmp")
                        if os.path.exists(tex_bmp):
                            os.remove(tex_bmp)
                    
                    self.mmp_tool.packing(paths=[temp_dir], bpp=bpp, overwrite=True, output_mmp=final_mmp)

        self.execute_async_task(worker_task)

    def apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.Window,          QColor("#1e222a"))
        palette.setColor(QPalette.WindowText,      QColor("#d8dee9"))
        palette.setColor(QPalette.Base,            QColor("#181b20"))
        palette.setColor(QPalette.AlternateBase,   QColor("#232830"))
        palette.setColor(QPalette.ToolTipBase,     QColor("#d8dee9"))
        palette.setColor(QPalette.ToolTipText,     QColor("#1e222a"))
        palette.setColor(QPalette.Text,            QColor("#d8dee9"))
        palette.setColor(QPalette.Button,          QColor("#3b4252"))
        palette.setColor(QPalette.ButtonText,      QColor("#ffffff"))
        palette.setColor(QPalette.BrightText,      QColor("#bf616a"))
        palette.setColor(QPalette.Highlight,       QColor("#88c0d0"))
        palette.setColor(QPalette.HighlightedText, QColor("#1e222a"))
        self.setPalette(palette)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    window = ModernMMPApp()
    window.show()
    sys.exit(app.exec())