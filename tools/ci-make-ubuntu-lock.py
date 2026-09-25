#!/usr/bin/env python3
"""按当前 Ubuntu 归档重新生成 tools/ubuntu-tools/packages.lock.json。

官方仓库里的锁指向已被归档清理的旧版本 deb（https://ports.ubuntu.com/... 404），
CI 里改用现网版本重建：.deb 由 chroot 内的 apt-get --download-only 取得，
本脚本只把它们登记成 tools/prepare-ubuntu-tools.py 需要的锁格式，
baseStatusSha256 取本次构建的 rootfs，保证与 APK 内置环境一致。
"""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

REQUESTED = ['ca-certificates', 'curl', 'git']
SOURCES = [
    'http://ports.ubuntu.com/ubuntu-ports noble main universe',
    'http://ports.ubuntu.com/ubuntu-ports noble-updates main universe',
    'http://ports.ubuntu.com/ubuntu-ports noble-security main universe',
]


def deb_field(deb, field):
    out = subprocess.run(['dpkg-deb', '-f', str(deb), field],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def parse_uris(path):
    """apt-get --print-uris 的行 → {文件名: pool 相对路径}。"""
    mapping = {}
    if not path or not path.is_file():
        return mapping
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        match = re.match(r"\s*'?(https?://[^'\s]+/ubuntu-ports/)(.+?)'?\s+(\S+)", line)
        if match:
            mapping[match.group(3)] = match.group(2)
    return mapping


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, required=True, help='已下载 .deb 的目录')
    parser.add_argument('--rootfs', type=Path, required=True, help='本次构建的 rootfs')
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--uris', type=Path, default=None)
    parser.add_argument('--distribution', default='noble')
    args = parser.parse_args()

    uris = parse_uris(args.uris)
    rows = []
    for deb in sorted(args.cache.glob('*.deb')):
        name = deb_field(deb, 'Package')
        architecture = deb_field(deb, 'Architecture')
        relative = uris.get(deb.name) or 'pool/main/%s/%s/%s' % (name[0], name, deb.name)
        rows.append({
            'Package': name,
            'Installed-Size': deb_field(deb, 'Installed-Size'),
            'Architecture': architecture,
            'Version': deb_field(deb, 'Version'),
            'Depends': deb_field(deb, 'Depends'),
            'Filename': relative,
            'Size': deb.stat().st_size,
            'SHA256': hashlib.sha256(deb.read_bytes()).hexdigest(),
        })
    if not rows:
        raise SystemExit('缓存目录里没有 .deb：' + str(args.cache))
    if len({row['Package'] for row in rows}) != len(rows):
        raise SystemExit('同一个包出现多次，无法生成锁')

    status = args.rootfs / 'var/lib/dpkg/status'
    base = hashlib.sha256(status.read_bytes()).hexdigest()
    lock = {
        'format': 1,
        'distribution': args.distribution,
        'architecture': 'arm64',
        'requested': REQUESTED,
        'baseStatusSha256': base,
        'sources': SOURCES,
        'packages': rows,
    }
    args.lock.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('lock 行数=%d baseStatusSha256=%s' % (len(rows), base))
    print('包：' + ', '.join(sorted(row['Package'] for row in rows)))


if __name__ == '__main__':
    main()
