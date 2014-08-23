#!/usr/bin/python3.3

# This needs python3.3 or greater - argparse changes behavior
# TODO - workaround

import LibOV
import argparse
import time

import zipfile

import sys
import os
import struct

from PyQt5 import QtCore
import queue
from collections import deque
from multiprocessing import Process, Pipe
#import yappi

def as_ascii(arg):
    if arg == None:
        return None
    return arg.encode('ascii')

class Command:
    def __subclasshook__(self):
        pass

    @staticmethod
    def setup_args(sp):
        pass

__cmd_keeper = []
def command(_name, *_args):
    def _i(todeco):
        class _sub(Command):
            name = _name

            @staticmethod
            def setup_args(sp):
                for (name, typ, *default) in _args:
                    if len(default):
                            name = "--" + name
                            default = default[0]
                    else:
                        default = None
                    sp.add_argument(name, type=typ, default=default)

            @staticmethod
            def go(dev, args):
                aarray = dict([(i, getattr(args, i)) for (i, *_) in _args])
                todeco(dev, **aarray)
        __cmd_keeper.append(_sub)
        return todeco

    return _i

int16 = lambda x: int(x, 16)


def check_ulpi_clk(dev):
    clks_up = dev.regs.ucfg_stat.rd()

    if not clks_up:
        print("ULPI Clock has not started up - osc?")
        return 1

    return 0

@command('uwrite', ('addr', str), ('val', int16))
def uwrite(dev, addr, val):
    addr = int(addr, 16)

    if check_ulpi_clk(dev):
        return 

    dev.ulpiwrite(addr, val)

@command('uread', ('addr', str))
def uread(dev, addr):
    addr = int(addr, 16)

    if check_ulpi_clk(dev):
        return 

    print ("ULPI %02x: %02x" % (addr, dev.ulpiread(addr)))

@command('report')
def report(dev):

    print("USB PHY Tests")
    if check_ulpi_clk(dev):
        print("\tWARNING: ULPI PHY clock not started; skipping ULPI tests")
    else:
        # display the ULPI identifier
        ident = 0
        for x in [dev.ulpiregs.vidh,
                dev.ulpiregs.vidl,
                dev.ulpiregs.pidh,
                dev.ulpiregs.pidl]:
            ident <<= 8
            ident |= x.rd()

        name = 'unknown'
        if ident == LibOV.SMSC_334x_MAGIC:
            name = 'SMSC 334x'
        print("\tULPI PHY ID: %08x (%s)" % (ident, name))

        # do in depth phy tests
        if ident == LibOV.SMSC_334x_MAGIC:
            dev.ulpiregs.scratch.wr(0)
            dev.ulpiregs.scratch_set.wr(0xCF)
            dev.ulpiregs.scratch_clr.wr(0x3C)

            stat = "OK" if dev.ulpiregs.scratch.rd() == 0xC3 else "FAIL"

            print("\tULPI Scratch register IO test: %s" % stat)
            print("\tPHY Function Control Reg:  %02x" % dev.ulpiregs.func_ctl.rd())
            print("\tPHY Interface Control Reg: %02x" % dev.ulpiregs.intf_ctl.rd())
        else:
            print("\tUnknown PHY - skipping phy tests")

    print ("SDRAM tests")
    def cb(n, ok):
        print("\t... %d: %s" % (n, "OK" if ok else "FAIL"))
    stat = do_sdramtests(dev, cb)
    if stat == -1:
        print("\t... all passed")


class OutputCustom:
    def __init__(self, output):
        self.output = output

    def handle_usb(self, pkt, flags):
        pkthex = " ".join("%02x" % x for x in pkt)
        self.output.write("data=%s speed=%s\n" % (pkthex, speed.upper()))


class OutputPcap:
    LINK_TYPE = 255 #FIXME

    def __init__(self, output):
        self.output = output
        self.output.write(struct.pack("IHHIIII", 0xa1b2c3d4, 2, 4, 0, 0, 1<<20, self.LINK_TYPE))

    def handle_usb(self, pkt, flags):
        self.output.write(struct.pack("IIIIH", 0, 0, len(pkt) + 2, len(pkt) + 2, flags))
        self.output.write(pkt)

def do_sdramtests(dev, cb=None):
    
    for i in range(0,6):
        dev.regs.SDRAM_TEST_CMD.wr(0x80 | i)
        stat = 0x40
        while (stat & 0x40):
            time.sleep(0.1)
            stat = dev.regs.SDRAM_TEST_CMD.rd() 

        ok = stat & 0x20
        cb(i, ok)

        if not ok:
            return i
    else:
        return -1

@command('sdramtest')
def sdramtest(dev):
    # LEDS select
    dev.regs.LEDS_MUX_0.wr(1)

    stat = do_sdramtests(dev)
    if stat != -1:
        print("SDRAM test failed on test %d\n" % stat)
    else:
        print("SDRAM test passed")

    dev.regs.LEDS_MUX_0.wr(0)

@command('sniff', ('speed', str), ('format', str, 'verbose'), ('out', str, None), ('timeout', int, None))
def sniff(dev, speed, format, out, timeout):
    # LEDs off
    dev.regs.LEDS_MUX_2.wr(0)
    dev.regs.LEDS_OUT.wr(0)

    # LEDS 0/1 to FTDI TX/RX
    dev.regs.LEDS_MUX_0.wr(2)
    dev.regs.LEDS_MUX_1.wr(2)

    assert speed in ["hs", "fs", "ls"]

    if check_ulpi_clk(dev):
        return

    # set to non-drive; set FS or HS as requested
    if speed == "hs":
            dev.ulpiregs.func_ctl.wr(0x48)
            dev.rxcsniff.service.highspeed = True
    elif speed == "fs":
            dev.ulpiregs.func_ctl.wr(0x49)
            dev.rxcsniff.service.highspeed = False
    elif speed == "ls":
            dev.ulpiregs.func_ctl.wr(0x4a)
            dev.rxcsniff.service.highspeed = False
    else:
        assert 0,"Invalid Speed"

    assert format in ["verbose", "custom", "pcap"]

    output_handler = None
    out = out and open(out, "wb")

    if format == "custom":
        output_handler = OutputCustom(out or sys.stdout)
    elif format == "pcap":
        assert out, "can't output pcap to stdout, use --out"
        output_handler = OutputPcap(out)

    if output_handler is not None:
      dev.rxcsniff.service.handlers = [output_handler.handle_usb]

    elapsed_time = 0
    try:
        dev.regs.CSTREAM_CFG.wr(1)
        while 1:
            if timeout and elapsed_time > timeout:
                break
            time.sleep(1)
            elapsed_time = elapsed_time + 1
    except KeyboardInterrupt:
        pass
    finally:
        dev.regs.CSTREAM_CFG.wr(0)

    if out is not None:
        out.close()

@command('debug-stream')
def debug_stream(dev):
    cons = dev.regs.CSTREAM_CONS_LO.rd() | dev.regs.CSTREAM_CONS_HI.rd() << 8
    prod_hd = dev.regs.CSTREAM_PROD_HD_LO.rd() | dev.regs.CSTREAM_PROD_HD_HI.rd() << 8
    prod = dev.regs.CSTREAM_PROD_LO.rd() | dev.regs.CSTREAM_PROD_HI.rd() << 8
    size = dev.regs.CSTREAM_SIZE_LO.rd() | dev.regs.CSTREAM_SIZE_HI.rd() << 8

    state = dev.regs.CSTREAM_PROD_STATE.rd()

    laststart = dev.regs.CSTREAM_LAST_START_LO.rd() | dev.regs.CSTREAM_LAST_START_HI.rd() << 8
    lastcount = dev.regs.CSTREAM_LAST_COUNT_LO.rd() | dev.regs.CSTREAM_LAST_COUNT_HI.rd() << 8
    lastpw = dev.regs.CSTREAM_LAST_PW_LO.rd() | dev.regs.CSTREAM_LAST_PW_HI.rd() << 8

    print("cons: %04x prod-wr: %04x prod-hd: %04x size: %04x state: %02x" % (cons, prod, prod_hd, size, state))
    print("\tlaststart: %04x lastcount: %04x (end: %04x) pw-at-write: %04x" % (laststart, lastcount, laststart + lastcount, lastpw))

@command('ioread', ('addr', str))
def ioread(dev, addr):
    print("%s: %02x" % (addr, dev.ioread(addr)))

@command('iowrite', ('addr', str), ('value', int16))
def iowrite(dev, addr, value):
    dev.iowrite(addr, value)

@command('led-test', ('v', int16))
def ledtest(dev, v):
    dev.regs.leds_out.wr(v)

@command('eep-erase')
def eeperase(dev):
    dev.dev.eeprom_erase()

@command('eep-program', ('serialno', int))
def eepprogram(dev, serialno):
    dev.dev.eeprom_program(serialno)

class LB_Test(Command):
    name = "lb-test"

    @staticmethod
    def setup_args(sp):
        sp.add_argument("size", type=int, default=64, nargs='?')

    @staticmethod
    def go(dev, args):
        # Stop the generator - do twice to make sure
        # theres no hanging packet 
        dev.regs.RANDTEST_CFG.wr(0)
        dev.regs.RANDTEST_CFG.wr(0)

        # LEDs off
        dev.regs.LEDS_MUX_2.wr(0)
        dev.regs.LEDS_OUT.wr(0)

        # LEDS 0/1 to FTDI TX/RX
        dev.regs.LEDS_MUX_0.wr(2)
        dev.regs.LEDS_MUX_1.wr(2)

        # Set test packet size
        dev.regs.RANDTEST_SIZE.wr(args.size)

        # Reset the statistics counters
        dev.lfsrtest.reset()

        # Start the test (and reinit the generator)
        dev.regs.RANDTEST_CFG.wr(1)

        st = time.time()
        try:
            while 1:
                time.sleep(1)
                b = dev.lfsrtest.stats()
                print("%4s %20d bytes %f MB/sec average" % (
                    "ERR" if b.error else "OK", 
                    b.total, b.total/float(time.time() - st)/1024/1024))

        except KeyboardInterrupt:
            dev.regs.randtest_cfg.wr(0)


event_loop = queue.Queue()
rxQueue = deque()# queue.Queue()
#inputpipe, outputpipe = Pipe()

class OVControl:
    def __init__(self, pkg='ov3.fwpkg'):
        self.isopen = False
        self.speed = "hs"
        self.queue = deque(maxlen=5000)
        zfile = zipfile.ZipFile(pkg, 'r')
        mapfile = zfile.open('map.txt', 'r')
        self.bitfile = zfile.open('ov3.bit', 'r')
        
        self.dev = LibOV.OVDevice(mapfile=mapfile, verbose=False)
        
        self.rxThread = WorkerThread(self)
        
        zfile.close()
    
    def open(self):
        
        if self.isopen:
            return
            
        self.dev.open()
        
        if not self.dev.isLoaded():
            self.dev.close()
            err = self.dev.open(self.bitfile)
            
        self.isopen = True
        
        self.dev.dev.write(LibOV.FTDI_INTERFACE_A, b'\x00' * 512, async=False)
        self.set_led(1)
        
        '''
        # set to non-drive; set FS or HS as requested
        if self.speed == "hs":
            self.dev.ulpiregs.func_ctl.wr(0x48)
            self.dev.rxcsniff.service.highspeed = True
        elif self.speed == "fs":
            self.dev.ulpiregs.func_ctl.wr(0x49)
            self.dev.rxcsniff.service.highspeed = False
        elif self.speed == "ls":
            self.dev.ulpiregs.func_ctl.wr(0x4a)
            self.dev.rxcsniff.service.highspeed = False
        else:
            assert 0,"Invalid Speed"
        
        # testing
        if check_ulpi_clk(self.dev):
            return
        
        self.dev.rxcsniff.service.handlers = [self.handle_usb]
        self.dev.regs.CSTREAM_CFG.wr(1)
        '''
        self.rxThread.start()
        
        
    def close(self):

        if not self.isopen:
            return
        
        self.rxThread.stop()
        
        self.set_led(0)
        self.dev.close()
        self.isopen = False
    
    def set_led(self, led):
        ledtest(self.dev, led)
    
    def set_usb_speed(self, speed="fs"):
        self.speed = speed
        
    
    def handle_usb(self, ts, pkt, flags):
        #a = (ts, pkt, flags)
        #print(a)
        #inputpipe.send((ts,flags,pkt))
        #print("testing")
        #self.queue.append(ts)
        rxQueue.append((ts,flags,pkt))
        
        
class UsbPacket:
    def __init__(self, ts, flags, data):
        self.ts = ts
        self.flags = flags
        self.data = data
    
    def __str__(self):
        return  "%d,%02X,%s" %(self.ts, self.flags, " ".join("%-2X" %x for x in self.data))



    
class WorkerThread(QtCore.QThread):
    
    def __init__(self, ov):
        super(WorkerThread, self).__init__()
        self.device = ov.dev
        self.ov = ov
        self.exiting = False
        self.speed = ov.speed
    
    def handle_usb(self, ts, pkt, flags):
        #print("%d,%d" %(ts,flags))
        #a = (ts, pkt, flags)
        #inputpipe.send((ts,flags,pkt))
        #print("sent")
        #rxQueue.put(UsbPacket(ts, flags, pkt))
        #rxQueue.put_nowait(a)
        rxQueue.append((ts,flags,pkt))
    
    def configure_speed(self):
        
        speed = self.ov.speed
        # set to non-drive; set FS or HS as requested
        if speed == "hs":
            self.device.ulpiregs.func_ctl.wr(0x48)
            self.device.rxcsniff.service.highspeed = True
        elif speed == "fs":
            self.device.ulpiregs.func_ctl.wr(0x49)
            self.device.rxcsniff.service.highspeed = False
        elif speed == "ls":
            self.device.ulpiregs.func_ctl.wr(0x4a)
            self.device.rxcsniff.service.highspeed = False
        else:
            assert 0,"Invalid Speed"
    
    def run(self):
        if self.device is None or not self.ov.isopen:
            print("Not open")
            return
            
        self.configure_speed()
        
        rxQueue.clear()
        
        if check_ulpi_clk(self.device):
            return


        self.device.rxcsniff.service.handlers = [self.handle_usb]
        timeout = 0
        elapsed_time = 0
        try:
            self.device.regs.CSTREAM_CFG.wr(1)
            while True:
                if timeout and elapsed_time > timeout:
                    break
                
                time.sleep(0.5)
                if not event_loop.empty():
                    callback = event_loop.get()
                    if callback is None:
                        break
                elapsed_time = elapsed_time + 1
        
        finally:
            self.device.regs.CSTREAM_CFG.wr(0)
        
    def stop(self):
        event_loop.put(None)
        self.wait()


    
    
def main():

    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", "-p", type=lambda x: zipfile.ZipFile(x, 'r'), 
            default=os.getenv('OV_PKG'))
    ap.add_argument("-l", "--load", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--config-only", "-C", action="store_true")

    # Bind commands
    subparsers = ap.add_subparsers()
    for i in Command.__subclasses__():
        sp = subparsers.add_parser(i.name)
        i.setup_args(sp)
        sp.set_defaults(hdlr=i)

    args = ap.parse_args()


    dev = LibOV.OVDevice(mapfile=args.pkg.open('map.txt', 'r'), verbose=args.verbose)

    err = dev.open(bitstream=args.pkg.open('ov3.bit', 'r') if args.load else None)

    if err:
        if err == -4:
            print("USB: Unable to find device")
            return 1
        print("USB: Error opening device (1)\n")
        print(err)

    if not dev.isLoaded():
        print("FPGA not loaded, forcing reload")
        dev.close()

        err = dev.open(bitstream=args.pkg.open('ov3.bit','r'))

    if err:
        print("USB: Error opening device (2)\n")
        return 1


    if args.config_only:
        return

    dev.dev.write(LibOV.FTDI_INTERFACE_A, b'\x00' * 512, async=False)

    try:
        if hasattr(args, 'hdlr'):
            args.hdlr.go(dev, args)
    finally:
        dev.close()

if  __name__ == "__main__":
#    yappi.start()
    main()
#    yappi.print_stats()

