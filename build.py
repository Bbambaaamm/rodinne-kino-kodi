"""Build reproducible Kodi ZIPs and the public add-on index from addons/."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parent
ADDONS = ROOT / 'addons'
DIST = ROOT / 'dist'
PROVIDER = 'plugin.video.webshare.available'
INSTALLER = 'script.michal.family.repair'
REPOSITORY = 'repository.rodinne.kino'
STATIC_SUFFIXES = {'.py', '.xml', '.json', '.po', '.png'}


def source_files(addon):
    files = {}
    for path in sorted((ADDONS / addon).rglob('*')):
        if not path.is_file() or path.suffix not in STATIC_SUFFIXES or '__pycache__' in path.parts:
            continue
        data = path.read_bytes()
        if path.suffix == '.py':
            compile(data, str(path), 'exec')
        elif path.suffix == '.xml':
            ET.fromstring(data)
        elif path.suffix == '.json':
            json.loads(data)
        files[path.relative_to(ADDONS / addon).as_posix()] = data
    files['LICENSE'] = (ROOT / 'LICENSE').read_bytes()
    return files


def make_zip(addon, files):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as archive:
        for relative, content in sorted(files.items()):
            info = ZipInfo(f'{addon}/{relative}')
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    result = buffer.getvalue()
    with ZipFile(BytesIO(result)) as archive:
        assert archive.testzip() is None
        assert archive.read(f'{addon}/addon.xml') == files['addon.xml']
    return result


def write_addon(addon, files):
    metadata = ET.fromstring(files['addon.xml'])
    assert metadata.get('id') == addon
    version = metadata.attrib['version']
    target = DIST / addon / f'{addon}-{version}.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    archive = make_zip(addon, files)
    target.write_bytes(archive)
    target.with_suffix('.zip.sha256').write_text(sha256(archive).hexdigest() + '\n', encoding='ascii', newline='\n')
    print(target.relative_to(ROOT).as_posix())
    return metadata


def main():
    provider = source_files(PROVIDER)
    installer = source_files(INSTALLER)
    repository_files = source_files(REPOSITORY)
    repository_data = make_zip(REPOSITORY, repository_files)
    installer['resources/repository.zip'] = repository_data
    version = ET.fromstring(provider['addon.xml']).attrib['version']
    provider_data = make_zip(PROVIDER, provider)
    installer[f'resources/provider-{version}.zip'] = provider_data
    installer['resources/manifest.json'] = json.dumps({
        'provider_version': version,
        'repository_sha256': sha256(repository_data).hexdigest(),
        'provider_sha256': sha256(provider_data).hexdigest(),
        'provider_files': sorted(provider),
    }).encode('utf-8')
    release = ET.fromstring(installer['addon.xml']).attrib['version']
    host = 'resources/search-host.xml'
    installer[host] = installer[host].replace(b'<window',
        ('<!-- Rodinné kino ' + release + ' -->\n<window').encode('utf-8'), 1)

    index = ET.Element('addons')
    index.append(write_addon(INSTALLER, installer))
    repository = write_addon(REPOSITORY, repository_files)
    index.append(repository)
    ET.indent(index, space='  ')
    metadata = ET.tostring(index, encoding='utf-8', xml_declaration=True)
    (DIST / 'addons.xml').write_bytes(metadata)
    (DIST / 'addons.xml.sha256').write_text(sha256(metadata).hexdigest() + '\n', encoding='ascii', newline='\n')

    # Kodi's HTTP directory parser needs matching relative link and label text.
    # Publish only the small repository ZIP in the installation source.
    site = ROOT / 'docs'
    site.mkdir(exist_ok=True)
    filename = f'{REPOSITORY}-{repository.attrib["version"]}.zip'
    archive = (DIST / REPOSITORY / filename).read_bytes()
    (site / filename).write_bytes(archive)
    (site / 'index.html').write_text(f'''<!doctype html>
<html lang="cs">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Rodinné kino pro Kodi</title></head>
<body>
<h1>Rodinné kino pro Kodi</h1>
<p>Instalační zdroj pro Kodi 21 Omega.</p>
<pre><a href="{filename}">{filename}</a> {len(archive)} B</pre>
<p>Vyber tento ZIP v Kodi přes Doplňky → Instalovat ze souboru ZIP.</p>
<p>Potom otevři Instalovat z repozitáře → Rodinné kino → Programové doplňky → Rodinné kino – instalace a servis.</p>
<p><a href="https://github.com/Bbambaaamm/rodinne-kino-kodi#instalace">Návod k instalaci</a></p>
</body>
</html>
''', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
