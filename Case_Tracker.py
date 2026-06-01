import sys
import json
import os
import re

import easyocr
import mss
import numpy as np

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QLineEdit
)

from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtCore import Qt, QRect, QPoint, QTimer

import keyboard


# =========================
# OVERLAY SELECTOR
# =========================
class ScreenSelector(QWidget):
    def __init__(self, callback):
        super().__init__()

        self.callback = callback
        self.step = "inventory"
        self.last_spin_value = None
        self.spin_pending = False
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_values)
        self.timer.start(2000)  # every 2 seconds

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.showFullScreen()

        self.start_point = QPoint()
        self.end_point = QPoint()
        self.selecting = False

    def mousePressEvent(self, event):
        self.start_point = event.pos()
        self.end_point = event.pos()
        self.selecting = True

    def mouseMoveEvent(self, event):
        self.end_point = event.pos()
        self.update()

    def mouseReleaseEvent(self, event):
        self.end_point = event.pos()
        self.selecting = False

        rect = QRect(self.start_point, self.end_point).normalized()

        region = {
            "left": rect.left(),
            "top": rect.top(),
            "width": rect.width(),
            "height": rect.height()
        }

        self.callback(self.step, region)
        self.close()

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.fillRect(self.rect(), QColor(0, 0, 0, 80))

        if self.selecting:
            pen = QPen(QColor(0, 255, 0), 2)
            painter.setPen(pen)
            painter.drawRect(QRect(self.start_point, self.end_point))


# =========================
# MAIN APP
# =========================
class CaseTracker(QWidget):
    def __init__(self):
        super().__init__()

        self.config_file = "config.json"
        self.load_config()

        self.reader = easyocr.Reader(['en'], gpu=False)

        # session data
        self.session_active = False
        self.start_net = 0
        self.current_net = 0
        self.rolls = 0
        self.last_spin_value = None

        self.setWindowTitle("Case Tracker")
        self.setGeometry(100, 100, 500, 600)

        self.setStyleSheet("""
            QWidget {
                background-color: black;
                color: white;
                font-size: 14px;
            }

            QPushButton {
                background-color: #222;
                border: 1px solid #555;
                padding: 8px;
            }

            QLineEdit {
                background-color: #111;
                border: 1px solid #555;
                padding: 5px;
                color: white;
            }
        """)

        layout = QVBoxLayout()

        self.case_cost = QLineEdit()
        self.case_cost.setPlaceholderText("Cost per 5 cases")

        self.start_button = QPushButton("Start Session")
        self.stop_button = QPushButton("Stop Session")
        self.reset_button = QPushButton("Reset Session")
        self.calibrate_button = QPushButton("Recalibrate OCR")
        self.test_ocr_button = QPushButton("Test OCR")

        self.status_label = QLabel("Status: Waiting")
        self.rolls_label = QLabel("Rolls: 0")

        self.session_label = QLabel("Session P/L: $0.00")
        self.net_label = QLabel("Net Worth: $0.00")

        layout.addWidget(self.case_cost)

        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(self.reset_button)

        layout.addWidget(self.calibrate_button)
        layout.addWidget(self.test_ocr_button)

        layout.addSpacing(10)

        layout.addWidget(self.status_label)
        layout.addWidget(self.rolls_label)
        layout.addWidget(self.net_label)
        layout.addWidget(self.session_label)

        self.setLayout(layout)

        # buttons
        self.start_button.clicked.connect(self.start_session)
        self.stop_button.clicked.connect(self.stop_session)
        self.reset_button.clicked.connect(self.reset_session)
        self.calibrate_button.clicked.connect(self.calibrate_ocr)
        self.test_ocr_button.clicked.connect(self.update_values)

        # R key hook
        keyboard.on_press_key("r", self.on_roll)

        # live update timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_values)
        self.timer.start(3000)

    # =========================
    # CONFIG
    # =========================
    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    self.config = json.load(f)
            except:
                self.config = {}
        else:
            self.config = {}

    def save_config(self):
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=4)

    # =========================
    # OCR
    # =========================
    def capture(self, region):
        with mss.mss() as sct:
            img = np.array(sct.grab(region))
        return img

    def read(self, region):
        img = self.capture(region)

        text = self.reader.readtext(
            img,
            detail=0,
            allowlist="0123456789,.$"
        )

        if not text:
            return 0.0

        raw = "".join(text)
        nums = re.findall(r"[\d,]+\.\d+", raw)

        if not nums:
            return 0.0

        return float(nums[0].replace(",", ""))

    # =========================
    # SESSION LOGIC
    # =========================
    def start_session(self):
        self.session_active = True
        self.rolls = 0
        self.start_net = self.current_net
        self.status_label.setText("Session Started")

    def stop_session(self):
        self.session_active = False
        self.status_label.setText("Session Stopped")

    def reset_session(self):
        self.start_net = 0
        self.current_net = 0
        self.rolls = 0
        self.last_spin_value = None
        self.rolls_label.setText("Rolls: 0")
        self.session_label.setText("Session P/L: $0.00")
        self.status_label.setText("Session Reset")
        self.update_values()

    def on_roll(self, _):
        if not self.session_active:
            return

        try:
            cost = float(self.case_cost.text() or 0)
        except:
            cost = 0

        # snapshot BEFORE spin
        self.last_spin_value = self.current_net

        self.start_net -= cost
        self.rolls += 1
        self.rolls_label.setText(f"Rolls: {self.rolls}")

        self.status_label.setText("Spin detected... waiting result")

        # delay so OCR catches AFTER spin
        QTimer.singleShot(4000, self.finalize_spin)

    def finalize_spin(self):
        inv_r = self.config.get("inventory_region")
        cash_r = self.config.get("cash_region")

        if not inv_r or not cash_r:
            return

        inv = self.read(inv_r)
        cash = self.read(cash_r)

        new_net = inv + cash

        if self.last_spin_value is None:
            return

        diff = new_net - self.last_spin_value

        color = "green" if diff >= 0 else "red"

        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(f"Spin Result: ${diff:,.2f}")

    # =========================
    # UPDATE VALUES
    # =========================
    def update_values(self):
        inv_r = self.config.get("inventory_region")
        cash_r = self.config.get("cash_region")

        if not inv_r or not cash_r:
            return

        inv = self.read(inv_r)
        cash = self.read(cash_r)

        net = inv + cash

        self.current_net = net
        self.net_label.setText(f"Net Worth: ${net:,.2f}")

        # live session profit (always updating)
        if self.start_net != 0:
            profit = net - self.start_net

            color = "green" if profit >= 0 else "red"
            self.session_label.setStyleSheet(f"color: {color};")
            self.session_label.setText(f"Session P/L: ${profit:,.2f}")

    # =========================
    # CALIBRATION
    # =========================
    def calibrate_ocr(self):
        self.selector = ScreenSelector(self.handle_select)
        self.selector.step = "inventory"

    def handle_select(self, step, region):
        if step == "inventory":
            self.config["inventory_region"] = region
            self.save_config()

            self.selector = ScreenSelector(self.handle_select)
            self.selector.step = "cash"
        else:
            self.config["cash_region"] = region
            self.save_config()


# =========================
# RUN
# =========================
app = QApplication(sys.argv)
window = CaseTracker()
window.show()
sys.exit(app.exec())
