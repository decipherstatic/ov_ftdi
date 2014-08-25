import sys
from PyQt5.QtCore import pyqtSlot, QAbstractItemModel, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem, QLabel
from PyQt5.QtGui import QColor

from mainwindow import Ui_MainWindow
import ovctl
from ovctl import OVControl
#import LibOV

TS = 0
FLAG = 1
DATA = 2

#  Physical layer error
HF0_ERR =  0x01
# RX Path Overflow
HF0_OVF =  0x02
# Clipped by Filter
HF0_CLIP = 0x04
# Clipped due to packet length (> 800 bytes)
HF0_TRUNC = 0x08
# First packet of capture session; IE, when the cap hardware was enabled
HF0_FIRST = 0x10
# Last packet of capture session; IE, when the cap hardware was disabled
HF0_LAST = 0x20

PID_DICT = \
{ 0x1: "OUT"   , 0x2: "ACK"  , 0x3: "DATA0", 0x4: "PING",
  0x5: "SOF"   , 0x6: "NYET" , 0x7: "DATA2", 0x8: "SPLIT",
  0x9: "IN"    , 0xA: "NAK"  , 0xB: "DATA1", 0xC: "ERR",
  0xD: "SETUP" , 0xE: "STALL", 0xF: "MDATA" }

TS_COL = 0
FLAG_COL = 1
PID_COL = 2
DATA_COL = 3

class OV_UI(QMainWindow):
	def __init__(self, parent=None):
		super(OV_UI, self).__init__(parent)
		
		self.ui = Ui_MainWindow()
		self.ui.setupUi(self)
        
		self.ovc = OVControl()
		self.uiTimer = QTimer(self)
		self.uiTimer.timeout.connect(self.updateui)
		self.uiTimer.setInterval(10)
		self.initUI()
		self.row = 1
		self.filters = {}
		self.msgCount = 0
		self.uiCounterInterval = 10
		self.currentIntervalCount = 0
		self.packetsPer100ms = 0
		
		
		#self.dev = LibOV.OVDevice()
	def updateui(self):
		maxitems = 30
		
		if self.currentIntervalCount >= self.uiCounterInterval:
			self.updateStatus("%d / second" %(self.packetsPer100ms * 10))
			self.packetsPer100ms = 0
			self.currentIntervalCount = 0
		else:
			self.currentIntervalCount += 1
			
		while len(ovctl.rxQueue) > 0 and (maxitems > 0):
		#while maxitems > 0:
			#packet = ovctl.outputpipe.recv()
			packet = ovctl.rxQueue.popleft()
			self.handlePacket(packet)
			self.packetsPer100ms += 1
			#print(packet)
			
			
			maxitems -= 1
		
		

	
	@pyqtSlot()
	def on_exit(self):
		self.shutdown()
		self.close()
	
	@pyqtSlot()
	def OpenDevice(self):
		self.resetTable()
		self.uiTimer.start()
		self.ovc.open()
	
	@pyqtSlot(bool)
	def ToggleConnection(self, toggled):
		self.deviceConnect(toggled)
	
	@pyqtSlot()
	def Open(self):
		self.deviceConnect(True)
	
	@pyqtSlot()
	def Close(self):
		self.deviceConnect(False)
	
	@pyqtSlot(int)
	def UpdateSpeed(self, index):
		speed = self.ui.usbSpeedComboBox.itemData(index)
		print(speed)
		self.ovc.set_usb_speed(speed)
	
	@pyqtSlot(bool)
	def ToggleSOFFilter(self, enable):
		self.filters[0x05] = enable
	
	def isValidPid(self, pid):
		return (pid >> 4) ^ 0xF == pid & 0xF
	
	def formatPid(self, pid):
		if self.isValidPid(pid):
			return PID_DICT[pid & 0xF]
		else:
			return "Err: %02X" %(pid)
	

	def handlePacket(self, packet):
		error = False
		flag = ""
		if packet[FLAG] != 0:
			if packet[FLAG] & HF0_FIRST:
				return
			
			error = True
			if packet[FLAG] & HF0_OVF:
				flag += "Overflow"
			else:
				flag += "%02X" %(packet[FLAG])
		else:
			flag = "OK"
		
		#
		tsItem = QTableWidgetItem(str(packet[TS]))
		flagsItem = QTableWidgetItem(flag)
		
		if not error:
			
			pidbyte = packet[DATA][0]
			pid = pidbyte & 0xF
		
			if self.isPacketFiltered(pid):
				return
				
			pid_str = self.formatPid(pidbyte)
			
			
			pidItem = QTableWidgetItem(pid_str)
			data = " ".join("%2X" %x for x in packet[DATA][1:])
			dataItem = QTableWidgetItem(data)
			
			self.ui.rxDataTable.setRowCount(self.row+1)
			self.ui.rxDataTable.setItem(self.row, TS_COL, tsItem)
			self.ui.rxDataTable.setItem(self.row, FLAG_COL, flagsItem)
			self.ui.rxDataTable.setItem(self.row, PID_COL, pidItem)
			self.ui.rxDataTable.setItem(self.row, DATA_COL, dataItem)
		
		self.ui.rxDataTable.scrollToItem(tsItem)
		self.row += 1
	
	def resetTable(self):
		self.row  = 1
		self.ui.rxDataTable.clear()
		self.ui.rxDataTable.setColumnCount(4)
		self.ui.rxDataTable.setHorizontalHeaderItem(0, QTableWidgetItem("Timestamp"))
		self.ui.rxDataTable.setHorizontalHeaderItem(1, QTableWidgetItem("Flags"))
		self.ui.rxDataTable.setHorizontalHeaderItem(2, QTableWidgetItem("PID"))
		self.ui.rxDataTable.setHorizontalHeaderItem(3, QTableWidgetItem("Data"))
		self.ui.rxDataTable.horizontalHeader().setStretchLastSection(True)
		self.ui.rxDataTable.setRowCount(1)
	
	def deviceConnect(self, connect=False):
		if connect:
			self.resetTable()
			self.uiTimer.start()
			self.ovc.open()
			self.ui.openClosePushButton.setText("Close")
		else:
			self.uiTimer.stop()
			self.ovc.close()
			self.ui.openClosePushButton.setText("Open")
	
	def isPacketFiltered(self, pid):
		if pid in self.filters:
			return self.filters[pid]
		else:
			return False
			
	def shutdown(self):
		self.uiTimer.stop()
		self.ovc.close()
	
	def updateStatus(self, status):
		self.statusLabel.setText("Status: " + status)
		
		
	def initUI(self):
		
		# Add items to the speeds drop down
		self.ui.usbSpeedComboBox.addItem("Low Speed", "ls")
		self.ui.usbSpeedComboBox.addItem("Full Speed", "fs")
		self.ui.usbSpeedComboBox.addItem("High Speed", "hs")
		
		# Configure the data view
		self.resetTable()

		
		
		# Configure the statusbar
		self.statusLabel = QLabel(self)
		self.updateStatus("Idle")
		self.ui.statusBar.addPermanentWidget(self.statusLabel)
		
		
		# Setup all events
		self.ui.usbSpeedComboBox.currentIndexChanged.connect(self.UpdateSpeed)
		self.ui.openClosePushButton.clicked.connect(self.ToggleConnection)
		self.ui.actionConnect.triggered.connect(self.Open)
		self.ui.actionDisconnect.triggered.connect(self.Close)
		self.ui.actionExit.triggered.connect(self.on_exit)
		self.ui.filterSOFPackets.clicked.connect(self.ToggleSOFFilter)
		
		self.ui.usbSpeedComboBox.setCurrentIndex(1)
	

if __name__=="__main__":
	app = QApplication(sys.argv)
	ov = OV_UI()
	ov.show()
	sys.exit(app.exec_())
