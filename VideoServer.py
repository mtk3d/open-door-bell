from __future__ import division

from twisted.internet import reactor, protocol, stdio
from twisted.protocols import basic

import io
import sys

from PIL import Image
from PIL import ImageOps
from PIL import ImageFilter
from PIL import ImageChops
from Config import Config

from datetime import datetime
import logging

def log(msg):
    tnow = datetime.now()
    logging.info('%s: %s' % (tnow.isoformat(), msg))

def setupLogging():
    logFormatter = logging.Formatter("%(message)s")
    rootLogger = logging.getLogger()
    rootLogger.setLevel(logging.DEBUG)

    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(logFormatter)
    rootLogger.addHandler(consoleHandler)

class ProcessInput(basic.LineReceiver):
    # This seemingly unused line is necessary to over-ride the delimiter
    # property of basic.LineReceiver which by default is '\r\n'. Do not
    # remove this!
    from os import linesep as delimiter

    def __init__(self, factory):
        self.factory = factory

    def lineReceived(self, line):
        log('line recd: %s' % line)
        if line == 'reset':
            log('resetting motion detection service')
            self.factory.reset()

class JpegStreamReaderFactory(protocol.Factory):
    def __init__(self):
        self.protocol = JpegStreamReaderForMotion
        self.reset()

    def reset(self):
        self.config = Config()

class JpegStreamReaderForMotion(protocol.Protocol):
    DETECTION_THRESHOLD = 0.01

    def __init__(self):
        self.data = ''
        self.motionDetected = False
        self.motionSustained = False
        self.prevImage = None
        self.imgcounter = 0

    def processImage(self, im):
        self.data = ''


    def processChunk(self, data):
        if not data:
            return

        idx = data.find(b'\xff\xd8\xff')
        data = data[idx:]

        stream = io.BytesIO(data)
        img = Image.open(stream)
        self.processImage(img)
        self.imgcounter += 1

    def dataReceived(self, data):
        self.data += data
        chunks = self.data.split('--spionisto\r\n')

        for chunk in chunks[:-1]:
            self.processChunk(chunk)

        self.data = chunks[-1]

def startServer():
    print 'Starting...'

    factory = JpegStreamReaderFactory()

    stdio.StandardIO(ProcessInput(factory))

    reactor.listenTCP(9998, factory)

    print 'MOTION_DETECTOR_READY'
    log('printed ready signal')
    sys.stdout.flush()

    reactor.run()

if __name__ == "__main__":
    setupLogging()
    log('Starting main method of motion detection')
    try:
        startServer()
    except:  # noqa: E722 (OK to use bare except)
        logging.exception("startServer() threw exception")
