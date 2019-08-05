#!/usr/bin/python3
"""
apt_changelog.py

Replacement for apt changelog, can be used both standalone and as a module.

In addition to apt changelog sources, it directly supports also Linux Mint
and Launchpad repositories and will try to retrieve a changelog for packages
from all other debian package sources as well. Most importantly, changelogs
for installed packages are retrieved locally to avoid unnecessary network
activity.

Unlike apt it does not support wildcards for the package name. You get to
check one specific changelog at a time only. I see no value in multi-lookups.

Copyright (c) 2018 gm10

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import fnmatch
import gzip
import lzma
import os
import sys
import tarfile
import tempfile

import requests
from apt.cache import Cache
from apt.debfile import DebPackage

import apt_pkg


class _Package():
    def __init__(self,name:str, fullname:str, architecture:str, version:str,
        source_name:str, source_version:str, uri:str, filename:str, origin:str,
        component:str, downloadable:bool, is_installed:bool, dependencies:list):
        self.name = name
        self.fullname = fullname
        self.architecture = architecture
        self.version = version
        self.source_name = source_name
        self.source_version = source_version
        self.source_version_raw = None
        self.uri = uri
        self.filename = filename
        self.origin = origin
        self.component = component
        self.downloadable = downloadable
        self.is_installed = is_installed
        self.installed_files = list()
        self.dependencies = dependencies

class _AptChangelog():

    def __init__(self, interactive:bool=False):
        self.interactive = interactive

        # constants
        # apt uses MB rather than MiB, so let's stay consistent
        self.MB = 1000 ** 2
        # downloads larger than this require confirmation or fail
        self.max_download_size_default = 1.5 * self.MB
        self.max_download_size = self.max_download_size_default
        max_download_size_msg_template = "\
To retrieve the full changelog, %s MB have to be downloaded.\n%s\
\n\
Proceed with the download?"
        self.max_download_size_msg_lc = max_download_size_msg_template % ("%.1f",
            "Otherwise we will try to retrieve just the last change.\n")
        self.max_download_size_msg = max_download_size_msg_template % ("%.1f","")
        self.max_download_size_msg_unknown = max_download_size_msg_template % ("an unknown amount of", "")

        self.apt_cache = None
        self.apt_cache_date = None
        self.candidate = None

        # get apt's configuration
        apt_pkg.init_config()
        if apt_pkg.config.exists("Acquire::Changelogs::URI::Origin"):
            self.apt_origins = apt_pkg.config.subtree("Acquire::Changelogs::URI::Origin")
        else:
            self.apt_origins = None
        if apt_pkg.config.exists("Dir::Cache::pkgcache"):
            self.apt_cache_path = apt_pkg.config.find_dir("Dir::Cache")
            self.pkgcache = apt_pkg.config.find_file("Dir::Cache::pkgcache")
        else:
            self.apt_cache = "invalid"
        if (self.apt_cache or
            not os.path.isdir(self.apt_cache_path) or
            not os.path.isfile(self.pkgcache)
            ):
            print("E: Invalid APT configuration found, try to run `apt update` first",
                file=sys.stderr)
            self.close(99)

    def get_cache_date(self):
        if os.path.isfile(self.pkgcache):
            return os.path.getmtime(self.pkgcache)
        return None

    def refresh_cache(self):
        cache_date = self.get_cache_date()

        if not self.apt_cache:
            self.apt_cache = Cache()
            self.apt_cache_date = cache_date
        elif cache_date != self.apt_cache_date:
            self.apt_cache.open(None)
            self.apt_cache_date = cache_date

    def drop_cache(self):
        if self.candidate:
            self.candidate = None
        self.apt_cache = None

    def get_changelog(self, pkg_name:str, no_local:bool=False):
        self.refresh_cache()
        self.candidate = self.parse_package_metadata(pkg_name)

        # parse the package's origin
        if not self.candidate.downloadable:
            origin = "local_package"
        elif self.candidate.origin == "linuxmint":
            origin = "linuxmint"
        elif self.candidate.origin.startswith("LP-PPA-"):
            origin = "LP-PPA"
        elif self.apt_origins and self.candidate.origin in self.apt_origins.list():
            origin = "APT"
        else:
            origin = "unsupported"

        # Check for changelog of installed package first
        has_local_changelog = False
        uri = None
        if not no_local and self.candidate.is_installed:
            if _DEBUG: print("Package is installed...")
            uri = self.get_changelog_from_filelist(
                self.candidate.installed_files, local=True)
            # Ubuntu kernel workarounds
            if self.candidate.origin == "Ubuntu":
                if self.candidate.source_name == "linux-signed":
                    uri = uri.replace("linux-image","linux-modules")
                if self.candidate.source_name == "linux-meta":
                    uri = None
            if uri and not os.path.isfile(uri):
                uri = None

        # Do nothing if local changelog exists
        if uri:
            has_local_changelog = True
        # all origins that APT supports
        elif origin == 'APT':
            uri = self.get_apt_changelog_uri(
                self.apt_origins.get(self.candidate.origin))
            r = self.check_url(uri)
            if not r:
                self.exit_on_fail(2)
        # Linux Mint repo
        elif origin == 'linuxmint':
            # Mint repos don't have .debian.tar.xz files, only full packages, so
            # check the package cache first
            base_uri, _ = os.path.split(self.candidate.uri)
            r, uri = self.get_changelog_uri(base_uri)
            if not r:
                # fall back to last change info for the source package
                # Mint's naming scheme seems to be using amd64 unless source
                # is i386 only, we always check amd64 first
                base_uri = "http://packages.linuxmint.com/dev/%s_%s_%s.changes"
                uri = base_uri % (self.candidate.source_name,
                    self.candidate.source_version, "amd64")
                r = self.check_url(uri, False)
                if not r:
                    uri = base_uri % (self.candidate.source_name,
                        self.candidate.source_version, "i386")
                    r = self.check_url(uri, False)
                    if not r:
                        self.exit_on_fail(3)

        # Launchpad PPA
        elif origin == 'LP-PPA':
            ppa_owner, ppa_name, _ = \
                self.candidate.uri.split("ppa.launchpad.net/")[1].split("/", 2)
            base_uri = "http://ppa.launchpad.net/%s/%s/ubuntu/pool/main/{self.source_prefix()}/%s" % (ppa_owner, ppa_name, self.candidate.source_name)
            r, uri = self.get_changelog_uri(base_uri)
            if not r:
                # fall back to last change info only
                uri = "https://launchpad.net/~%s/+archive/ubuntu/%s/+files/%s_%s_source.changes" % (ppa_owner, ppa_name, self.candidate.source_name, self.candidate.source_version)
                r = self.check_url(uri, False)
                if not r:
                    self.exit_on_fail(4)
        # Not supported origin
        elif origin == 'unsupported':
            if _DEBUG: print("Unsupported Package")
            base_uri, _ = os.path.split(self.candidate.uri)
            r, uri = self.get_changelog_uri(base_uri)
            if not r:
                self.exit_on_fail(5)
        # Locally installed package without local changelog or remote
        # source, hope it's cached and contains a changelog
        elif origin == 'local_package':
            uri = self.apt_cache_path + self.candidate.filename
            if not os.path.isfile(uri):
                self.exit_on_fail(6)

        # Changelog downloading, extracting and processing:
        changelog = ""
        # local changelog
        if has_local_changelog and not no_local:
            if _DEBUG: print("Using local changelog:",uri)
            try:
                filename = os.path.basename(uri)
                # determine file type by name/extension
                # as per debian policy 4.4 the encoding must be UTF-8
                # as per policy 12.7 the name must be changelog.Debian.gz or
                # changelog.gz (deprecated)
                if filename.lower().endswith('.gz'):
                    changelog = gzip.open(uri,'r').read().decode('utf-8')
                elif filename.lower().endswith('.xz'):
                    # just in case / future proofing
                    changelog = lzma.open(uri,'r').read().decode('utf-8')
                elif filename.lower() == 'changelog':
                    changelog = open(uri, 'r').read().encode().decode('utf-8')
                else:
                    raise ValueError('Unknown changelog format')
            except Exception as e:
                _generic_exception_handler(e)
                self.exit_on_fail(1)
        # APT-format changelog, download directly
        # - unfortunately this is slow since the servers support no compression
        elif origin == "APT":
            if _DEBUG: print("Downloading: %s (%.2f MB)" % (uri, r.length / self.MB))
            changelog = r.text
            r.close()
        # last change changelog, download directly
        elif uri.endswith('.changes'):
            if _DEBUG: print("Downloading: %s (%.2f MB)" % (uri, r.length / self.MB))
            changes = r.text.split("Changes:")[1].split("Checksums")[0].split("\n")
            r.close()
            for change in changes:
                change = change.strip()
                if change:
                    if change == ".":
                        change = ""
                    changelog += change + "\n"
        # compressed binary source, download and extract changelog
        else:
            source_is_cache = uri.startswith(self.apt_cache_path)
            if _DEBUG: print("Using cached package:" if source_is_cache else
                "Downloading: %s (%.2f MB)" % (uri, r.length / self.MB))
            try:
                if not source_is_cache:
                    # download stream to temporary file
                    tmpFile = tempfile.NamedTemporaryFile(prefix="apt-changelog-")
                    if self.interactive and r.length:
                        # download chunks with progress indicator
                        recv_length = 0
                        blocks = 60
                        for data in r.iter_content(chunk_size=16384):
                            recv_length += len(data)
                            tmpFile.write(data)
                            recv_pct = recv_length / r.length
                            recv_blocks = int(blocks * recv_pct)
                            print("\r[%(progress)s%(spacer)s] %(percentage).1f%%" %
                                {
                                    "progress": "=" * recv_blocks,
                                    "spacer":  " " * (blocks - recv_blocks),
                                    "percentage": recv_pct * 100
                                }, end="", flush=True)
                        # clear progress bar when done
                        print("\r" + " " * (blocks + 10), end="\r", flush=True)
                    else:
                        # no content-length or non-interactive, download in one go
                        # up to the configured max_download_size, ask only when
                        # exceeded
                        r.raw.decode_content = True
                        size = 0
                        size_exceeded = False
                        while True:
                            buf = r.raw.read(16*1024)
                            if not size_exceeded:
                                size += len(buf)
                                if size > self.max_download_size:
                                    if not self.user_confirm(self.max_download_size_msg_unknown):
                                        r.close()
                                        tmpFile.close()
                                        return ""
                                    else:
                                        size_exceeded = True
                            if not buf:
                                break
                            tmpFile.write(buf)
                    r.close()
                    tmpFile.seek(0)
                if uri.endswith(".deb"):
                    # process .deb file
                    if source_is_cache:
                        f = uri
                    else:
                        f = tmpFile.name
                        # We could copy the downloaded .deb files to the apt
                        # cache here but then we'd need to run the script elevated:
                        # shutil.copy(f, self.apt_cache_path + os.path.basename(uri))
                    deb = DebPackage(f)
                    changelog_file = self.get_changelog_from_filelist(deb.filelist)
                    if changelog_file:
                        changelog = deb.data_content(changelog_file)
                        if changelog.startswith('Automatically decompressed:'):
                            changelog = changelog[29:]
                    else:
                        raise ValueError('Malformed Debian package')
                elif uri.endswith(".diff.gz"):
                    # Ubuntu partner repo has .diff.gz files,
                    # we can extract a changelog from that
                    data = gzip.open(tmpFile.name, "r").read().decode('utf-8')
                    additions = data.split("+++")
                    for addition in additions:
                        lines = addition.split("\n")
                        if "/debian/changelog" in lines[0]:
                            for line in lines[2:]:
                                if line.startswith("+"):
                                    changelog += "%s\n" % line[1:]
                                else:
                                    break
                    if not changelog:
                        raise ValueError('No changelog in .diff.gz')
                else:
                    # process .tar.xz file
                    with tarfile.open(fileobj=tmpFile, mode="r:xz") as tar:
                        changelog_file = self.get_changelog_from_filelist(
                            [s.name for s in tar.getmembers() if s.type in (b"0", b"2")])
                        if changelog_file:
                            changelog = tar.extractfile(changelog_file).read().decode()
                        else:
                            raise ValueError('No changelog in source package')
            except Exception as e:
                _generic_exception_handler(e)
                self.exit_on_fail(520)
            if 'tmpFile' in vars():
                try:
                    tmpFile.close()
                except Exception as e:
                    _generic_exception_handler(e)

        # ALL DONE
        return changelog

    def parse_package_metadata(self, pkg_name:str):
        """ Creates the self.candidate object based on package name=version/release

        Wildcard matching is only used for version and release, and only the
        first match is processed.
        """
        # parse =version declaration
        if "=" in pkg_name:
            (pkg_name, pkg_version) = pkg_name.split("=", 1)
            pkg_release = None
        # parse /release declaration (only if no version specified)
        elif "/" in pkg_name:
            (pkg_name, pkg_release) = pkg_name.split("/", 1)
            pkg_version = None
        else:
            pkg_version = None
            pkg_release = None

        # check if pkg_name exists
        # unlike apt no pattern matching, a single exact match only
        if pkg_name in self.apt_cache:
            pkg = self.apt_cache[pkg_name]
        else:
            print("E: Unable to locate package %s" % pkg_name, file=sys.stderr)
            self.close(13)

        # get package data
        _candidate = None
        candidate = None
        if pkg_release or pkg_version:
            match_found = False
            for _pkg in pkg.versions:
                if pkg_version:
                    if fnmatch.fnmatch(_pkg.version, pkg_version):
                        match_found = True
                else:
                    for _origin in _pkg.origins:
                        if fnmatch.fnmatch(_origin.archive, pkg_release):
                            match_found = True
                if match_found:
                    _candidate = _pkg
                    break
            if not match_found:
                if pkg_release:
                    print('E: Release "%s" is unavailable for "%s"' % (pkg_release, pkg.name),
                          file=sys.stderr)
                else:
                    print('E: Version "%s" is unavailable for "%s"' % (pkg_version, pkg.name),
                          file=sys.stderr)
                self.close(14)
        else:
            _candidate = pkg.candidate
        candidate = _Package(
            version = _candidate.version,
            name = _candidate.package.name,
            fullname = None,
            architecture = pkg.architecture,
            source_name = _candidate.source_name,
            source_version = _candidate.source_version,
            uri = _candidate.uri,
            filename = os.path.basename(_candidate.filename),
            origin = _candidate.origins[0].origin,
            component = _candidate.origins[0].component,
            downloadable = _candidate.downloadable,
            is_installed = _candidate.is_installed,
            dependencies = _candidate.dependencies
        )
        if candidate.is_installed:
            candidate.installed_files = pkg.installed_files
        candidate.source_version_raw = candidate.source_version
        if ":" in candidate.source_version:
            candidate.source_version = candidate.source_version.split(":", 1)[1]
        return candidate

    def check_url(self, url:str, check_size:bool=True, stream:bool=True,
        msg:str=None):
        """ True if url can be downloaded and fits size requirements """
        if _DEBUG: print("Checking:", url)
        try:
            _r = requests.get(url, stream=stream, timeout=5)
        except Exception as e:
            _generic_exception_handler(e)
        else:
            if _r:
                if not _r.encoding:
                    _r.encoding = "utf-8"
                length = _r.headers.get("Content-Length")
                if length:
                    _r.length = int(length)
                else:
                    _r.length = 0
                if (not check_size or not
                    (check_size and _r.length > self.max_download_size and not
                    self.user_confirm(
                        (self.max_download_size_msg_lc if not msg else msg) %
                        (_r.length / self.MB))
                    )):
                    return _r
        if '_r' in vars():
            _r.close()
        return False

    @staticmethod
    def close(err:int=0):
        """ Exit """
        sys.exit(err)

    def exit_on_fail(self, err:int=404):
        """ Prints error message and calls self.close() """
        try:
            details = "Changelog unavailable for %s=%s" % (self.candidate.source_name, self.candidate.source_version_raw)
        except AttributeError:
            details = ""
        print("E: Failed to fetch changelog. %s" % details, file=sys.stderr)
        self.close(err)

    @staticmethod
    def strtobool (val):
        val = val.lower()
        if val in ('y', 'yes'):
            return True
        elif val in ('n', 'no'):
            return False
        else:
            raise ValueError("Invalid response value %s" % val)

    def user_confirm(self, q:str):
        """ returns bool (always False in non-interactive mode) """
        if not self.interactive:
            if _DEBUG: print("Maximum size exceeded, skipping in non-interactive mode")
            return False
        print("%s [y/n] " % q, end="")
        while True:
            try:
                response = self.strtobool(input())
                print("")
                return response
            except ValueError:
                print("Invalid response. Try again [y/n]: ", end="")
            except KeyboardInterrupt:
                pass

    def get_deb_or_tar(self, uri_tar:str=None):
        """ Returns request and URI of the preferred source

        The choice is made based on availability and size. If .deb is smaller
        than comparison_trigger_size, or if check_tar is False, then .deb is
        always selected.
        """
        comparison_trigger_size = 50000
        r_deb = self.check_url(self.candidate.uri, False)
        if r_deb:
            if uri_tar and r_deb.length > comparison_trigger_size:
                # try for .tar.xz
                r_tar = self.check_url(uri_tar, False)
                # validate and compare sizes
                if r_tar and r_tar.length < r_deb.length:
                    _r = r_tar
                    r_deb.close()
                else:
                    _r = r_deb
                    if r_tar:
                        r_tar.close()
            else:
                _r = r_deb
            if (not _r.length > self.max_download_size or
                self.user_confirm(self.max_download_size_msg_lc %
                (_r.length / self.MB))
                ):
                return (_r, _r.url)
        return (False, "")

    def get_changelog_from_filelist(self, filelist:list, local:bool=False):
        """ Returns hopefully the correct "changelog" or an empty string.

        We should not need to be searching because the debian policy says it
        must be at debian/changelog for source packages but not all seem to
        adhere to the policy:
        https://www.debian.org/doc/debian-policy/ch-source.html#debian-changelog-debian-changelog

        """
        files = [s for s in filelist if "changelog" in s.lower()]
        if local:
            testpath = "/usr/share/doc/%s/changelog" % self.candidate.name
            for item in files:
                if item.lower().startswith(testpath):
                    return item
        else:
            testpath = "debian/changelog"
            if testpath in files:
                return testpath
            testpath = "recipe/debian/changelog"
            if testpath in files:
                return testpath
            testpath = "usr/share/doc/%s/changelog" % self.candidate.name
            for item in files:
                if item.lower().startswith(testpath):
                    return item
            # no hits in the standard locations, let's try our luck in
            # random locations at the risk of getting the wrong file
            for item in files:
                if os.path.basename(item).lower().startswith("changelog"):
                    return item
        return None

    def get_apt_changelog_uri(self, uri_template:str):
        """ Returns URI based on provided apt changelog URI template.

        Emulates apt's std::string pkgAcqChangelog::URI
        The template must contain the @CHANGEPATH@ variable, which will
        be expanded to
            COMPONENT/SRC/SRCNAME/SRCNAME_SRCVER
        Component is omitted for releases without one (= flat-style
        repositories).
        """
        source_version = self.candidate.source_version

        def get_kernel_version_from_meta_package(pkg):
            for dependency in pkg.dependencies:
                if not dependency.target_versions or not dependency.rawtype == "Depends":
                    if _DEBUG: print("W: Kernel dependency not found:", dependency)
                    return None
                deppkg = dependency.target_versions[0]
                if deppkg.source_name in ("linux", "linux-signed"):
                    return deppkg.source_version
                if deppkg.source_name.startswith("linux-meta"):
                    _pkg = self.parse_package_metadata(str(deppkg))
                    return get_kernel_version_from_meta_package(_pkg)
            return None

        # Ubuntu kernel meta package workaround
        if self.candidate.origin == "Ubuntu" and \
           self.candidate.source_name.startswith("linux-meta"):
            _source_version = get_kernel_version_from_meta_package(self.candidate)
            if _source_version:
                source_version = _source_version
                self.candidate.source_name = "linux"

        # Ubuntu signed kernel workaround
        if self.candidate.origin == "Ubuntu" and \
           self.candidate.source_name == "linux-signed":
            self.candidate.source_name = "linux"

        # XXX:  Debian does not seem to reliably keep changelogs for previous
        #       (kernel) versions, so should we always look for the latest
        #       version instead on Debian? apt does not do this but the
        #       packages.debian.org website shows the latest version in the
        #       selected archive

        # strip epoch
        if ":" in source_version:
            source_version = source_version.split(":", 1)[1]

        # the path is: COMPONENT/SRC/SRCNAME/SRCNAME_SRCVER, e.g.
        #   main/a/apt/apt_1.1 or contrib/liba/libapt/libapt_2.0
        return uri_template.replace('@CHANGEPATH@',
            "%(component)s%(source_prefix)s/%(source_name)s/%(source_name)s_%(source_version)s" %
            {
                "component": self.candidate.component + "/" if \
                    self.candidate.component and \
                    self.candidate.component != "" else "",
                "source_prefix": self.source_prefix(),
                "source_name": self.candidate.source_name,
                "source_version": source_version
            })

    def source_prefix(self, source_name:str=None):
        """ Return prefix used for build repository URL """
        if not source_name:
            source_name = self.candidate.source_name
        return source_name[0] if not source_name.startswith("lib") else \
            source_name[:4]

    def parse_dsc(self, url:str):
        """ Returns filename or None """
        _r = self.check_url(url, False, False)
        if _r:
            target = ""
            lines = _r.text.split("Files:", 1)[1].split(":", 1)[0].split("-----BEGIN", 1)[0].split("\n")
            target = [s.strip() for s in lines if s.strip().lower().endswith('.debian.tar.xz')]
            if not target:
                target = [s.strip() for s in lines if s.strip().lower().endswith('.diff.gz')]
            if not target:
                target = [s.strip() for s in lines if s.strip().lower().endswith('.tar.xz')]
            # don't even test for .tar.gz, it will be too big compared to the .deb
            # if not target:
            #     target = [s.strip() for s in lines if s.strip().lower().endswith('.tar.gz')]
            if target:
                return target[0].split()[-1]
            elif _DEBUG: print(".dsc parse error for", url)
        return None

    def get_changelog_uri(self, base_uri:str):
        """ Tries to find a changelog in files listed in .dsc, locally cached
        packages as well as the remote .deb file

        Returns r and uri
        """
        uri = None
        # XXX:  For APT sources we could just read the apt_pkg.SourceRecords()
        #       directly, if available, which it is not for most users, so
        #       probably not worth it
        target_filename = self.parse_dsc("%s/%s_%s.dsc" % (base_uri, self.candidate.source_name, self.candidate.source_version))
        # get .debian.tar.xz or .diff.gz as a priority as the smallest options
        if (base_uri and target_filename and (
                target_filename.lower().endswith('.debian.tar.xz') or
                target_filename.lower().endswith('.diff.gz')
            )):
            uri = "%s/%s" % (base_uri, target_filename)
            target_filename = None
            r = self.check_url(uri, msg = self.max_download_size_msg)
        else:
            r = None
        if not r:
            # fall back to cached local package
            uri = self.apt_cache_path + self.candidate.filename
            if not os.path.isfile(uri):
                # cache miss, download the full source package or the .deb,
                # depending on size and availability
                if target_filename:
                    uri_tar = "%s/%s" % (base_uri, target_filename)
                else:
                    uri_tar = None
                r, uri = self.get_deb_or_tar(uri_tar)
        return (r, uri)

def _generic_exception_handler(e):
    if _DEBUG:
        import traceback
        print("%s: %s\n" % (e.__class__.__name__, traceback.format_exc()), file=sys.stderr)

def drop_cache():
    """ Drop the apt cache to free up memory. """
    # For some reason this does not free about 11M the first time it is run, and
    # additional 21M (32M total) the second time it runs (if the cache had been
    # opened again in the meantime). All consecutive runs keep those 32M total
    # without additional loss.
    # This only affects the freeing of memory, the maximum memory usage is stable.
    # It's unclear whether this is a python-apt or a python issue.

    if apt_changelog:
        apt_changelog.drop_cache()

def get_changelog(pkg_name:str, interactive:bool=False, output:bool=False,
    paged_output:bool=False, no_local:bool=False, max_download_size:int=0):
    """ Returns changelog for given package name, if any, and if within
        size-restrictions
    """
    changelog = None
    try:
        if not apt_changelog:
            __init__(interactive)
        if int(max_download_size) > 0:
            apt_changelog.max_download_size = int(max_download_size)
        else:
            apt_changelog.max_download_size = apt_changelog.max_download_size_default
        changelog = apt_changelog.get_changelog(pkg_name, no_local)
    except SystemExit:
        if interactive:
            raise
    except KeyboardInterrupt:
        sys.exit(130)
    else:
        if output:
            if not changelog:
                # empty changelog
                apt_changelog.exit_on_fail(7)
            if paged_output:
                try:
                    from pydoc import pager
                    pager(changelog)
                except Exception as e:
                    _generic_exception_handler(e)
                    paged_output = False
            else:
                print(changelog)
    return changelog

def print(*args, **kwargs):
    try:
        return __builtins__.print(*args, **kwargs)
    except:
        pass

def set_debug(value:bool):
    global _DEBUG
    _DEBUG = bool(value)

def __init__(interactive:bool=False):
    """ Instantiate _AptChangelog to global apt_changelog """
    global apt_changelog
    apt_changelog = _AptChangelog(interactive)

_DEBUG = False
apt_changelog = None

if __name__ == "__main__":
    if "--debug" in sys.argv:
        set_debug(True)
        sys.argv.remove("--debug")
    if "--no-local" in sys.argv:
        sys.argv.remove("--no-local")
        _no_local=True
    else:
        _no_local=False
    if len(sys.argv) != 2:
        print("""\
Usage:  apt changelog [options] <package>

Tries to retrieve the changelog of a package and display it through a pager.
By default it displays the changelog for the version that is installed.
However, you can specify the same options as for the install command.

Options:
        --no-local
            Always retrieve changelogs remotely, where possible. This can be
            useful when the locally installed changelog has been truncated.

Changelog lookup may fail for some packages if source repositories
are not enabled""")
        sys.exit(1)
    else:
        isatty = sys.stdin.isatty() and sys.stdout.isatty()
        get_changelog(sys.argv[1], interactive=isatty, output=True,
            paged_output=isatty, no_local=_no_local)
