import os
import time
import xbmc
import xbmcaddon
import xbmcvfs

monitor = xbmc.Monitor()
for _ in range(120):
    try:
        folder = xbmcvfs.translatePath(xbmcaddon.Addon('plugin.video.webshare.available').getAddonInfo('path'))
        if os.path.isfile(os.path.join(folder, 'tracking.py')):
            import maintenance
            maintenance.service()
            break
    except Exception:
        pass
    if monitor.waitForAbort(0.5):
        break
