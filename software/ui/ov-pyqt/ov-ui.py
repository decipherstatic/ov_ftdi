import sys
from PyQt5.QtCore import pyqtSlot, QAbstractItemModel, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow, QTableWidgetItem
from PyQt5.QtGui import QColor

from mainwindow import Ui_MainWindow
import ovctl
from ovctl import OVControl
#import LibOV


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
		
		#self.dev = LibOV.OVDevice()
	def updateui(self):
		maxitems = 10

		while len(ovctl.rxQueue) > 0 and (maxitems > 0):
		#while maxitems > 0:
			#packet = ovctl.outputpipe.recv()
			packet = ovctl.rxQueue.popleft()
			#print(packet)
			self.ui.rxDataTable.setRowCount(self.row+1)
			ts = QTableWidgetItem(str(packet[0]))
			flags = QTableWidgetItem(str(packet[1]))
			#flags.setBackground(QColor("Blue"))
			if len(packet[2]) > 0:
				pid = packet[2][0] & 0xF
				if (packet[2][0] >> 4) ^ 0xF != pid:
					print("Err - bad PID of %02x" % pid)
			
			if self.isPacketFiltered(pid):
				continue
				
			data = " ".join("%2X" %x for x in packet[2])
			data = QTableWidgetItem(data)
			self.ui.rxDataTable.setItem(self.row, 0, ts)
			self.ui.rxDataTable.setItem(self.row, 1, flags)
			self.ui.rxDataTable.setItem(self.row, 2, data)
			self.ui.rxDataTable.scrollToItem(data)
			self.row += 1
			
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
	
	def resetTable(self):
		self.row  = 1
		self.ui.rxDataTable.clear()
		self.ui.rxDataTable.setHorizontalHeaderItem(0, QTableWidgetItem("Timestamp"))
		self.ui.rxDataTable.setHorizontalHeaderItem(1, QTableWidgetItem("Flags"))
		self.ui.rxDataTable.setHorizontalHeaderItem(2, QTableWidgetItem("Data"))
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
		
		
	def initUI(self):
		
		self.ui.usbSpeedComboBox.addItem("Low Speed", "ls")
		self.ui.usbSpeedComboBox.addItem("Full Speed", "fs")
		self.ui.usbSpeedComboBox.addItem("High Speed", "hs")
		
		self.ui.rxDataTable.setColumnCount(3)
		#self.ui.rxDataTable.setRowCount(200000)
		self.ui.rxDataTable.setHorizontalHeaderItem(0, QTableWidgetItem("Timestamp"))
		self.ui.rxDataTable.setHorizontalHeaderItem(1, QTableWidgetItem("Flags"))
		self.ui.rxDataTable.setHorizontalHeaderItem(2, QTableWidgetItem("Data"))
		self.ui.rxDataTable.horizontalHeader().setStretchLastSection(True)
		
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
