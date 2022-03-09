#!/usr/bin/python3 -u
# encoding: utf-8
"""
G-code streamer
"""
import sys, os, serial, time, re
import argparse
import logging

lg = logging.getLogger(__file__)
args = None
gfile= None
ser = None
totalcount = 0
start_time = None 

def main():
    global args
    parser = argparse.ArgumentParser()
    parser.add_argument('-p', '--port', dest="port", default='/dev/ttyUSB0', help="Port. default - /dev/ttyUSB0")
    parser.add_argument('-f', '--file', dest="file", required=True, help="G-code file to print")
    parser.add_argument('-v', action='count', default=0, dest="verbose_count", 
                        help="increases log verbosity for each occurence up to 3 times, default - critical")
    parser.add_argument('-l', '--log_file', dest="log_file", help="logging file. default - stderr")

    args = parser.parse_args()

    loggerConfig(level=args.verbose_count, log_file=args.log_file)

    start()
    Dprint()
    finish()

def start():
    global gfile, ser, args, totalcount
    gfile = open(args.file, 'r')
    totalcount = getFullExtrude()
    lg.debug("Using file: %s Filament: %.2f m" % (args.file, totalcount))

    ser = serial.Serial()
    ser.port = args.port
    ser.baudrate = 115200
    ser.dtr = False
    ser.open()
    time.sleep(0.1)
    ser.flushInput()
    time.sleep(0.1)

    lg.debug("Init printer...")
    ser.dtr = True
    # wait until printer ready
    return
    while True:
        out = ser.readline().decode("utf-8").strip()
        lg.debug('Got: %s' % out)
        if out.lower().startswith("init"):
            break

def finish(excode=0):
    global gfile, ser
    gfile.close()
    ser.close()
    hours, rest = divmod( time.time()-start_time, 3600 )
    minutes, seconds = divmod( rest, 60 )
    print( "Finished in {}h {:0>2}m".format( int(hours),int(minutes) ) )
    sys.exit(excode)

def Dprint():
    global gfile, ser, totalcount, start_time
    lg.debug("Starting")
    count = 0
    zcount = 0
    for line in gfile:
        if line.startswith('G1'):
            count += getLineExtrude(line)
            if not start_time:
                start_time = time.time()
            progress = float(count/1000) / totalcount
            runningh, runningm = divmod(time.time()-start_time, 3600)
            speed = float(count/1000) / ( time.time()-start_time )
            if line.startswith("G1 Z"):
                zcount += 1
                if speed > 0 :
                    estimateh, estimatem = divmod(( (1-progress) * totalcount ) / speed, 3600)
                    print("Progress: %.2f %% Z: %s Running: %s h %.0f min Estimate left: %s h %.0f min" %
                        ( progress*100, zcount-2 , int(runningh), round(runningm/60), int(estimateh), round(estimatem/60) ), flush=True)
        try:
            line = line.strip()         # strip EOL
            line = line.split(';')[0]   # strip comments
            if not line.strip():        # skip empty lines
                continue

            lg.debug("Extruder: %.2f m Z: %s Line: %s" % (float(count/1000), zcount, line))

            ser.write( bytes(line + '\n', "utf-8") )
            while True:
                try:
                    out = ser.readline().decode("utf-8").strip()    # blocking
                except Exception as e:
                    lg.error("Bad response %s" % e)
                    continue
                lg.debug('Got: %s' % out)
                if out.lower().startswith("ok"):
                    break
                elif out.startswith("T:"):
                    print("Heating: %s" % out, flush=True)
                elif out.startswith("echo:busy: processing"):
                    pass

        except Exception as e:
            lg.error("Exception interrupt: %s" % e)
            ser.write( bytes("M104 S0\nM140 S0\nM107\nM84\n", "utf-8") )
            finish(1)

def getFullExtrude():
    gfile = open(args.file, 'r')
    extrude = 0
    for line in gfile:
        extrude += getLineExtrude(line)
    extrude = float(extrude/1000)
    gfile.close()
    return (extrude)

def getLineExtrude(ln):
    global lg
    e = 0
    ln=ln.strip()
    if ln.startswith('G1'):
        try:
            e = float(re.findall(r'E(.*)$',ln)[0])
            if e < 0: e = 0
        except Exception as ex:
            pass
    return(e)

def loggerConfig(level=0, log_file=None):
    lg.setLevel({1: 'ERROR', 2: 'WARNING', 3: 'INFO'}.get(level, 'DEBUG') if level else 'CRITICAL')
    try: fh = open(log_file, 'a')
    except: fh = sys.stderr
    ch = logging.StreamHandler(fh)
    formatter = logging.Formatter('%(asctime)s - %(filename)s:%(lineno)d - %(levelname)s - %(msg)s')
    ch.setFormatter(formatter)
    lg.addHandler(ch)
 
if __name__ == '__main__':
    main()

# vim: ai ts=4 sts=4 et sw=4 ft=python
