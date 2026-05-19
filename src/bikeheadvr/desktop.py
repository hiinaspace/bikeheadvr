from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QThread, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QRadioButton,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .app import RuntimeOptions, RuntimeStatus, run_session
from .desktop_settings import (
    DesktopSettings,
    LoadResult,
    load_settings,
    log_path,
    save_settings,
)

LOGGER = logging.getLogger(__name__)


class EngineThread(QThread):
    status_emitted = Signal(str, str)
    session_finished = Signal(int)

    def __init__(self, options: RuntimeOptions) -> None:
        super().__init__()
        self._options = options
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        exit_code = run_session(
            self._options,
            stop_event=self._stop_event,
            status_callback=self._emit_status,
        )
        self.session_finished.emit(exit_code)

    def _emit_status(self, status: RuntimeStatus) -> None:
        self.status_emitted.emit(status.state, status.message)


class EngineController(QObject):
    status_changed = Signal(str, str)
    running_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: EngineThread | None = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, settings: DesktopSettings) -> bool:
        if self.is_running():
            return False

        options = settings.to_runtime_options(log_file=log_path())
        thread = EngineThread(options)
        thread.status_emitted.connect(self.status_changed)
        thread.session_finished.connect(self._handle_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self.running_changed.emit(True)
        thread.start()
        return True

    def stop(self) -> None:
        if self._thread is None:
            return
        self._thread.request_stop()
        self.status_changed.emit("stopping", "Stopping runtime...")

    def wait_for_stop(self, timeout_ms: int) -> bool:
        if self._thread is None:
            return True
        return self._thread.wait(timeout_ms)

    def _handle_finished(self, exit_code: int) -> None:
        if exit_code != 0:
            self.status_changed.emit(
                "error",
                "Runtime exited with an error. Check the status text or log file.",
            )
        self._thread = None
        self.running_changed.emit(False)


class MainWindow(QMainWindow):
    quit_requested = Signal()

    def __init__(
        self,
        controller: EngineController,
        load_result: LoadResult,
        tray_icon: QSystemTrayIcon,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._tray_icon = tray_icon
        self._settings = load_result.settings
        self._warning_text = load_result.warning
        self._close_to_tray_notified = False
        self._is_exiting = False
        self._applying_settings = False
        self._running_locomotion_mode: str | None = None

        self.setWindowTitle("bikeheadvr")
        self.setMinimumWidth(360)

        central = QWidget(self)
        root_layout = QVBoxLayout()
        central.setLayout(root_layout)
        self.setCentralWidget(central)

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setVisible(False)
        root_layout.addWidget(self.warning_label)

        self.mode_tabs = QTabWidget()
        self.bike_tab = QWidget(self)
        bike_layout = QVBoxLayout()
        self.bike_tab.setLayout(bike_layout)

        bike_mode_box = QGroupBox("Bike control")
        bike_mode_layout = QVBoxLayout()
        bike_mode_box.setLayout(bike_mode_layout)
        self.manual_radio = QRadioButton("Manual")
        self.tracker_radio = QRadioButton("Tracker")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.manual_radio)
        self.mode_group.addButton(self.tracker_radio)
        bike_mode_layout.addWidget(self.manual_radio)
        bike_mode_layout.addWidget(self.tracker_radio)
        bike_layout.addWidget(bike_mode_box)

        self.pedal_checkbox = QCheckBox("Pedal calibration on startup")
        bike_layout.addWidget(self.pedal_checkbox)
        bike_layout.addStretch(1)

        self.skating_tab = QWidget(self)
        skating_layout = QVBoxLayout()
        self.skating_tab.setLayout(skating_layout)
        self.skating_turn_checkbox = QCheckBox("Enable playspace turning")
        self.skating_turn_checkbox.setToolTip(
            "Uses skate roll while moving to yaw the SteamVR playspace. "
            "Leave off if you are sensitive to smooth turning."
        )
        self.skating_turn_warning_label = QLabel(
            "May cause more motion sickness than straight skating."
        )
        self.skating_turn_warning_label.setWordWrap(True)
        self.skating_debug_checkbox = QCheckBox("Show diagnostic overlays")
        self.skating_debug_checkbox.setToolTip(
            "Shows foot contact indicators and the ghost COM/force debug view."
        )
        skating_layout.addWidget(self.skating_turn_checkbox)
        skating_layout.addWidget(self.skating_turn_warning_label)
        skating_layout.addWidget(self.skating_debug_checkbox)
        skating_layout.addStretch(1)

        self.mode_tabs.addTab(self.bike_tab, "Bike")
        self.mode_tabs.addTab(self.skating_tab, "Skating")
        root_layout.addWidget(self.mode_tabs)

        self.mode_locked_label = QLabel("Stop overlay to switch modes.")
        self.mode_locked_label.setWordWrap(True)
        self.mode_locked_label.setVisible(False)
        root_layout.addWidget(self.mode_locked_label)

        self.verbose_checkbox = QCheckBox("Verbose logging")
        root_layout.addWidget(self.verbose_checkbox)

        status_box = QGroupBox("Status")
        status_layout = QGridLayout()
        status_box.setLayout(status_layout)
        self.status_label = QLabel("Stopped")
        self.detail_label = QLabel("Ready.")
        self.detail_label.setWordWrap(True)
        self.log_path_label = QLabel(str(log_path()))
        self.log_path_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        status_layout.addWidget(QLabel("State"), 0, 0)
        status_layout.addWidget(self.status_label, 0, 1)
        status_layout.addWidget(QLabel("Details"), 1, 0)
        status_layout.addWidget(self.detail_label, 1, 1)
        status_layout.addWidget(QLabel("Log file"), 2, 0)
        status_layout.addWidget(self.log_path_label, 2, 1)
        root_layout.addWidget(status_box)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.start_stop_button = QPushButton("Start")
        self.hide_button = QPushButton("Hide to tray")
        self.quit_button = QPushButton("Quit")
        button_row.addWidget(self.hide_button)
        button_row.addWidget(self.quit_button)
        button_row.addWidget(self.start_stop_button)
        root_layout.addLayout(button_row)

        self.manual_radio.toggled.connect(self._handle_settings_changed)
        self.tracker_radio.toggled.connect(self._handle_settings_changed)
        self.mode_tabs.currentChanged.connect(self._handle_settings_changed)
        self.pedal_checkbox.toggled.connect(self._handle_settings_changed)
        self.skating_turn_checkbox.toggled.connect(self._handle_settings_changed)
        self.skating_debug_checkbox.toggled.connect(self._handle_settings_changed)
        self.verbose_checkbox.toggled.connect(self._handle_settings_changed)
        self.start_stop_button.clicked.connect(self._toggle_runtime)
        self.hide_button.clicked.connect(self.hide_to_tray)
        self.quit_button.clicked.connect(self.quit_requested.emit)

        controller.status_changed.connect(self._update_status)
        controller.running_changed.connect(self._handle_running_changed)

        self._apply_settings_to_widgets()
        if self._warning_text:
            self.warning_label.setText(self._warning_text)
            self.warning_label.setVisible(True)

    def set_exiting(self) -> None:
        self._is_exiting = True

    def current_settings(self) -> DesktopSettings:
        return DesktopSettings(
            locomotion_mode=self._selected_locomotion_mode(),
            pedal_calibration_enabled=self.pedal_checkbox.isChecked(),
            skating_playspace_turn_enabled=self.skating_turn_checkbox.isChecked(),
            skating_debug_overlays_enabled=self.skating_debug_checkbox.isChecked(),
            verbose_logging=self.verbose_checkbox.isChecked(),
            start_minimized=self._settings.start_minimized,
        )

    def hide_to_tray(self) -> None:
        self.hide()
        if not self._close_to_tray_notified:
            self._tray_icon.showMessage(
                "bikeheadvr",
                "bikeheadvr is still running in the tray.",
                QSystemTrayIcon.Information,
                2500,
            )
            self._close_to_tray_notified = True

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._is_exiting:
            event.accept()
            return
        event.ignore()
        self.hide_to_tray()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            self.hide_to_tray()

    def _apply_settings_to_widgets(self) -> None:
        self._applying_settings = True
        if self._settings.locomotion_mode == "skating":
            self.manual_radio.setChecked(True)
            self.mode_tabs.setCurrentWidget(self.skating_tab)
        elif self._settings.locomotion_mode == "tracker":
            self.tracker_radio.setChecked(True)
            self.mode_tabs.setCurrentWidget(self.bike_tab)
        else:
            self.manual_radio.setChecked(True)
            self.mode_tabs.setCurrentWidget(self.bike_tab)
        self.pedal_checkbox.setChecked(self._settings.pedal_calibration_enabled)
        self.skating_turn_checkbox.setChecked(
            self._settings.skating_playspace_turn_enabled
        )
        self.skating_debug_checkbox.setChecked(
            self._settings.skating_debug_overlays_enabled
        )
        self.verbose_checkbox.setChecked(self._settings.verbose_logging)
        self._applying_settings = False
        self._sync_mode_options_enabled()

    def _handle_settings_changed(self) -> None:
        if self._applying_settings:
            return
        if self._controller.is_running():
            self._sync_mode_options_enabled()
            return
        self._settings = self.current_settings()
        self._sync_mode_options_enabled()
        save_settings(self._settings)

    def _handle_running_changed(self, running: bool) -> None:
        if not running:
            self._running_locomotion_mode = None
        self.start_stop_button.setText("Stop" if running else "Start")
        self._sync_mode_options_enabled()
        if not running and self.status_label.text() == "Running":
            self.status_label.setText("Stopped")

    def _toggle_runtime(self) -> None:
        if self._controller.is_running():
            self._controller.stop()
            return

        self._settings = self.current_settings()
        save_settings(self._settings)
        self._running_locomotion_mode = self._settings.locomotion_mode
        started = self._controller.start(self._settings)
        if started:
            self._update_status("starting", "Starting runtime...")
            self._sync_mode_options_enabled()
        else:
            self._running_locomotion_mode = None
            self._sync_mode_options_enabled()

    def _update_status(self, state: str, message: str) -> None:
        if state == "running":
            self.status_label.setText("Running")
        elif state == "starting":
            self.status_label.setText("Starting")
        elif state == "stopping":
            self.status_label.setText("Stopping")
        elif state == "error":
            self.status_label.setText("Error")
        elif state == "stopped":
            self.status_label.setText("Stopped")
        self.detail_label.setText(message)

    def _selected_locomotion_mode(self) -> str:
        if self.mode_tabs.currentWidget() == self.skating_tab:
            return "skating"
        if self.tracker_radio.isChecked():
            return "tracker"
        return "manual"

    def _sync_mode_options_enabled(self) -> None:
        enabled = not self._controller.is_running()
        self.manual_radio.setEnabled(enabled)
        self.tracker_radio.setEnabled(enabled)
        self.pedal_checkbox.setEnabled(enabled)
        self.skating_turn_checkbox.setEnabled(enabled)
        self.skating_debug_checkbox.setEnabled(enabled)
        self.verbose_checkbox.setEnabled(enabled)
        mode_switch_pending = (
            not enabled
            and self._running_locomotion_mode is not None
            and self._selected_locomotion_mode() != self._running_locomotion_mode
        )
        self.mode_locked_label.setVisible(mode_switch_pending)


def create_tray_icon(
    controller: EngineController, icon: QIcon | None = None
) -> tuple[QSystemTrayIcon, QAction, QAction, QAction]:
    tray_icon = QSystemTrayIcon(icon or _load_app_icon())
    tray_icon.setToolTip("bikeheadvr")
    menu = QMenu()
    open_action = menu.addAction("Open")
    toggle_action = menu.addAction("Start")
    menu.addSeparator()
    exit_action = menu.addAction("Exit")
    tray_icon.setContextMenu(menu)

    controller.running_changed.connect(
        lambda running: toggle_action.setText("Stop" if running else "Start")
    )
    return tray_icon, open_action, toggle_action, exit_action


def main(argv: list[str] | None = None) -> int:
    del argv
    QApplication.setApplicationName("bikeheadvr")
    QApplication.setOrganizationName("bikeheadvr")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        LOGGER.error("System tray is not available on this Windows session.")
        return 1

    app_icon = _load_app_icon()
    app.setWindowIcon(app_icon)
    load_result = load_settings()
    controller = EngineController()
    tray_icon, open_action, toggle_action, exit_action = create_tray_icon(
        controller, app_icon
    )
    window = MainWindow(controller, load_result, tray_icon)
    window.setWindowIcon(app_icon)

    open_action.triggered.connect(window.showNormal)
    open_action.triggered.connect(window.activateWindow)
    toggle_action.triggered.connect(window._toggle_runtime)

    def exit_app() -> None:
        window.set_exiting()
        if controller.is_running():
            controller.stop()
            controller.wait_for_stop(5000)
        tray_icon.hide()
        app.quit()

    window.quit_requested.connect(exit_app)
    exit_action.triggered.connect(exit_app)
    tray_icon.activated.connect(
        lambda reason: (
            (
                window.showNormal(),
                window.activateWindow(),
            )
            if reason == QSystemTrayIcon.Trigger
            else None
        )
    )
    tray_icon.show()

    if load_result.settings.start_minimized:
        window.hide()
    else:
        window.show()

    return app.exec()


def _default_app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)

    quadrants = [
        (0, 0, "#274c77", "B"),
        (32, 0, "#6096ba", "H"),
        (0, 32, "#a3cef1", "V"),
        (32, 32, "#8b1e3f", "R"),
    ]
    font = QFont("Segoe UI", 20, QFont.Bold)
    painter.setFont(font)
    metrics = QFontMetrics(font)

    for x, y, color, label in quadrants:
        painter.setBrush(QColor(color))
        painter.drawRect(x, y, 32, 32)
        painter.setPen(QPen(QColor("white")))
        text_rect = metrics.boundingRect(label)
        text_x = x + (32 - text_rect.width()) / 2
        text_y = y + (32 + metrics.ascent() - metrics.descent()) / 2 - 1
        painter.drawText(int(text_x), int(text_y), label)
        painter.setPen(Qt.NoPen)

    painter.setPen(QPen(QColor("#0d1b2a"), 2))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(1, 1, 62, 62)
    painter.end()
    return QIcon(pixmap)


def _load_app_icon() -> QIcon:
    icon_path = Path(__file__).resolve().parents[2] / "bikeheadvr.ico"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
    return _default_app_icon()
