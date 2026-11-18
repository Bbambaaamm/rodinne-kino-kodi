"""Run family services and apply pending installed releases when Kodi is idle."""
import os
import time
import xbmc

import maintenance as m
from updates import Updater, addon_version


def main():
    changes = m.read_json(os.path.join(m.PROFILE, 'changes.json'))
    if not changes.get('applied') or changes.get('rolled_back'):
        return
    monitor = xbmc.Monitor()
    heartbeat = m.HOME.getProperty('Family.Service.Heartbeat')
    if heartbeat and time.time() - float(heartbeat) < 5:
        if m.HOME.getProperty('Family.Service.Version') == m.VERSION:
            return
        # Older releases also started a script outside Kodi's service manager.
        m.HOME.setProperty('Family.Service.Stop', 'true')
        for _ in range(50):
            if not m.HOME.getProperty('Family.Service.Heartbeat'):
                break
            if monitor.waitForAbort(.2):
                return
        else:
            return
        m.HOME.clearProperty('Family.Service.Stop')
    updater = Updater()
    from default import backup
    if updater.ready():
        updater.apply(backup)
        return
    if addon_version(m.PROVIDER):
        m.service(updater)
    else:
        while not monitor.abortRequested() and updater.pending() and not updater.ready():
            if monitor.waitForAbort(1):
                return
    if not monitor.abortRequested():
        updater.apply(backup)


if __name__ == '__main__':
    main()
