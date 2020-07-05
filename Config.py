import ConfigParser
import os

class Config:
    def __init__(self):
        # self.paramNames = ()

        configPath = self.getConfigFilePath()
        if os.path.isfile(configPath):
            config = self.getConfigParser()
            config.read(configPath)

            for (key, val) in config.items('Main'):
                if hasattr(self, key):
                    setattr(self, key, int(val))

    def getConfigParser(self):
        config = ConfigParser.RawConfigParser()
        # The below option preserves case of the key names. Otherwise, they
        # all get converted to lowercase by default (!)
        config.optionxform = str
        return config

    def getConfigFilePath(self):
        return '/home/pi/sleep_monitor.cfg'

    def write(self):
        config = self.getConfigParser()

        config.add_section('Main')
        for propName in self.paramNames:
            config.set('Main', propName, str(getattr(self, propName)))

        with open(self.getConfigFilePath(), 'wb') as configfile:
            config.write(configfile)

if __name__ == "__main__":
    config = Config()
    for name in config.paramNames:
        print '%s: %s' % (name, getattr(config, name))
