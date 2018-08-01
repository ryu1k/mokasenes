#! /usr/bin/python
# -*- coding: utf-8 -*-

import fcntl
import httplib
import json
import os
import Queue
import re
import serial, signal, smbus, socket, sys
import threading, time, traceback
import urllib, urllib2
import weakref

import RPi.GPIO as GPIO

class CONF:
    APP_LOCKFILE = "/tmp/.senseapp.py.lock"

    IFPORT = 58888

    SHUTDOWN_SYSTEM = True
    SHUTDOWN_SYSTEM_CMD = "setsid shutdown_after_5sec.sh &"

    BLINK_LED_ON_DATA = False

    SLACK_NOTIFY_TICK_SEC_TEMP = 60 * 30
    SLACK_NOTIFY_TICK_SEC_BATT = 60 * 60 * 24 * 7
    pass


try:
    import private
    CONF.SLACK_API_URL = private.SLACK_API_URL
except:
    print "Copy private_tp.py to private.py and update it. exit."
    sys.exit(1)
    pass


# trace
_exlog_proc = None
def _trace_entity(msg):
    sys.stderr.write( msg )
    sys.stderr.flush()
    if _exlog_proc:
        _exlog_proc(msg)
        pass
    return 

_tra = lambda *v : _trace_entity( "".join([
            time.strftime("%d.%H%M%S."),     
            "%03d" % (time.time() * 1000 % 1000),
            " : " + str(v)+"\n" ]) )
_tr  = _tra
_trx = _tra


########################################################################
# Worker loop
#  - uart を読む
#  - gpio を読んでアクション
class DeviceControl(threading.Thread):
    """LED 状態などの読み取り、制御
    - led   : LED on/off
    - power : shutdown, restart
    """
    UART_WAIT_TICK = 0.1
    FLUENTD = ("127.0.0.1", 24330)
    
    def __init__(self, app):
        threading.Thread.__init__(self)
        self.daemon = True

        self.app = weakref.ref(app)
        self.uart = UARTReader(self)
        self.gpio = GPIOCtl(self)
        self.lcd = LCD()
        self.slack = SlackTempNotify()
        self.fluentd = FluentdTCP(self.FLUENTD)
        self.keep_running = True
        return

    def stop(self):
        self.fluentd.stop()
        self.keep_running = False
        return

    def run(self):
        self.fluentd.start()

        #                  1234567890123456
        self.lcd.write(0, "SENSEAPP awaked")
        self.lcd.write(1, "@"+get_self_ip_addr())
        self.blink()
        while self.keep_running:
            self.uart.wait_and_read(self.UART_WAIT_TICK)
            self.gpio.read()
            self.slack.on_time()
            continue

        self.blink()
        #                  1234567890123456
        self.lcd.write(1, "SENSEAPP closed")
        self.fluentd.join()
        return

    def blink(self):
        for i in xrange(30):
            self.gpio.led( i % 2)
            time.sleep(0.1)
            continue
        self.gpio.led(False)
        return

    def on_trigger_reset(self):
        """GPIO detect press of reset"""
        _tra("on_trigger_reset")
        #                  1234567890123456
        self.lcd.write(0, "Bye!  Remove PWR")
        self.lcd.write(1, "after ACT is off")
        self.lcd.freeze()
        self.app().on_reset()
        return

    def on_mode(self):
        """GPIO detect press of reset short. mode change."""
        _tra("on_trigger_mode")
        CONF.BLINK_LED_ON_DATA = not CONF.BLINK_LED_ON_DATA
        #                  1234567890123456
        self.lcd.write(0, "LED on data %s" % (CONF.BLINK_LED_ON_DATA and "ON" or "OFF"))
        return

    def on_data(self, data):
        try:
            if CONF.BLINK_LED_ON_DATA:
                self.gpio.led_timer(2)
                pass
            self.disp_lcd(data)
            self.slack.update(data)
            self.fluentd.put(data)
        except Exception, e:
            _tra( "on except", str(e), traceback.format_exc() )
            pass
        return

    _disp_lcd_fmt = "%d>%6.2f'C %5s"
    #                1234567890123456
    #                N>-12.34'C 11:12
    def disp_lcd(self, data):
        sid = data.get("id")
        if sid not in [1, 2]:
            return

        line = sid -1
        temp = data.get("temp", -99.99)
        hourmin = time_to_hourmin_str( data.get("stamp", 0) )

        text = self._disp_lcd_fmt % (sid, temp, hourmin)
        _trx("lcd", line, text, data)
        self.lcd.write(line, text)
        return

    pass # of class




"""
Python 2.7.3 (default, Mar 18 2014, 05:13:23)
[GCC 4.6.3] on linux2
Type "help", "copyright", "credits" or "license" for more information.
>>> import RPi
>>> import RPi.GPIO as GPIO
>>> GPIO.setmode(GPIO.BOARD)
>>> GPIO.setup(22, GPIO.OUT)
>>> GPIO.output(22, True)
>>> GPIO.output(22, False)
>>> GPIO.output(22, True)
>>> GPIO.output(22, False)
>>> GPIO.output(22, True)
>>> GPIO.output(22, False)
"""
class GPIOCtl(object):
    """GPIO のモニタリング、制御
    - スイッチのモニタ
    - LED の制御
    - LCD の制御

    pin# は GPIO# ではなく、物理 pin#
    """

    # raspi generic
    PINS_I2C = [ 3, 5 ]
    PINS_SPI = [ 19, 21, 23, 24, 26 ]
    PINS_PWM = [ 12 ]
    PINS_VALID = [
        7, 11, 13, 15, 16, 18, 22 ]
    
    # app specific
    PIN_OUT_LED  = 22 # GPIO25
    PIN_IN_RESET = 7  # GPIO4

    def __init__(self, master):
        GPIO.setmode(GPIO.BOARD)
        GPIO.setup(self.PIN_OUT_LED,  GPIO.OUT)
        GPIO.setup(self.PIN_IN_RESET, GPIO.IN, pull_up_down=GPIO.PUD_DOWN) # default up.

        self.in_reset    = Histeresis(nhistory=50, dbg_id="reset_sw") # need pressed 5 sec
        self.press_2sec  = Histeresis(nhistory=20, dbg_id="press_2sec") # need pressed 1 sec
        self.short_reset = Histeresis(nhistory=10, dbg_id="short_sw") # need pressed 1 sec
        self.master = weakref.ref(master)
        self.ledcnt = 0 # if plus, led will be on on any input
        return
    
    def __del__(self):
        self.led(False)
        return

    def read(self):
        raw = GPIO.input( self.PIN_IN_RESET ) and 1 or 0

        # 5 sec: going to shutdown
        if self.in_reset.set(raw) and self.in_reset.val():
            self.master().on_trigger_reset()
            pass

        # 2 sec: notify shutdown.
        if self.press_2sec.set(raw): # histeresis value changed.
            if self.press_2sec.val(): # to true
                self.lcd_write(0, "BEGIN SHUTDOWN")
            else:                 #0123456789abcdef
                self.lcd_write(0, "SHUTDOWN CANCEL")
                pass
            pass
        # 1 sec: change configuration
        if self.short_reset.set(raw) and self.short_reset.val():
            "short reset changed and True"
            self.master().on_mode()
            pass

        # _tra("gpio", raw, self.in_reset.val() )
        self.led( raw )
        return

    def lcd_write(self, line, msg):
        return self.master().lcd.write(line, msg)

    def led(self, on_off):
        if self.ledcnt >= 0:
            self.ledcnt -= 1
            on_off = 1
            pass
        GPIO.output(self.PIN_OUT_LED, on_off)
        return

    def led_timer(self, num):
        self.ledcnt += num
        self.led( 1 )
        return

    pass # of class

class Histeresis(object):
    def __init__(self, init_val=0, nhistory=3, dbg_id="anonymous"):
        self._val = init_val
        self.nhist = nhistory
        self.dbg_id = dbg_id
        self.hist = []
        return

    def reset(self, init_val=0):
        self.hist = [init_val]
        self._val = init_val
        return

    def val(self):
        return self._val

    def set(self, val):
        "@retval= True:value chanegd. False: value not changed."
        self.hist.insert(0, val)
        self.hist = self.hist[:self.nhist]

        diffval = [ v for v in self.hist if v != val]
        # _tra(val, self.hist, diffval)
        # empty diffval == self.hist have only same value.
        if not diffval and val != self._val:
            self._on_val_update(val, self._val)
            self._val = val
            return True            
        return False
            
    def _on_val_update(self, new, prev):
        _tra("on_val_update(%s) : %d -> %d" % (self.dbg_id, prev, new) )
        return

    pass # of class

    

class UARTReader(object):
    # cat /dev/ttyAMA0 out.
    #
    # |::ts=314687
    # | 
    # |::rc=80000000:lq=108:ct=FD9C:ed=81007822:id=0:ba=3060:a1=1280:a2=0701:te=1950
    # | 
    # |::ts=314688

    def __init__(self, master, path="/dev/ttyAMA0"):
        self.master = weakref.ref(master)
        self.path = path
        self.ser = serial.Serial(
            port=path,
            baudrate=115200,
            parity=serial.PARITY_NONE,
            bytesize=serial.EIGHTBITS,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.034)

        self.carry = ""
        return

    def wait_and_read(self, timeout_sec=0.1):
        begin = time.time()
        while True:
            rest = begin + timeout_sec - time.time()
            if rest <= 0:
                break

            data = self.ser.readline()
            if not data:
                # _trx("no data")
                continue
            # _trx("on line. '%s'" % data)
            self._process_line(data)
            continue
        return

    # ::rc=80000000:lq=120:ct=02C9:ed=81007772:id=2:ba=3000:a1=1251:a2=0822:te=1581
    _PROCESS_LINE_RE_TS  = re.compile("::ts=[0-9]*")
    _PROCESS_LINE_RE_MSG = re.compile(".*:id=([0-9-]+):ba=([0-9-]+):a1=([0-9-]+):a2=([0-9-]+):te=([0-9-]+)")
    def _process_line(self, line):
        if self._PROCESS_LINE_RE_TS.match(line):
            self._on_timestamp()
            return
        m = self._PROCESS_LINE_RE_MSG.match(line)
        if m:
            _trx("on data line. '%s'" % line)
            self._on_data(m)
            return

        _tra("Unknown line", line)
        return


    def _on_timestamp(self):
        # _tra("on timestamp")
        self.timestamp = time.time()
        return

    def _on_data(self, m):
        try:
            d = { "id"  : int(m.group(1)),
                  "batt": int(m.group(2)) / 1000.0,
                  "a1"  : int(m.group(3)),
                  "a2"  : int(m.group(4)),
                  "temp": int(m.group(5)) / 100.0,
                  "stamp": time.time(),
                  "node": 0,
              }
        except:
            _tra("on except", m.group(0))
            return
        _trx("on_data", d)
        self.master().on_data(d)
        return

    pass # of class

########################################################################
# LCD : AQM1602
########################################################################
# http://akizukidenshi.com/catalog/g/gK-08896/
# 
# Raspi 標準の i2c ヘッダピンを利用すると、動作が安定しない問題がある。
#   http://wbbwbb.blog83.fc2.com/blog-entry-242.html
#
# 回避策として、I2C を raspi の標準 **ではない** GPIO 23, 24で動作させ、
# 液晶モジュール側でプルアップする。
#   http://www.neko.ne.jp/~freewing/raspberry_pi/raspberry_pi_3_gpio_enable_i2c_3/
#   ./utils/boot/config.txt の dtoverlay=i2c-gpio
#
# 下記にあるようにジャンパをショート
#   http://akizukidenshi.com/download/ds/xiamen/AQM1602_rev2.pdf 
#
# smbus.SMBus(3) としてアクセスする。
# 
"""
d1 = [ 0x38, 0x39, 0x14, 0x75, 0x56, 0x6c ]; bus.write_i2c_block_data( 0x3e, 0x00, d1 ); time.sleep(0.3); d2 = [ 0x0f, 0x38, 0x01 ]; bus.write_i2c_block_data( 0x3e, 0x00, d2 )
>>> d1 = [ 0x38, 0x39, 0x14, 0x75, 0x56, 0x6c ]; bus.write_i2c_block_data( 0x3e, 0x00, d1 ); time.sleep(0.3); d2 = [ 0x0c, 0x38, 0x01 ]; bus.write_i2c_block_data( 0x3e, 0x00, d2 )
>>> bus.write_i2c_block_data( 0x3e, 0x40, [ 0x52, 0x61, 0x73, 0x70, 0x62, 0x69, 0x61, 0x6e ] )

to line 2
i2cset -y 3 0x3e 0x00 0x38 0xc0 0x38 i

"""
class LCD(object):
    CHARMAP = {
        " ": 0x20,
        "!": 0x21,
        "#": 0x23,
        "-": 0x2d,
        ".": 0x2e,
        "/": 0x2f,
        "0": 0x30,
        "1": 0x31,
        "2": 0x32,
        "3": 0x33,
        "4": 0x34,
        "5": 0x35,
        "6": 0x36,
        "7": 0x37,
        "8": 0x38,
        "9": 0x39,
        ":": 0x3a,
        ">": 0x3e,
        "@": 0x40,
        "A": 0x41,
        "B": 0x42,
        "C": 0x43,
        "D": 0x44,
        "E": 0x45,
        "F": 0x46,
        "G": 0x47,
        "H": 0x48,
        "I": 0x49,
        "J": 0x4a,
        "K": 0x4b,
        "L": 0x4c,
        "M": 0x4d,
        "N": 0x4e,
        "O": 0x4f,
        "P": 0x50,
        "Q": 0x51,
        "R": 0x52,
        "S": 0x53,
        "T": 0x54,
        "U": 0x55,
        "V": 0x56,
        "W": 0x57,
        "X": 0x58,
        "Y": 0x59,
        "Z": 0x5a,
        "a": 0x61,
        "b": 0x62,
        "c": 0x63,
        "d": 0x64,
        "e": 0x65,
        "f": 0x66,
        "g": 0x67,
        "h": 0x68,
        "i": 0x69,
        "j": 0x6a,
        "k": 0x6b,
        "l": 0x6c,
        "m": 0x6d,
        "n": 0x6e,
        "o": 0x6f,
        "p": 0x70,
        "q": 0x71,
        "r": 0x72,
        "s": 0x73,
        "t": 0x74,
        "u": 0x75,
        "v": 0x76,
        "w": 0x77,
        "x": 0x78,
        "y": 0x79,
        "z": 0x7a,
        "'": 0xdf,
    }
    SPACE = 0x20
    SHARP = 0x23
    FALLBACK = SPACE

    WIDTH = 16
    BLANK_LINE = [SPACE] * WIDTH

    TICK = 0.001
    def __init__(self):
        self.freezed = False # if true, not allow update.
        self.bus = smbus.SMBus(3) # Use 3rd i2c bus.
        self.fb = {
            0: self.BLANK_LINE,
            1: self.BLANK_LINE,
        }
        self._devinit()
        return

    def __del__(self):
        self.bus.close()
        return

    def _devinit(self):
        # 0x38:to sp-mode, 0x39: 0x14, 0x75:contrast... 0x56: 0x6c
        self.bus.write_i2c_block_data( 0x3e, 0x00, [ 0x38, 0x39, 0x14, 0x75, 0x56, 0x6c ] )
        time.sleep(0.3);
        # 0x0c:cursor 0x38:leave sp-mode, 0x01:clear
        self.bus.write_i2c_block_data( 0x3e, 0x00, [ 0x0c, 0x38, 0x01 ] )
        self._tick()
        self.write(0, "-"*16)
        self.write(1, "-"*16)
        # self.write(1, "12345")
        # self.clear()
        # self.write(1, "/////")
        return

    def _tick(self):
        time.sleep( self.TICK )
        return

    def clear(self):
        if self.freezed:
            return
        self.write(0, self.BLANK_LINE)
        self.write(1, self.BLANK_LINE)
        return

    def freeze(self, is_freeze=True):
        self.freezed = is_freeze
        return

    def write(self, line, msg):
        """
        line : 0, 1
        msg  : must be in chars above. 0 to 16 chars. (01234567890abcdef)

        bus.write_i2c_block_data( 0x3e, 0x40, [ 0x52, 0x61, 0x73, 0x70, 0x62, 0x69, 0x61, 0x6e ] )
        """
        if self.freezed:
            return

        if line != 0:
            line = 1

        # encode text.
        mapped = [ self.CHARMAP.get(c, self.FALLBACK) for c in msg ]
        self.fb[line] = (mapped + self.BLANK_LINE)[:16]

        # clear once
        self._clear_dev()

        # render
        for l in [0, 1]:
            self._set_line(l)
            self._tick()
            self.bus.write_i2c_block_data( 0x3e, 0x40, self.fb[l] )
            self._tick()
            continue
        return

    def _set_line(self, line):
        lkey = 0x00 if line == 0 else 0xc0
        # _trx(line, lkey)
        self.bus.write_i2c_block_data( 0x3e, 0x00, [0x38, lkey, 0x38] )
        return

    def _clear_dev(self):
        self.bus.write_i2c_block_data( 0x3e, 0x00, [0x01] )
        self._tick()
        return


    pass


########################################################################
# Slack
########################################################################
class SlackTempNotify(object):
    URL = CONF.SLACK_API_URL

    def __init__(self):
        self.tick_temp = TickGen(CONF.SLACK_NOTIFY_TICK_SEC_TEMP, 0)
        self.tick_batt = TickGen(CONF.SLACK_NOTIFY_TICK_SEC_BATT, 0)
        self.data = {}
        return

    def on_time(self):
        if self.tick_temp.is_period():
            self.send_temp()

        if self.tick_batt.is_period():
            self.send_batt()
        return

    def update(self, new):
        sid = new.get("id", 0)
        data = self.data.get(sid, {})

        new_temp  = "%5.2f" % new.get("temp", 0.0)
        data_temp = data.get("temp", "--.--")

        need_notify = new_temp != data_temp

        # update data anyway.
        data.update( {
            "temp": new_temp,
            "batt": "%4.2f" % new.get("batt", 0),
            "stamp": time.strftime("%Y/%m/%d %H:%M", time.localtime(new.get("stamp", 0))),
        })
        self.data[sid] = data

        # notify if temp changes.
        if need_notify:
            # self.post(sid, "%s 'C" % data["temp"] )
            # self.send_temp()
            pass
        return

    def send_batt(self):
        self.post(1, "Battery : %s V, %s V --- (%s, %s)" % (
            self.data.get(1, {}).get("batt", "-.--"),
            self.data.get(2, {}).get("batt", "-.--"),
            self.data.get(1, {}).get("stamp", "--.--"),
            self.data.get(2, {}).get("stamp", "--.--"),
        ))
        return

    def send_temp(self):
        self.post(1, "Temp : %s 'C, %s 'C --- (%s, %s)" % (
            self.data.get(1, {}).get("temp", "--.--"),
            self.data.get(2, {}).get("temp", "--.--"),
            self.data.get(1, {}).get("stamp", "--.--"),
            self.data.get(2, {}).get("stamp", "--.--"),
        ))
        return

    def post(self, sid, text):
        body = {
            "channel" : "temp-%d" % sid,
            "username": "Sensor",
            "attachments": [
                {
                    "text"  : text,
                }
            ],
        }
        req = urllib2.Request(self.URL)
        req.add_header("Content-Type", "application/json")
        res = urllib2.urlopen(req, json.dumps(body)).read()
    pass


########################################################################
# Fluentd
########################################################################
class FluentdTCP(threading.Thread):
    def __init__(self, peer_tuple, conn_timeout=3, conn_retry_interval=10, control_tick=0.3):
        threading.Thread.__init__(self)
        self.daemon = True
        self.keep_running = True

        self.queue = Queue.Queue()

        self.peer = peer_tuple
        self.sock = None

        self.TICK = control_tick
        self.timeout = conn_timeout
        self.retry_tick = TickGen( conn_retry_interval, 0)

        return

    def put(self, data):
        try:
            self.queue.put(data, block=False)
        except Queue.Full:
            _tr("FluentdTCP: queue is full. discard it. l=%d" % self.queue.qsize())
            self.put(data)
            pass
        return

    def stop(self):
        self.keep_running = False
        return

    def run(self):
        while self.keep_running:
            # sock not exists. try connect.
            if not self.sock:
                if not self.retry_tick.is_period():
                    self._discard()
                    self._wait()
                    continue
                self._try_connect()
                continue

            # sock exists. try send.
            self._try_send()
            self._wait()
            continue
        return

    def _wait(self):
        time.sleep( self.TICK )
        return

    def _discard(self):
        if not self.queue.qsize():
            return
        try:
            _tr("FluentdTCP : queue discard. l=%d" % self.queue.qsize())
            while self.queue.get(block=False):
                continue
        except Queue.Empty:
            pass
        return

    def _try_connect(self):
        try:
            self.sock = socket.create_connection( self.peer, self.timeout)
            self.sock.settimeout(1)
            _tr("FluentdTCP: connected. peer=%s" % str(self.peer))
        except socket.error as e:
            _tr("FluentdTCP: connection failed. e=%s, peer=%s" % (str(e), str(self.peer)))
            pass
        return

    def _try_send(self):
        while True:
            # get from queue
            if not self.queue.qsize():
                return # no item
            try:
                item = self.queue.get(block=False)
            except Queue.Empty:
                return # no item. (strange...)

            # stringize
            try:
                stringized = json.dumps( item )
            except:
                _tr("FluentdTCP: stringize failed. (%s)" % str(item))
                continue # drop this item and continue.

            # send
            try:
                l = len(stringized)
                sent = self.sock.send( stringized )
                if l == sent:
                    continue # OK to send.
                _tr("FluentdTCP : failed to send all. %d/%d" % (sent/l))
            except Exception as e:
                _tr("FluentdTCP : exception on send. (%s)" % str(e))
                pass

            # send error handling
            _tr("FluentdTCP : close current socket.")
            try:
                self.sock.close()
            except:
                _tr(" exception in close")
                pass
            self.sock = None
            return
        return

    pass # of class


########################################################################
# Utility class and methods
########################################################################
class TickGen(object):
    def __init__(self, tick, last=None):
        self.tick = tick
        self.last = time.time() if last==None else last
        return

    def is_period(self):
        now = time.time()
        elapsed = now - self.last

        if elapsed < self.tick:
            return False

        # It's now!!
        self.last = now
        return True
    pass


class SystemMutex(object):
    def __init__(self, path):
        self.path = path
        self.file = None
        return

    def owner(self):
        try:
            return open(self.path).read()
        except:
            pass
        return ""

    def lock(self):
        if self.file:
            return True # aleady locked.

        # ensure lockfile
        if not os.access(self.path, os.R_OK):
            try:
                f = open(self.path, "w+")
                f.write(".")
                f.close()
            except:
                pass
            pass

        self.file = open(self.path, "r+")
        try:
            fcntl.lockf(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.file.seek(0)
            self.file.write("pid=%d" % os.getpid())
            self.file.flush()
            return True
        except IOError: # can not take lock.
            pass
        self.file = None
        return False
        
    def unlock(self):
        if not self.file:
            return
        try:
            fcntl.lockf(self.file.fileno(), fcntl.LOCK_UN)
        except:
            pass
        self.file = None
        return 

    pass # of class


########################################################################
# The Main
########################################################################
class MainApp(object):
    STOP_SIGNALS = [ 
        signal.SIGHUP, signal.SIGUSR2, signal.SIGINT, signal.SIGTERM
    ]
    IGNORE_SIGNALS = [ signal.SIGPIPE ]

    def __init__(self):
        global _exlog_proc
        _trx("pre mutex")
        self.mutex = SystemMutex( CONF.APP_LOCKFILE )
        _trx("post mutex")
        self.dev = DeviceControl(self)
        self.keep_running = True
        _trx("post devinit")

        sigproc = lambda n, f: self.on_signal(n, f)
        [ signal.signal(s, sigproc) for s in self.STOP_SIGNALS ]
        [ signal.signal(s, sigproc) for s in self.IGNORE_SIGNALS ]

        # loggers
        self.slack = SlackTempNotify()
        try:
            pass
            # self.logger = HTTPLogger()
            # _exlog_proc = self.logger.write
        except:
            _tra("failed to open LogFifo")
            pass
        return

    def __del__(self):
        global _exlog_proc
        _tra("leave...")
        _exlog_proc = None
        return

    def start(self):
        _tra("entry")
        if not self.mutex.lock():
            _tra("failed to take lock. '%s' seems running" % self.mutex.owner())
            return False

        # start main task thread.
        self.dev.start()

        # on start actions
        self.on_start()

        while self.keep_running:
            time.sleep(0.5)
            continue

        _tra("start to join")
        self.dev.join()
        _tra("join completed")
        return

    def on_start(self):
        self.do_notify("Sensing system starts now. @%s" % get_self_ip_addr())
        return

    def on_reset(self):
        self.do_notify("On reset. going to stop.")
        self.stop()
        return


    def on_signal(self, signum, frame):
        if signum in self.IGNORE_SIGNALS:
            _tr(" on signal %d. ignore." % signum)
            return
        self.dev.lcd.write(1, "ON SIGNAL %d"  % signum)
        self.do_notify("on signal (%s). going to stop app. Not stop System." % str(signum))
        CONF.SHUTDOWN_SYSTEM = False
        self.stop()
        return

    def stop(self):
        self.dev.stop()
        self.keep_running = False
        if CONF.SHUTDOWN_SYSTEM:
            self.do_notify("system shutdown begin...")
            os.system( CONF.SHUTDOWN_SYSTEM_CMD )
            pass
        return

    def do_notify(self, msg):
        _tra(msg)
        self.slack.post(1, str(msg))
        return

    pass # of class

    
########################################################################
# simple utility methods
def get_self_ip_addr():
    try:
        return os.popen("/bin/hostname -I").read().split("\n")[0].strip()
    except:
        pass
    return "-"

def time_to_hourmin_str(unix_time):
    timetuple = time.localtime(unix_time)
    hour   = timetuple[3]
    minute = timetuple[4]
    return "%02d:%02d" % (hour, minute)

"""
Python 2.7.3 (default, Mar 18 2014, 05:13:23)
[GCC 4.6.3] on linux2
Type "help", "copyright", "credits" or "license" for more information.
>>> import RPi
>>> import RPi.GPIO as GPIO
>>> GPIO.setmode(GPIO.BOARD)
>>> GPIO.setup(22, GPIO.OUT)
>>> GPIO.output(22, True)
>>> GPIO.output(22, False)
>>> GPIO.output(22, True)
>>> GPIO.output(22, False)
>>> GPIO.output(22, True)
>>> GPIO.output(22, False)
>>>
[1]+  停止                  python
root@raspsense01:/home/ryu1# vigr

fcntl = open(".db.lock", "a+")
>>> fcntl.flock( f.fileno(), fcntl.LOCK_UN )
>>> fcntl.flock( f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB )
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
IOError: [Errno 11] Resource temporarily unavailable
"""

def _test_slack():
    SlackTempNotify().post(1, "by _test_slack()")
    return

def _test_rpc():
    server = RPCServer(None, None)
    server.start()
    time.sleep(600)
    _tra("call shutdown.")
    server.server.shutdown()
    _tra("shutdown begin")
    server.join()
    _tra("joined. completed")
    return

def _test_gpio():
    app = MainApp()
    dev = DeviceControl(app)
    dev.start()
    while True: time.sleep(300)
    return


def _start_app():
    _trx("Pre MainApp Create")
    app = MainApp()
    _trx("Post MainApp Create")
    app.start()
    return


def main():
    _start_app()
    return

if __name__ == "__main__":
    main()
    pass



