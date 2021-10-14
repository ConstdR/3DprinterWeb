#!/usr/bin/python
# encoding: utf-8

import argparse
import logging
import configparser
import os, re, glob
import aiohttp_jinja2, asyncio
import jinja2
import tempfile

from aiohttp import web

from pprint import pprint as pp

lg = logging.getLogger(__file__)
args = None
cfg = None
app = None

def main():
    global args, cfg, app

    mydir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(mydir)

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', dest='config', default='config.cfg',
                    help="Config file. Default: config.cfg")
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.config)
    cfg = config['default']

    logging.basicConfig(level=cfg['debug'])

    app = web.Application()
    aiohttp_jinja2.setup(app,loader=jinja2.FileSystemLoader('templates'))
    app.add_routes([
                    web.get('/', index),
                    web.get('/delete', delete_files),
                    web.get('/favicon.ico', favicon),
                    web.get('/start', start_print),
                    web.get('/set', set_usbport),
                    web.get('/kill', kill_print),
                    web.post('/store', store),
                    web.static('/tmp', 'tmp'),
                    web.static('/storage', 'storage'),
                    web.static('/static', 'static'),
                   ])
    app['printer'] = None
    app['usbport'] = None
    web.run_app(app, host=cfg['host'], port=cfg['port'])

async def kill_print(request):
    lg.debug("Killing process")
    app['printer'].kill()
    raise web.HTTPFound(location='/')

async def set_usbport(request):
    lg.debug("Set usbport: %s" % request.query)
    pp(request.query)
    app['usbport'] = request.query['port']
    raise web.HTTPFound(location='/')

async def start_print(request):
    lg.debug("Start print")
    for fn in os.listdir('tmp'):
        file_path = os.path.join('tmp/', fn)
        try:
            if os.path.isfile(file_path) :
                os.remove(file_path)
        except Exception as e:
            lg.error("Failed to remove file %s : %s" % (file_path, e))
    name=request.query['name']
    lg.debug("Printing file: %s" % name)
    (outfd, stdoutfn) = tempfile.mkstemp(prefix=name+'.', suffix='.log.txt', dir='tmp')
    (errfd, stderrfn) = tempfile.mkstemp(prefix=name+'.', suffix='.err.txt', dir='tmp')
    fout = os.fdopen(outfd, "w")
    ferr = os.fdopen(errfd, "w")
    app['printer'] = await asyncio.create_subprocess_exec('./stream.py', '-p', app['usbport'],
                            '-vvvv', 
                            '-f', os.path.join('storage/', name),
                            stdout=fout, stderr=ferr)
    app['printfile'] = name
    app['printerout'] = stdoutfn
    app['printererr'] = stderrfn
    lg.debug("PID: %s stdout: %s stderr: %s" % (app['printer'].pid, stdoutfn, stderrfn))
    raise web.HTTPFound(location='/')

async def delete_files(request):
    lg.debug("Delete files")
    try:
        names=request.query.getall('name')
        for name in names:
            fname = os.path.join('storage/', name)
            try:
                os.remove(fname)
            except Exception as e:
                lg.error("Deleting %s error: %s" % (fname, e))
    except:
        lg.debug("No names to delete")

    raise web.HTTPFound(location='/')

@aiohttp_jinja2.template('stored.html')
async def store(request):
    lg.debug('Store file')
    reader = await request.multipart()
    field = None

    try:
        while True:
            field = await reader.next()
            if not field:
                break
            if field.name == 'gcode':
                filename = field.filename
                if not filename : break
                with open(os.path.join('storage/', filename), 'wb') as f:
                    while True:
                        chunk = await field.read_chunk()
                        if not chunk:
                            break
                        f.write(chunk)
                f.close()
                break
    except Exception as e:
        lg.error("Error: %s" % e)

    raise web.HTTPFound(location='/')
    { 'result': 'Hmm'}

async def favicon(request):
    res = web.FileResponse('static/favicon.ico')
    res.headers['Cache-Control'] = 'max-age=10000'
    return res

async def index(request):
    global app
    lg.debug("Index")
    work = {}
    files = {}
    ports = []
    outfile = None
    errfile = None
    output = None
    logging = None
    for f in glob.glob('/dev/ttyUSB*'):
        sel = None
        if not app['usbport']: app['usbport'] = f
        if app['usbport'] == f: sel = True
        ports.append({ 'name':f, 'selected':sel})
    if len(ports) == 0:
        app['usbport'] = None
    lg.debug("Ports: %s" % ports)

    loglst = glob.glob('tmp/*log.txt')
    if len(loglst): outfile = loglst[0]
    lg.debug("loglst: %s" % loglst)
    errlst = glob.glob('tmp/*err.txt')
    if len(errlst): errfile = errlst[0]

    for f in os.listdir('storage'):
        try:
            stat = os.stat(os.path.join('storage/', f))
            files[f] = {'size':stat.st_size }
        except:
            lg.error("Skip %s, %s" % (f, e))
    if app['printer']:
        if app['printer'].returncode is not None:
            app['printer'] = None
        else:
            work['pid'] = app['printer'].pid
            work['state'] = last_line(app['printerout'])
            ptail = await asyncio.create_subprocess_exec('tail', 
                            app['printererr'],
                            stdout=asyncio.subprocess.PIPE)
            ( logging, stderr )  = await ptail.communicate()
            logging = logging.decode('utf-8')
            ptail = await asyncio.create_subprocess_exec('tail',
                            app['printerout'],
                            stdout=asyncio.subprocess.PIPE)
            ( output, stderr )  = await ptail.communicate()
            output = output.decode('utf-8')

    lg.debug("usbport: %s" % app['usbport'])
    response = aiohttp_jinja2.render_template('index.html',
                                              request,
                       { 'ports':ports, 'files':files, 'worker':work,
                         'outfile':outfile, 'errfile':errfile,
                         'output':output, 'logging':logging,
                         'app':app})
    if app['printer'] :
        response.headers['Refresh'] = '5'

    return response

def last_line(inputfile):
    last_line = ''
    with open(inputfile, 'rb') as f:
        try:
            f.seek(-2, os.SEEK_END)
            while f.read(1) != b'\n':
                f.seek(-2, os.SEEK_CUR)
            last_line = f.readline().decode()
        except:
            pass

    return last_line

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Interrupted')
        sys.exit(0)

# vim: ai ts=4 sts=4 et sw=4 ft=python
