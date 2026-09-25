#!/usr/bin/env python3
"""直连 dl.google.com 安装 Android SDK 组件。

runner 镜像自带的 sdkmanager 在部分镜像版本上会以
"Warning: Failed to find package 'tools'" 退出（AGP 与 setup-android 都会因此失败），
这里改为按 repository2-3.xml 里的官方归档直连下载并校验 sha1 后解包，
不依赖 sdkmanager，也不依赖它的许可交互。zip 内的顶层目录名按包类型修正：
build-tools 的 zip 顶层是内部版本号目录，必须改成请求的版本号目录名。
"""
import argparse
import hashlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = 'https://dl.google.com/android/repository/'
LICENSES = {
    'android-sdk-license': [
        '8933bad161af4178b1185d1a37fbf41ea5269c55',
        'd56f5187479451eabf01fb78af6dfcb131a6481e',
        '24333f8a63b6825ea9c5514f83c2829b004d1fee',
    ],
    'android-sdk-preview-license': ['84831b9409646a918e30573bab4c9c91346d8abd'],
    'android-ndk-license': ['33b6a2b64607f11b759f320ef9dff4ae5c47d97a'],
}


def fetch(url, timeout=600):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith('.zip'):
        unzip = shutil.which('unzip')
        if unzip:
            # 用 unzip 而不是 zipfile：SDK/NDK 归档里带符号链接，
            # zipfile.extractall 会把链接写成普通文本文件。
            subprocess.run([unzip, '-q', '-o', str(archive), '-d', str(destination)], check=True)
        else:
            with zipfile.ZipFile(archive) as zipped:
                zipped.extractall(destination)
    else:
        with tarfile.open(archive) as tar:
            tar.extractall(destination)
    entries = list(destination.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--package', action='append', default=[])
    parser.add_argument('--repository', default=REPO + 'repository2-3.xml')
    args = parser.parse_args()
    args.sdk.mkdir(parents=True, exist_ok=True)

    xml = fetch(args.repository).decode('utf-8', 'replace')
    blocks = {m.group(1): m.group(2)
              for m in re.finditer(r'<remotePackage path="([^"]+)">(.*?)</remotePackage>', xml, re.S)}

    for package in args.package:
        if package not in blocks:
            raise SystemExit('仓库里没有这个包：' + package)
        chosen = None
        for archive in re.finditer(r'<archive>(.*?)</archive>', blocks[package], re.S):
            body = archive.group(1)
            host = re.search(r'<host-os>([^<]+)</host-os>', body)
            if host and host.group(1) != 'linux':
                continue
            chosen = (re.search(r'<url>([^<]+)</url>', body).group(1),
                      int(re.search(r'<size>(\d+)</size>', body).group(1)),
                      re.search(r'<checksum[^>]*>([0-9a-f]+)</checksum>', body).group(1))
            break
        if not chosen:
            raise SystemExit('没有可用归档：' + package)
        url, size, sha1 = chosen
        kind, name = package.split(';', 1)
        print('==> %s <= %s (%d bytes)' % (package, url, size), flush=True)
        data = fetch(REPO + url)
        if len(data) != size:
            raise SystemExit('下载大小不符：%s（%d != %d）' % (url, len(data), size))
        if hashlib.sha1(data).hexdigest() != sha1:
            raise SystemExit('sha1 校验失败：' + url)
        temporary = Path(tempfile.mkdtemp())
        archive = temporary / url
        archive.write_bytes(data)
        extracted = extract(archive, temporary / 'x')

        if kind == 'platforms':
            base = args.sdk / 'platforms'
            base.mkdir(parents=True, exist_ok=True)
            real = base / extracted.name
            if real.exists():
                shutil.rmtree(real)
            shutil.move(str(extracted), str(real))
            # AGP 与 build.sh 可能按 android-37 或 android-37.0 找平台目录，两个别名都建上。
            for alias in (name, name.split('.')[0]):
                if alias == real.name:
                    continue
                link = base / alias
                if link.is_symlink():
                    link.unlink()
                elif link.exists():
                    shutil.rmtree(link)
                link.symlink_to(real.name)
            print('    platform -> %s（别名 %s）' % (real, ', '.join(sorted({name, name.split('.')[0]} - {real.name}))))
        elif kind == 'build-tools':
            target = args.sdk / 'build-tools' / name
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(extracted), str(target))
            print('    build-tools -> %s' % target)
        elif kind == 'ndk':
            target = args.sdk / 'ndk' / name
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(extracted), str(target))
            print('    ndk -> %s' % target)
        else:
            raise SystemExit('不支持的包类型：' + package)
        shutil.rmtree(temporary, ignore_errors=True)

    licenses = args.sdk / 'licenses'
    licenses.mkdir(parents=True, exist_ok=True)
    for name, hashes in LICENSES.items():
        (licenses / name).write_text('\n'.join(hashes) + '\n', encoding='utf-8')
    print('已写入许可文件：' + ', '.join(sorted(LICENSES)))


if __name__ == '__main__':
    main()
