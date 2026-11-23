"""Read-only quality measurements against Kodi JSON-RPC on a trusted LAN."""
import argparse
import codecs
import json
import socket
import time
from urllib.parse import urlencode


class RPC:
    def __init__(self, host):
        self.socket = socket.create_connection((host, 9090), timeout=4)
        self.socket.settimeout(20)
        self.decoder = json.JSONDecoder()
        self.utf8 = codecs.getincrementaldecoder('utf8')()
        self.buffer = ''
        self.number = 0

    def call(self, method, params=None):
        self.number += 1
        request = {'jsonrpc': '2.0', 'id': self.number, 'method': method}
        if params is not None:
            request['params'] = params
        self.socket.sendall(json.dumps(request).encode() + b'\n')
        while True:
            self.buffer = self.buffer.lstrip()
            try:
                value, end = self.decoder.raw_decode(self.buffer)
            except ValueError:
                data = self.socket.recv(65536)
                if not data:
                    raise ConnectionError('Kodi disconnected')
                self.buffer += self.utf8.decode(data)
                continue
            self.buffer = self.buffer[end:]
            if value.get('id') == self.number:
                if 'error' in value:
                    raise RuntimeError(value['error'].get('message') or 'Kodi RPC error')
                return value.get('result')

    def close(self):
        self.socket.close()


def plugin_path(**params):
    params.setdefault('infinite', 1)
    params.setdefault('count', 20)
    params['quality_probe'] = time.time_ns()
    return 'plugin://plugin.video.webshare.available/?' + urlencode(params)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', required=True)
    parser.add_argument('--only', action='append', default=[],
                        help='Measure only the named route; repeat for more routes.')
    args = parser.parse_args()
    routes = (
        ('next_episodes', plugin_path(action='list', kind='episode', source='next')),
        ('movie_popular', plugin_path(action='list', kind='movie', source='popular')),
        ('tv_popular', plugin_path(action='list', kind='tv', source='popular')),
        ('movie_genre_comedy', plugin_path(action='list', kind='movie', source='genre_35')),
        ('movie_recommendations', plugin_path(action='list', kind='movie', source='recommendations')),
        ('history', plugin_path(action='personal', kind='both', source='history')),
        ('streaming_services', 'plugin://plugin.video.webshare.available/?action=streaming&view=cards&quality_probe=' + str(time.time_ns())),
    )
    if args.only:
        wanted = set(args.only)
        routes = tuple(row for row in routes if row[0] in wanted)
        unknown = wanted.difference(row[0] for row in routes)
        if unknown:
            parser.error('Unknown route: ' + ', '.join(sorted(unknown)))
    rpc = RPC(args.host)
    report = {'host': args.host, 'measured_at': int(time.time()), 'routes': {}}
    try:
        labels = [
            'Window(Home).Property(Family.Availability.Build)',
            'Window(Home).Property(Family.Paging.Count.list_movie_recommendations)',
            'Window(Home).Property(Family.Paging.CountSchema.list_movie_recommendations)',
        ]
        report['properties'] = rpc.call('XBMC.GetInfoLabels', {'labels': labels}) or {}
        for name, path in routes:
            started = time.monotonic()
            try:
                result = rpc.call('Files.GetDirectory', {
                    'directory': path, 'media': 'files',
                }) or {}
                files = result.get('files') or []
                report['routes'][name] = {
                    'seconds': round(time.monotonic() - started, 3),
                    'items': len(files),
                    'titles': [(row.get('title') or row.get('label') or '')[:100] for row in files[:24]],
                }
            except Exception as exc:
                report['routes'][name] = {
                    'seconds': round(time.monotonic() - started, 3),
                    'error': type(exc).__name__,
                }
    finally:
        rpc.close()
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()

