#!/usr/bin/env python
"""
Listens to a WXT520 weather station on a network serial port,
parses the ASCII weather data format, builds and submits an
APRS weather packet to the APRS-IS/CWOP.

BSD License and stuff
Copyright 2010 Tom Hayward <tom@tomh.us> 
"""


import sys, os, time
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

def toPas(Pstn):
    Pstn = float(Pstn)
    # p0 = 1013.25
    # T0 = 288.15
    # g = 9.801
    # Rd = 287.04
    # Gamma = 6.5
    # zstn = ELEVATION
    # return Pstn*(1 + ((p0**0.190284*0.0065/Rd)*(zstn/(Pstn**0.190284))) )**(1/0.190284)
    # No idea if this formula is correct:
    return Pstn * pow((1.0 + 0.000084229 * (ELEVATION/pow(Pstn, 0.19028))), 5.2553)
    # offset for 750m elevation:
    #return Pstn + 86.6816

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
        pressure = toPas(d['0R2']['Pa'][:-1]) * 10.0
    except KeyError:
        pressure = None
    try:
        rain_since_midnight = float(toHin(d['0R3']['Rc'])) - toHin(rain_at_midnight)
    except (KeyError, TypeError):
        rain_since_midnight = None
    return make_aprs_wx(wind_dir=wind_dir, wind_speed=wind_speed, wind_gust=wind_gust, temperature=temperature, humidity=humidity, pressure=pressure, rain_since_midnight=rain_since_midnight)

def main():
    #change to data directory if needed
    #os.chdir("/home/root/scheduler")
    #redirect outputs to a logfile
    #sys.stdout = sys.stderr = Log(open(LOGFILE, 'a+'))
    #ensure the that the daemon runs a normal user
    #os.setegid(103)     #set group first "pydaemon"
    #os.seteuid(103)     #set user "pydaemon"

    #setup the schduler
    sched = Scheduler()
    sched.start()
    
    global rain_at_midnight
    d = {}
    
    @sched.cron_schedule(hour='0',minute='0',second='0')
    def reset_rain_counter():
        global rain_at_midnight
        try:
            rain_at_midnight = d['0R3']['Rc']
        except KeyError:
            rain_at_midnight = None
    
    @sched.interval_schedule(minutes=5)
    def post_to_aprs():
        print convert_wxt(d)
        send_aprs(APRS_HOST, APRS_PORT, APRS_USER, APRS_PASS, CALLSIGN, convert_wxt(d))
    
    #start the weather socket
    wx_socket = socket(AF_INET, SOCK_STREAM)
    wx_socket.connect((WX_HOST, WX_PORT))
    wx_file = wx_socket.makefile()
    
    while True:
        try:
            line = wx_file.readline().rstrip().split(',')
            key = line.pop(0)
            d[key] = {}
            for i in line:
                i = i.split('=')
                d[key][i[0]] = i[1]
        except KeyboardInterrupt:
            break
    sched.shutdown()
    wx_socket.shutdown(0)
    wx_socket.close()
    print convert_wxt(d)

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

    # start the daemon main loop
    main()