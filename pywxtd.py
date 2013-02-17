#!/usr/bin/env python
"""
Listens to a WXT520 weather station on a network serial port,
parses the ASCII weather data format, builds and submits an
APRS weather packet to the APRS-IS/CWOP.

BSD License and stuff
Copyright 2010 Tom Hayward <tom@tomh.us>
"""


import sys, os, time
from datetime import datetime, timedelta
from apscheduler.scheduler import Scheduler
from socket import *

from settings import *

rain_at_midnight = None

class Log:
    """file like for writes with auto flush after each write
    to ensure that everything is logged, even during an
    unexpected exit."""
    def __init__(self, f):
        self.f = f
    def write(self, s):
        self.f.write(s)
        self.f.flush()

def toMph(speed):
    """Convert to miles/hour"""
    # m/s
    if speed[-1] == 'M':
        return float(speed[:-1]) * 2.23693629
    # km/h
    elif speed[-1] == 'K':
        return float(speed[:-1]) * 0.621371192
    # mph
    elif speed[-1] == 'S':
        return float(speed[:-1]) * 1
    # knots
    elif speed[-1] == 'N':
        return float(speed[:-1]) * 1.15077945
    else:
        return 0

def toFahrenheit(temp):
    """Convert to degrees Fahrenheit"""
    if temp[-1] == 'C':
        return float(temp[:-1]) * (9.0/5.0) + 32
    elif temp[-1] == 'F':
        return float(temp[:-1])

def toHin(rain):
    """Convert to hundreths of an inch"""
    # from mm (M)
    if rain[-1] == 'M':
        return float(rain[:-1]) * 3.93700787

def toPas(pressure):
    """Converts sensor pressure (mb) to sea-level pressure (mb)"""
    # from hPa/millibars
    if pressure[-1] == 'H':
        Pstn = float(pressure[:-1])
    else:
        return None
    return Pstn * pow((1.0 + 0.000084229 * (ELEVATION/pow(Pstn, 0.19028))), 5.2553)

def make_aprs_wx(wind_dir=None, wind_speed=None, wind_gust=None, temperature=None, rain_since_midnight=None, humidity=None, pressure=None):
    """
    Assembles the payload of the APRS weather packet.
    """
    def str_or_dots(number, length):
        """
        If parameter is None, fill space with dots. Else, zero-pad.
        """
        if number is None:
            return '.'*length
        else:
            format_type = {
                'int': 'd',
                'float': '.0f',
            }[type(number).__name__]
            return ''.join(('%0',str(length),format_type)) % number
    return '!4643.80N/11710.14W_%s/%sg%st%sP%sh%sb%s%s' % (
        str_or_dots(wind_dir, 3),
        str_or_dots(wind_speed, 3),
        str_or_dots(wind_gust, 3),
        str_or_dots(temperature, 3),
        str_or_dots(rain_since_midnight, 3),
        str_or_dots(humidity, 2),
        str_or_dots(pressure, 5),
        STATION_TYPE
    )

def send_aprs(host, port, user, passcode, callsign, wx):
    #start the aprs server socket
    s = socket(AF_INET, SOCK_STREAM)
    s.connect((host, port))
    #aprs login
    s.send('user %s pass %s vers KD7LXL-Python 0.1\n' % (user, passcode) )
    s.send('%s>APRS:%s\n' % (callsign, wx))
    s.shutdown(0)
    s.close()

def convert_wxt(d):
    # There's got to be a better way of doing this error checking:
    try:
        wind_dir = int(d['0R1']['Dm'][:3])
    except KeyError:
        wind_dir = None
    try:
        wind_speed = toMph(d['0R1']['Sm'])
    except KeyError:
        wind_speed = None
    try:
        wind_gust = toMph(d['0R1']['Sx'])
    except KeyError:
        wind_gust = None
    try:
        temperature = toFahrenheit(d['0R2']['Ta'])
    except KeyError:
        temperature = None
    try:
        humidity = float(d['0R2']['Ua'][:-1])
    except KeyError:
        humidity = None
    try:
        pressure = toPas(d['0R2']['Pa']) * 10.0
    except KeyError:
        pressure = None
    try:
        rain_since_midnight = float(toHin(d['0R3']['Rc']))
    except (KeyError, TypeError):
        rain_since_midnight = None
    return make_aprs_wx(wind_dir=wind_dir, wind_speed=wind_speed, wind_gust=wind_gust, temperature=temperature, humidity=humidity, pressure=pressure, rain_since_midnight=rain_since_midnight)

def main():
    #setup the schduler
    sched = Scheduler()
    sched.start()

    @sched.cron_schedule(hour='0',minute='0',second='0')
    def reset_rain_counter():
        #start the weather socket
        wx_socket = socket(AF_INET, SOCK_STREAM)
        try:
            wx_socket.connect((WX_HOST, WX_PORT))
        except error, msg:
            print >>sys.stderr, time.strftime("%Y-%m-%d %H:%M:%S"), 'Could not reset rain counter: ', msg
            print >>sys.stderr, time.strftime("%Y-%m-%d %H:%M:%S"), 'Reported rain-since-midnight value is no longer accurate.'
            return False
        wx_file = wx_socket.makefile()
        wx_file.write('0XZRU\r\n')
        wx_socket.shutdown(0)
        wx_socket.close()

    @sched.interval_schedule(minutes=5)
    def post_to_aprs():
        d = {}
        # listen to weather station
        #start the weather socket
        wx_socket = socket(AF_INET, SOCK_STREAM)
        try:
            wx_socket.connect((WX_HOST, WX_PORT))
        except error, msg:
            print >>sys.stderr, time.strftime("%Y-%m-%d %H:%M:%S"), 'Could not open socket: ', msg
            time.sleep(30)
            try:
                #start the weather socket
                wx_socket.connect((WX_HOST, WX_PORT))
            except error, msg:
                print >>sys.stderr, time.strftime("%Y-%m-%d %H:%M:%S"), 'Could not open socket (2nd attempt): ', msg
                return False
        try:
            wx_file = wx_socket.makefile()

            done_time = datetime.now() + timedelta(seconds=10)
            while datetime.now() < done_time:
                try:
                    line = wx_file.readline().rstrip().split(',')
                    key = line.pop(0)
                    d[key] = {}
                    for i in line:
                        i = i.split('=')
                        try:
                            d[key][i[0]] = i[1]
                        except IndexError, msg:
                            print >>sys.stderr, 'IndexError: ', msg, i
                            continue
                except KeyboardInterrupt:
                    break
        except error, msg:
            print >>sys.stderr, time.strftime("%Y-%m-%d %H:%M:%S"), 'Socket Error: ', msg
            wx_socket.close()
            return False

        # post to aprs
        wx = convert_wxt(d)
        print time.strftime("%Y-%m-%d %H:%M:%S"), wx
        send_aprs(APRS_HOST, APRS_PORT, APRS_USER, APRS_PASS, CALLSIGN, wx)

    # run forever
    post_to_aprs()
    while 1:
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            break
    sched.shutdown()

if __name__ == "__main__":
    # do the UNIX double-fork magic, see Stevens' "Advanced
    # Programming in the UNIX Environment" for details (ISBN 0201563177)
    try:
        pid = os.fork()
        if pid > 0:
            # exit first parent
            sys.exit(0)
    except OSError, e:
        print >>sys.stderr, "fork #1 failed: %d (%s)" % (e.errno, e.strerror)
        sys.exit(1)

    # decouple from parent environment
    os.chdir("/")   #don't prevent unmounting....
    os.setsid()
    os.umask(0)

    # do second fork
    try:
        pid = os.fork()
        if pid > 0:
            # exit from second parent, print eventual PID before
            #print "Daemon PID %d" % pid
            open(PIDFILE,'w').write("%d"%pid)
            sys.exit(0)
    except OSError, e:
        print >>sys.stderr, "fork #2 failed: %d (%s)" % (e.errno, e.strerror)
        sys.exit(1)

    # redirect outputs to a logfile
    sys.stdout = sys.stderr = Log(open(LOGFILE, 'a+'))
    # ensure the that the daemon runs a normal user
    os.setegid(999)     #set group first "pywxtd"
    os.seteuid(999)     #set user "pywxtd"
    # start the daemon main loop
    main()