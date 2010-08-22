# configure these paths:
LOGFILE = '/var/log/pywxtd.log'
PIDFILE = '/var/run/pywxtd.pid'

WX_HOST = ''
WX_PORT = 4001

APRS_HOST = 'rotate.aprs2.net'
APRS_PORT = 14580
APRS_USER = ''
APRS_PASS = ''

CALLSIGN = ''

STATION_TYPE = 'WXT520'
ELEVATION = 750 # meters above sea-level

# error checking:
assert len(WX_HOST) > 0
assert type(WX_PORT) == type(10)
assert len(APRS_HOST) > 0
assert len(APRS_USER) > 0
assert len(CALLSIGN) > 0
