import time
import os
from pathlib import Path
import json
import threading

import gi
gi.require_version('AppStream', '1.0')
from gi.repository import GLib, GObject

from . import _apt
from . import _flatpak
from ._flatpak import FlatpakRemoteInfo
from .pkgInfo import FlatpakPkgInfo, AptPkgInfo
from .misc import print_timing

SYS_CACHE_PATH = "/var/cache/mintinstall/pkginfo.json"
USER_CACHE_PATH = os.path.join(GLib.get_user_cache_dir(), "mintinstall", "pkginfo.json")

MAX_AGE = 7 * (60 * 60 * 24) # days

class CacheLoadingException(Exception):
    '''Thrown when there was an issue loading the pickled package set'''

class JsonObject(object):
    def __init__(self, pkginfo_cache, section_lists, flatpak_remote_infos):
        super(JsonObject, self).__init__()

        self.pkginfo_cache = pkginfo_cache
        self.section_lists = section_lists
        self.flatpak_remote_infos = flatpak_remote_infos

    @classmethod
    def from_json(cls, json_data: dict):
        pkgcache_dict = {}
        for key in json_data["pkginfo_cache"].keys():
            pkginfo_data = json_data["pkginfo_cache"][key]

            if pkginfo_data["pkg_hash"].startswith("a"):
                pkgcache_dict[key] = AptPkgInfo.from_json(pkginfo_data)
            else:
                pkgcache_dict[key] = FlatpakPkgInfo.from_json(pkginfo_data)

        remotes_dict = {}
        for key in json_data["flatpak_remote_infos"].keys():
            remote_data = json_data["flatpak_remote_infos"][key]
            remotes_dict[key] = FlatpakRemoteInfo.from_json(remote_data)

        return cls(pkgcache_dict,
                   json_data["section_lists"],
                   remotes_dict)

    def to_json(self):
        return self.__dict__

class PkgCache(object):
    STATUS_EMPTY = 0
    STATUS_OK = 1

    @print_timing
    def __init__(self, have_flatpak=False):
        super(PkgCache, self).__init__()

        self.status = self.STATUS_EMPTY
        self.have_flatpak = have_flatpak

        self._items = {}
        self._item_lock = threading.Lock()

        try:
            cache, sections, flatpak_remote_infos = self._load_cache()
        except CacheLoadingException:
            cache = {}
            sections = {}
            flatpak_remote_infos = {}

        if len(cache) > 0:
            self.status = self.STATUS_OK
        else:
            self.status = self.STATUS_EMPTY

        self._items = cache
        self.sections = sections
        self.flatpak_remote_infos = flatpak_remote_infos

    def keys(self):
        with self._item_lock:
            return self._items.keys()

    def values(self):
        with self._item_lock:
            return self._items.values()

    def __getitem__(self, key):
        with self._item_lock:
            return self._items[key]

    def __setitem__(self, key, value):
        with self._item_lock:
            self._items[key] = value

    def __delitem__(self, key):
        with self._item_lock:
            del self._items[key]

    def __contains__(self, pkg_hash):
        with self._item_lock:
            return pkg_hash in self._items

    def __len__(self):
        with self._item_lock:
            return len(self._items)

    def __iter__(self):
        with self._item_lock:
            for pkg_hash in self._items:
                yield self[pkg_hash]
            return

    def _generate_cache(self):
        cache = {}
        sections = {}
        flatpak_remote_infos = {}

        if self.have_flatpak:
            cache, flatpak_remote_infos = _flatpak.process_full_flatpak_installation(cache)

        cache, sections = _apt.process_full_apt_cache(cache)

        return cache, sections, flatpak_remote_infos

    def _get_best_load_path(self):
        try:
            sys_mtime = os.path.getmtime(SYS_CACHE_PATH)

            if ((time.time() - MAX_AGE) > sys_mtime) or not os.access(SYS_CACHE_PATH, os.R_OK):
                print("Installer: System pkgcache too old or not accessible, skipping")
                sys_mtime = 0
        except OSError:
            sys_mtime = 0

        try:
            user_mtime = os.path.getmtime(USER_CACHE_PATH)

            if (time.time() - MAX_AGE) > user_mtime:
                print("Installer: User pkgcache too old, skipping")
                user_mtime = 0
        except OSError:
            user_mtime = 0

        # If neither exist, return None, and a new cache will be generated
        if sys_mtime == 0 and user_mtime == 0:
            return None

        most_recent = None

        # Select the most recent
        if sys_mtime > user_mtime:
            most_recent = SYS_CACHE_PATH
            print("Installer: System pkgcache is most recent, using it.")
        else:
            most_recent = USER_CACHE_PATH
            print("Installer: User pkgcache is most recent, using it.")

        return Path(most_recent)

    @print_timing
    def _load_cache(self):
        """
        The cache pickle file can be in either a system or user location,
        depending on how the cache was generated.  If it exists in both places, take the
        most recent one.  If it's more than MAX_AGE, generate a new one anyhow.
        """

        cache = None
        sections = None
        flatpak_remote_infos = None

        path = self._get_best_load_path()

        if path is None:
            raise CacheLoadingException
        try:
            with path.open(mode='r', encoding="utf8") as f:
                json_obj = JsonObject.from_json(json.load(f))
                cache = json_obj.pkginfo_cache
                sections = json_obj.section_lists
                flatpak_remote_infos = json_obj.flatpak_remote_infos
        except Exception as e:
            print("Installer: Error loading pkginfo cache:", e)
            cache = None

        if cache == None:
            raise CacheLoadingException

        return cache, sections, flatpak_remote_infos

    def _get_best_save_path(self):
        best_path = None

        # Prefer the system location, as all users can access it
        try:
            path = Path(SYS_CACHE_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        except PermissionError:
            try:
                path = Path(USER_CACHE_PATH)
                path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                path = None
        finally:
            best_path = path

        return best_path

    def _save_cache(self, to_be_json):
        path = self._get_best_save_path()

        FlatpakPkgInfo.__module__ = "installer.pkgInfo"
        AptPkgInfo.__module__ = "installer.pkgInfo"
        FlatpakRemoteInfo.__module__ = "installer._flatpak"

        try:
            with path.open(mode='w', encoding="utf8") as f:
                json.dump(to_be_json, f, default=lambda o: o.to_json(), indent=4)
        except Exception as e:
            print("Installer: Could not save cache:", str(e))

    def _new_cache_common(self):
        print("Installer: Generating new pkgcache")
        cache, sections, flatpak_remote_infos = self._generate_cache()

        if len(cache) > 0:
            self._save_cache(JsonObject(cache, sections, flatpak_remote_infos))

        with self._item_lock:
            self._items = cache
            self.sections = sections
            self.flatpak_remote_infos = flatpak_remote_infos

        if len(cache) == 0:
            self.status = self.STATUS_EMPTY
        else:
            self.status = self.STATUS_OK

    def _generate_cache_thread(self, callback=None):
        self._new_cache_common()

        if callback != None:
            GObject.idle_add(callback)

    def get_subset_of_type(self, pkg_type):
        with self._item_lock:
            return {k: v for k, v in self._items.items() if k.startswith(pkg_type)}

    def force_new_cache_async(self, idle_callback=None):
        thread = threading.Thread(target=self._generate_cache_thread,
                                  kwargs={"callback" : idle_callback})
        thread.start()

    def force_new_cache(self):
        self._new_cache_common()

    def find_pkginfo(self, string, pkg_type=None):
        if pkg_type in (None, "a"):
            pkginfo = _apt.find_pkginfo(self, string)

            if pkginfo != None:
                return pkginfo

        if self.have_flatpak:
            if pkg_type in (None, "f"):
                pkginfo = _flatpak.find_pkginfo(self, string)

                if pkginfo != None:
                    return pkginfo

        return None

    def _get_manually_installed_debs(self):
        """
        Generate list of manually installed Debian package.
        Requires a package list provided by the installer.
            Currently knows only Ubiquity's /var/log/installer/initial-status.gz
        """
        installer_log = "/var/log/installer/initial-status.gz"
        if not os.path.isfile(installer_log):
            return None
        import gzip
        try:
            installer_log = gzip.open(installer_log, "r").read().decode('utf-8').splitlines()
        except Exception as e:
            # There are a number of different exceptions here, but there's only one response
            print("Could not get initial installed packages list (check /var/log/installer/initial-status.gz): %s" % str(e))
            return None
        initial_status = [x[9:] for x in installer_log if x.startswith("Package: ")]
        if not initial_status:
            return None
        from . import _apt
        pkgcache = [x[4:] for x in self.get_subset_of_type("a")]
        current_status = ["apt:%s" % pkg for pkg in _apt.get_apt_cache() if
            (pkg.installed and
            not pkg.is_auto_installed and
            pkg.shortname not in initial_status and
            pkg.shortname in pkgcache)]
        return current_status

    def get_manually_installed_packages(self):
        """ Get list of all manually installed packages (apt and flatpak) """
        installed_packages = None
        installed_packages_apt = self._get_manually_installed_debs()
        if installed_packages_apt:
            installed_packages = installed_packages_apt
            installed_packages += [x for x in self.get_subset_of_type("f")]
        return installed_packages

