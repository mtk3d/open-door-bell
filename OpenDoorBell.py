#!/usr/bin/env python

from twisted.internet import reactor, protocol, defer, interfaces
import twisted.internet.error
from twisted.web import server, resource
from twisted.web.static import File
from zope.interface import implementer

import re
from datetime import datetime, timedelta
import os
import json
import subprocess

from ProcessProtocolUtils import spawnNonDaemonProcess, \
        TerminalEchoProcessProtocol
from ZeroConfUtils import startZeroConfServer

from LoggingUtils import log, setupLogging, LoggingProtocol

from Config import Config



def async_sleep(seconds):
    d = defer.Deferred()
    reactor.callLater(seconds, d.callback, seconds)
    return d

class MJpegResource(resource.Resource):
    def __init__(self, queues):
        self.queues = queues

    def setupProducer(self, request):
        producer = JpegProducer(request)
        request.notifyFinish().addErrback(self._responseFailed, producer)
        request.registerProducer(producer, True)

        self.queues.append(producer)

    def _responseFailed(self, err, producer):
        log('connection to client lost')
        producer.stopProducing()

    def render_GET(self, request):
        log('getting new client of image stream')
        request.setHeader("content-type", 'multipart/x-mixed-replace; boundary=--spionisto')

        self.setupProducer(request)
        return server.NOT_DONE_YET

class LatestImageResource(resource.Resource):
    def __init__(self, factory):
        self.factory = factory

    def render_GET(self, request):
        request.setHeader("content-type", 'image/jpeg')
        return self.factory.latestImage

@implementer(interfaces.IPushProducer)
class JpegProducer(object):
    def __init__(self, request):
        self.request = request
        self.isPaused = False
        self.isStopped = False
        self.delayedCall = None

    def cancelCall(self):
        if self.delayedCall:
            self.delayedCall.cancel()
            self.delayedCall = None

    def pauseProducing(self):
        self.isPaused = True
        self.cancelCall()
        # log('producer is requesting to be paused')

    def resetPausedFlag(self):
        self.isPaused = False
        self.delayedCall = None

    def resumeProducing(self):
        # calling self.cancelCall is defensive. We should not really get
        # called with multiple resumeProducing calls without any
        # pauseProducing in the middle.
        self.cancelCall()
        self.delayedCall = reactor.callLater(1, self.resetPausedFlag)
        # log('producer is requesting to be resumed')

    def stopProducing(self):
        self.isPaused = True
        self.isStopped = True
        log('producer is requesting to be stopped')

MJPEG_SEP = '--spionisto\r\n'




class JpegStreamReader(protocol.Protocol):
    def __init__(self):
        self.tnow = None

    def connectionMade(self):
        log('MJPEG Image stream received')
        self.data = ''
        self.tnow = datetime.now()
        self.cumDataLen = 0
        self.cumCalls = 0

    def dataReceived(self, data):
        self.data += data

        chunks = self.data.rsplit(MJPEG_SEP, 1)

        dataToSend = ''
        if len(chunks) == 2:
            subchunks = chunks[0].rsplit(MJPEG_SEP, 1)

            lastchunk = subchunks[-1]
            idx = lastchunk.find(b'\xff\xd8\xff')
            self.factory.latestImage = lastchunk[idx:]

            dataToSend = chunks[0] + MJPEG_SEP

        self.data = chunks[-1]

        self.cumDataLen += len(dataToSend)
        self.cumCalls += 1

        for producer in self.factory.queues:
            if (not producer.isPaused):
                producer.request.write(dataToSend)

        if datetime.now() - self.tnow > timedelta(seconds=1):
            # log('Wrote %d bytes in the last second (%d cals)' % (self.cumDataLen, self.cumCalls))
            self.tnow = datetime.now()
            self.cumDataLen = 0
            self.cumCalls = 0


class PingResource(resource.Resource):
    def render_GET(self, request):
        request.setHeader("content-type", 'application/json')
        request.setHeader("Access-Control-Allow-Origin", '*')

        status = {'status': 'ready'}
        return json.dumps(status)

class GetConfigResource(resource.Resource):
    def __init__(self, app):
        self.app = app

    def render_GET(self, request):
        request.setHeader("content-type", 'application/json')

        status = {}
        for paramName in self.app.config.paramNames:
            status[paramName] = getattr(self.app.config, paramName)

        return json.dumps(status)


class UpdateConfigResource(resource.Resource):
    def __init__(self, app):
        self.app = app

    def render_GET(self, request):
        log('Got request to change parameters to %s' % request.args)

        for paramName in self.app.config.paramNames:
            # a bit of defensive coding. We really should not be getting
            # some random data here.
            if paramName in request.args:
                paramVal = int(request.args[paramName][0])
                log('setting %s to %d' % (paramName, paramVal))
                setattr(self.app.config, paramName, paramVal)

        self.app.resetAfterConfigUpdate()

        request.setHeader("content-type", 'application/json')
        status = {'status': 'done'}
        return json.dumps(status)


class Logger:
    def __init__(self, app):
        self.lastLogTime = datetime.min
        self.logFile = None

        reactor.addSystemEventTrigger('before', 'shutdown', self.closeLastLogFile)

    @defer.inlineCallbacks
    def run(self):
        while True:
            yield async_sleep(2)
            tnow = datetime.now()

    def closeLastLogFile(self):
        if self.logFile is not None:
            self.logFile.close()
            newname = self.logFile.name.replace('.inprogress', '')
            os.rename(self.logFile.name, newname)
            self.logFile = None

    def createNewLogFile(self, tstr):
        bufsize = 1  # line buffering

        if not os.path.isdir('../sleep_logs'):
            os.mkdir('../sleep_logs')

        self.logFile = open('../sleep_logs/%s.log.inprogress' % tstr, 'w', bufsize)

    def printToFile(self, logStr):
        self.logFile.write(logStr + '\n')


class Video(TerminalEchoProcessProtocol):
    def __init__(self, app):
        TerminalEchoProcessProtocol.__init__(self)
        self.app = app

    def outLineReceived(self, line):
        self.app.startGstreamerVideo()

    def errLineReceived(self, line):
        log('Video: error: %s' % line)

    def reset(self):
        self.transport.write('reset\n')


class OpenDoorBell:
    def startGstreamerVideo(self):

        videosrc = '/dev/video0'

        try:
            out = subprocess.check_output(['v4l2-ctl', '--list-devices'])
        except subprocess.CalledProcessError as e:
            out = e.output

        lines = out.splitlines()
        for (idx, line) in enumerate(lines):
            if 'bcm2835' in line:
                nextline = lines[idx + 1]
                videosrc = nextline.strip()

        spawnNonDaemonProcess(reactor, LoggingProtocol('gstream-video'), '/bin/sh',
                              ['sh', 'gstream_video.sh', videosrc])

        log('Started gstreamer video using device %s' % videosrc)

    def __init__(self):
        queues = []

        self.config = Config()
        self.reactor = reactor
     
        self.video = Video(self)
        spawnNonDaemonProcess(reactor, self.video, 'python',
                ['python', 'VideoServer.py'])
        log('Started Video process')

        logger = Logger(self)
        logger.run()
        log('Started logging')

        factory = protocol.Factory()
        factory.protocol = JpegStreamReader
        factory.queues = queues
        factory.latestImage = None
        reactor.listenTCP(9999, factory)
        log('Started listening for MJPEG stream')

        root = File('web')
        root.putChild('stream.mjpeg', MJpegResource(queues))
        root.putChild('latest.jpeg', LatestImageResource(factory))
        root.putChild('ping', PingResource())
        root.putChild('getConfig', GetConfigResource(self))
        root.putChild('updateConfig', UpdateConfigResource(self))

        site = server.Site(root)
        PORT = 80
        BACKUP_PORT = 8080

        portUsed = PORT
        try:
            reactor.listenTCP(PORT, site)
            log('Started webserver at port %d' % PORT)
        except twisted.internet.error.CannotListenError:
            portUsed = BACKUP_PORT
            reactor.listenTCP(BACKUP_PORT, site)
            log('Started webserver at port %d' % BACKUP_PORT)

        startZeroConfServer(portUsed)

        reactor.run()

    def resetAfterConfigUpdate(self):
        log('Updated config')
        self.config.write()

if __name__ == "__main__":
    import logging
    setupLogging()
    log('Starting main method of sleep monitor')
    try:
        app = OpenDoorBell()
    except:
        logging.exception("main() threw exception")
