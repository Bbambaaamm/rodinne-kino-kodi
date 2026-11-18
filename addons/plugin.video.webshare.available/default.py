import family
import sys

if __name__ == '__main__':
    try:
        family.begin_invocation(sys.argv)
        family.route()
        family.deliver_pending_playback()
    except Exception as exc:
        title, message = family.classify_error(exc)
        family.HOME.setProperty('Family.LastErrorClass', type(exc).__name__)
        if family.HANDLE >= 0 and family.PARAMS.get('action') in ('card', 'play', 'search'):
            family.xbmcplugin.setResolvedUrl(family.HANDLE, False, family.xbmcgui.ListItem())
        family.xbmcgui.Dialog().ok(title, message)
