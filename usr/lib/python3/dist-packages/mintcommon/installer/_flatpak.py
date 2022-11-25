import time
import threading
import math
from pathlib import Path
import subprocess
import requests
import tempfile
import os

import gi
gi.require_version('AppStreamGlib', '1.0')
gi.require_version('Gtk', '3.0')
from gi.repository import AppStreamGlib, GLib, GObject, Gtk, Gio, Gdk

try:
    gi.require_version('Flatpak', '1.0')
    from gi.repository import Flatpak
except:
    pass

from .pkgInfo import FlatpakPkgInfo
from . import dialogs
from .dialogs import ChangesConfirmDialog, FlatpakProgressWindow
from .misc import debug


def check_ml(_id):
    on_ml = threading.current_thread() == threading.main_thread()
    print("%s on mainloop: %s" %(_id, on_ml))

class FlatpakRemoteInfo():
    def __init__(self, remote=None):
        if remote:
            self.name = remote.get_name()
            self.title = remote.get_title()
            self.url = remote.get_url()
            self.disabled = remote.get_disabled()
            self.noenumerate = remote.get_noenumerate()

            if not self.title or self.title == "":
                self.title = self.name.capitalize()
        else:
            self.name = None
            self.title = None
            self.url = None
            self.disabled = False
            self.noenumerate = False

    @classmethod
    def from_json(cls, json_data:dict):
        inst = cls()

        inst.name = json_data["name"]
        inst.title = json_data["title"]
        inst.url = json_data["url"]
        inst.disabled = json_data["disabled"]
        inst.noenumerate = json_data["noenumerate"]

        return inst

    def to_json(self):
        return self.__dict__

_fp_sys = None

_as_pool_lock = threading.Lock()
_as_pools = {} # keyed to remote name

def get_fp_sys():
    global _fp_sys

    if _fp_sys == None:
        _fp_sys = Flatpak.Installation.new_system(None)

    return _fp_sys

ALIASES = {
}

def make_pkg_hash(ref):
    if not isinstance(ref, Flatpak.Ref):
        raise TypeError("flatpak.make_pkg_hash() must receive FlatpakRef, not %s" % type(ref))

    try:
        return "fp:%s:%s" % (ref.get_origin(), ref.format_ref())
    except Exception:
        return "fp:%s:%s" % (ref.get_remote_name(), ref.format_ref())

def _get_remote_name_by_url(fp_sys, url):
    name = None

    try:
        remotes = fp_sys.list_remotes()
    except GLib.Error:
        remotes = []

    for remote in remotes:
        remote_url = remote.get_url()
        if remote_url.endswith('/'): #flatpakrefs are often missing the trailing forward slash in the url
            remote_url = remote_url[:-1]

        if remote_url == url:
            name = remote.get_name()

    return name

def _process_remote(cache, fp_sys, remote, arch):
    remote_name = remote.get_name()

    if remote.get_disabled():
        print("Installer: flatpak - remote '%s' is disabled, skipping" % remote_name)
        return

    print("Installer: flatpak - updating appstream data for remote '%s'..." % remote_name)

    try:
        success = fp_sys.update_appstream_sync(remote_name, arch, None)
    except GLib.Error:
        # Not fatal..
        pass

    # get_noenumerate indicates whether a remote should be used to list applications.
    # Instead, they're intended for single downloads (via .flatpakref files)
    if remote.get_noenumerate():
        print("Installer: flatpak - remote '%s' is marked as no-enumerate skipping package listing" % remote_name)
        return

    remote_url = remote.get_url()

    try:
        for ref in fp_sys.list_remote_refs_sync(remote_name, None):
            name = ref.get_name()

            if ".Plugin" in name:
                continue
            if ".Extension" in name:
                continue

            if ref.get_name().endswith("BaseApp"):
                continue

            if ref.get_name().endswith("Sdk"):
                continue
            if ref.get_name().endswith("Platform"):
                continue

            if ref.get_arch() != arch:
                continue

            if ref.get_eol() is not None:
                continue

            _add_package_to_cache(cache, ref, remote_url, False)
    except GLib.Error as e:
        print("Process remote:", e.message)

def _add_package_to_cache(cache, ref, remote_url, installed):
    pkg_hash = make_pkg_hash(ref)

    try:
        remote_name = ref.get_remote_name()
    except Exception:
        remote_name = ref.get_origin()

    try:
        pkginfo = cache[pkg_hash]

        if installed:
            pkginfo.installed = installed
    except KeyError:
        pkginfo = FlatpakPkgInfo(pkg_hash, remote_name, ref, remote_url, installed)
        cache[pkg_hash] = pkginfo

    return pkginfo

def process_full_flatpak_installation(cache):
    fp_time = time.time()

    arch = Flatpak.get_default_arch()
    fp_sys = get_fp_sys()

    flatpak_remote_infos = {}

    try:
        for remote in fp_sys.list_remotes():
            _process_remote(cache, fp_sys, remote, arch)

            remote_name = remote.get_name()

            try:
                for ref in fp_sys.list_installed_refs(None):
                    # All remotes will see installed refs, but the installed refs will always
                    # report their correct origin, so only add installed refs when they match the remote.
                    if ref.get_origin() == remote_name:
                        _add_package_to_cache(cache, ref, remote.get_url(), True)
            except GLib.Error as e:
                print("adding packages:", e.message)

            flatpak_remote_infos[remote_name] = FlatpakRemoteInfo(remote)

    except GLib.Error as e:
        print("Installer: flatpak - could not get remote list", e.message)
        cache = {}

    print('Installer: Processing Flatpaks for cache took %0.3f ms' % ((time.time() - fp_time) * 1000.0))

    return cache, flatpak_remote_infos

def _load_appstream_pool(pools, remote):
    pool = AppStreamGlib.Store()
    path = remote.get_appstream_dir().get_path()

    with open(os.path.join(path, "appstream.xml")) as f:
        pool.from_xml(f.read(), path)

    pools[remote.get_name()] = pool

def initialize_appstream():
    thread = threading.Thread(target=_initialize_appstream_thread)
    thread.start()

def _initialize_appstream_thread():
    fp_sys = get_fp_sys()

    global _as_pools
    global _as_pool_lock

    with _as_pool_lock:
        _as_pools = {}

        try:
            for remote in fp_sys.list_remotes():
                _load_appstream_pool(_as_pools, remote)
        except (GLib.Error, Exception) as e:
            try:
                msg = e.message
            except:
                msg = str(e)
            print("Installer: Could not initialize appstream components for flatpaks: %s" % msg)

def get_remote_or_installed_ref(ref, remote_name):
    fp_sys = get_fp_sys()

    try:
        iref = fp_sys.get_installed_ref(ref.get_kind(),
                                        ref.get_name(),
                                        ref.get_arch(),
                                        ref.get_branch(),
                                        None)

        if iref:
            return iref
    except GLib.Error as e:
        if e.code != Flatpak.Error.NOT_INSTALLED:
            print("Installer: Couldn't look up InstalledRef: %s" % e.message)

    try:
        rref = fp_sys.fetch_remote_ref_sync(remote_name,
                                            ref.get_kind(),
                                            ref.get_name(),
                                            ref.get_arch(),
                                            ref.get_branch(),
                                            None)
        if rref:
            return rref
    except GLib.Error as e:
        if e.code != Flatpak.Error.ALREADY_INSTALLED:
            print("Installer: Couldn't look up RemoteRef (%s): %s" % (remote_name, e.message))

    return None

def create_pkginfo_from_as_component(comp, remote_name, remote_url):
    name = comp.get_pkgname_default()
    branch = comp.get_branch()

    bundle = comp.get_bundle_default()

    shallow_ref = Flatpak.Ref.parse(bundle.get_id())

    ref = get_remote_or_installed_ref(shallow_ref, remote_name)
    if ref is None:
        return None

    pkg_hash = make_pkg_hash(ref)
    pkginfo = FlatpakPkgInfo(pkg_hash, remote_name, ref, remote_url)
    pkginfo.installed = isinstance(ref, Flatpak.InstalledRef)

    return pkginfo

def search_for_pkginfo_as_component(pkginfo):
    name = pkginfo.name

    comps = []

    global _as_pools
    global _as_pool_lock

    with _as_pool_lock:
        try:
            pool = _as_pools[pkginfo.remote]
        except Exception:
            return None

        comps = pool.get_apps_by_id(name)

        if comps == []:
            comps = pool.get_apps_by_id(name + ".desktop")

    if len(comps) > 0:
        return comps[0]
    else:
        return None

def _get_system_theme_matches():
    fp_sys = get_fp_sys()
    arch = Flatpak.get_default_arch()

    theme_refs = []

    gtksettings = Gtk.Settings.get_default()

    icon_theme = "org.freedesktop.Platform.Icontheme.%s" % gtksettings.props.gtk_icon_theme_name
    gtk_theme = "org.gtk.Gtk3theme.%s" % gtksettings.props.gtk_theme_name

    def sortref(ref):
        try:
            val = float(ref.get_branch())
        except ValueError:
            val = 9.9

        return val

    for name in (icon_theme, gtk_theme):
        theme_ref = None

        for remote in fp_sys.list_remotes():
            if remote.get_nodeps():
                continue
            remote_name = remote.get_name()

            try:
                print("Looking for theme %s in %s" % (name, remote_name))

                all_refs = fp_sys.list_remote_refs_sync(remote_name, None)
                matching_refs = []

                for listed_ref in all_refs:
                    if listed_ref.get_name() == name:
                        matching_refs.append(listed_ref)

                if not matching_refs:
                    continue

                # Sort highest version first.
                matching_refs = sorted(matching_refs, key=sortref, reverse=True)

                for matching_ref in matching_refs:
                    if matching_ref.get_arch() != arch:
                        continue

                    theme_ref = matching_ref
                    print("Found theme ref '%s' in remote %s" % (theme_ref.format_ref(), remote_name))
                    break

            except GLib.Error as e:
                theme_ref = None
                debug("Error finding themes for flatpak: %s" % e.message)

        if theme_ref:
            theme_refs.append(theme_ref)

    return theme_refs

def _get_installed_related_refs(remote, ref_str):
    return_refs = []

    related_refs = get_fp_sys().list_installed_related_refs_sync(remote,
                                                                 ref_str,
                                                                 None)

    return related_refs

def select_packages(task):
    task.transaction = FlatpakTransaction(task)

    print("Installer: Calculating changes required for Flatpak package: %s" % task.pkginfo.name)

def select_updates(task):
    task.transaction = FlatpakTransaction(task)

    print("Installer: Calculating Flatpak updates.")

class FlatpakTransaction():
    def __init__(self, task):
        self.task = task
        self.transaction = Flatpak.Transaction.new_for_installation(get_fp_sys(), task.cancellable)
        self.item_count = 0
        self.current_count = 0

        self.transaction_ready = False
        self.current_fp_progress = None
        self.op_error = None

        self.start_transaction = threading.Event()

        self.transaction.connect("ready", self.on_transaction_ready)
        self.transaction.connect("new-operation", self._new_operation)
        self.transaction.connect("operation-done", self._operation_done)
        self.transaction.connect("operation-error", self._operation_error)
        self.transaction.connect("end-of-lifed-with-rebase", self._ref_eoled_with_rebase)

        thread = threading.Thread(target=self._transaction_thread)
        thread.start()

    def _transaction_thread(self):
        try:
            if self.task.type == "install":
                self.transaction.add_install(self.task.pkginfo.remote,
                                             self.task.pkginfo.refid,
                                             None)
            elif self.task.type == "remove":
                self.transaction.add_uninstall(self.task.pkginfo.refid)

                for related_ref in _get_installed_related_refs(self.task.pkginfo.remote, self.task.pkginfo.refid):
                    self.transaction.add_uninstall(related_ref.format_ref())
            else:
                try:
                    if self.task.initial_refs_to_update != []:
                        for ref in self.task.initial_refs_to_update:
                            self.transaction.add_update(ref, None, None)
                    else:
                        for ref in get_fp_sys().list_installed_refs(self.task.cancellable):
                            self.transaction.add_update(ref.format_ref(), None, None)
                except GLib.Error as e:
                    print("Problem checking installed flatpaks updates: %s" % e.message)
                    raise


            # Always install the corresponding theme if we didn't already
            # have it.
            if self.task.type != "remove":
                if self.task.asapp is not None and self.task.asapp.get_kind() != AppStreamGlib.AppKind.ADDON:
                    for theme_ref in _get_system_theme_matches():
                        try:
                            self.transaction.add_install(theme_ref.get_remote_name(),
                                                         theme_ref.format_ref(),
                                                         None)
                        except GLib.Error as e:
                            if e.code == Flatpak.Error.ALREADY_INSTALLED:
                                continue
                            else:
                                raise

            # Simulate the install, cancel once ops are generated.

        except GLib.Error as e:
            self.on_transaction_error(e)


        try:
            self.transaction.run(self.task.cancellable)
        except GLib.Error as e:
            self.on_transaction_error(e)

        self.on_transaction_finished()

    def on_transaction_error(self, error):
        if not self.op_error:
            if error.code in (Flatpak.Error.ABORTED, Gio.IOErrorEnum.CANCELLED):
                return

        if not self.transaction_ready:
            self.task.handle_error(error, info_stage=True)
        else:
            if self.op_error:
                self.task.handle_error(self.op_error)
            else:
                self.task.handle_error(error)

    def on_transaction_finished(self):
        get_fp_sys().drop_caches(None)

        if self.task.error_message:
            self.task.call_error_cleanup_callback()
        else:
            self.task.call_finished_cleanup_callback()

    def on_transaction_progress(self, progress):
        package_chunk_size = 1.0 / self.item_count
        partial_chunk = (progress.get_progress() / 100.0) * package_chunk_size
        actual_progress = math.floor(((self.current_count * package_chunk_size) + partial_chunk) * 100.0)
        if self.task.client_progress_cb:
            GLib.idle_add(self.task.client_progress_cb,
                          self.task.pkginfo,
                          actual_progress,
                          progress.get_is_estimating(),
                          progress.get_status(),
                          priority=GLib.PRIORITY_DEFAULT)

    def _new_operation(self, transaction, op, progress):
        progress.set_update_frequency(500)
        progress.connect("changed", self.on_transaction_progress)

    def _operation_error(self, transaction, operation, error, details):
        # Set error from the failing operation - Overall transaction errors from real failure
        # use the same ABORTED code.
        # The op error will be more specific and useful (and let us distinguish cancel from fail).
        self.op_error = error
        return False

    def _operation_done(self, transaction, operation, commit, result, data=None):
        self.current_count += 1
        if self.current_count < self.item_count:
            return

    def on_transaction_ready(self, transaction):
        self.transaction_ready = True

        try:
            fp_sys = get_fp_sys()

            dl_size = 0
            disk_size = 0

            for op in self.transaction.get_operations():
                ref = Flatpak.Ref.parse(op.get_ref())
                op_type = op.get_operation_type()

                if op_type == Flatpak.TransactionOperationType.INSTALL:
                    dl_size += op.get_download_size()
                    disk_size += op.get_installed_size()
                    self._add_to_list(self.task.to_install, ref)
                elif op_type == Flatpak.TransactionOperationType.UNINSTALL:
                    iref = fp_sys.get_installed_ref(ref.get_kind(),
                                                    ref.get_name(),
                                                    ref.get_arch(),
                                                    ref.get_branch(),
                                                    None)

                    disk_size -= iref.get_installed_size()
                    self._add_to_list(self.task.to_remove, ref)
                else: # update
                    iref = fp_sys.get_installed_ref(ref.get_kind(),
                                                    ref.get_name(),
                                                    ref.get_arch(),
                                                    ref.get_branch(),
                                                    None)

                    current_installed_size = iref.get_installed_size()
                    new_installed_size = op.get_installed_size()
                    dl_size += op.get_download_size()
                    disk_size += new_installed_size - current_installed_size

                    self._add_to_list(self.task.to_update, ref)

            self.task.download_size = dl_size
            if disk_size > 0:
                self.task.install_size = disk_size
            else:
                self.task.freed_size = abs(disk_size)

        except Exception as e:
            # Something went wrong, bail out
            self.task.info_ready_status = self.task.STATUS_BROKEN
            self.task.handle_error(e)
            return False # Close 'ready' callback, cancel.

        if len(self.task.to_install) > 0:
            print("For install:")
            for ref in self.task.to_install:
                print(ref.format_ref())
        if len(self.task.to_remove) > 0:
            print("For removal:")
            for ref in self.task.to_remove:
                print(ref.format_ref())
        if len(self.task.to_update) > 0:
            print("For updating:")
            for ref in self.task.to_update:
                print(ref.format_ref())

        self.item_count = len(self.task.to_install + self.task.to_remove + self.task.to_update)

        self.task.info_ready_status = self.task.STATUS_OK
        self.task.confirm = self._confirm_transaction
        self.task.cancel = self._cancel_transaction
        self.task.execute = self._execute_transaction
        self.task.call_info_ready_callback()

        self.start_transaction.wait()

        if self.task.cancellable.is_cancelled():
            return False

        return True

    def _ref_eoled_with_rebase(self, transaction, remote, ref, reason, rebased_to_ref, prev_ids):
        # skip
        # transaction.add_uninstall(ref)
        # transaction.add_rebase(rebased_to_ref)
        return True

    def _add_to_list(self, ref_list, ref):
        ref_str = ref.format_ref()

        for existing_ref in ref_list:
            if ref_str == existing_ref.format_ref():
                debug("Skipping %s, already added to task" % ref_str)
                return

        ref_list.append(ref)

    def _get_runtime_ref_from_remote_metadata(self, remote_name, ref_str):
        runtime_ref = None

        ref = Flatpak.Ref.parse(ref_str)

        meta = get_fp_sys().fetch_remote_metadata_sync(remote_name, ref, None)
        data = meta.get_data().decode()

        keyfile = GLib.KeyFile.new()
        keyfile.load_from_data(data, len(data), GLib.KeyFileFlags.NONE)

        runtime = keyfile.get_string("Application", "runtime")
        runtime_ref = Flatpak.Ref.parse("runtime/%s" % runtime)

        return runtime_ref.format_ref()

    def _confirm_transaction(self):
        # only show a confirmation if:
        # - (install/remove) Additional changes are triggered for more than just the selected package.
        # - we're updating all available packages
        # - the packages specifically selected to be updated (initial_refs_to_update) trigger additional package installs/updates/removals
        total_count = len(self.task.to_install + self.task.to_remove + self.task.to_update)
        additional = False

        if self.task.type in (self.task.INSTALL_TASK, self.task.UNINSTALL_TASK) and total_count > 1:
            additional = True
        elif self.task.type == self.task.UPDATE_TASK:
            if len(self.task.initial_refs_to_update) == 0 or (total_count - len(self.task.initial_refs_to_update)) > 0:
                additional = True

        if additional:
            Gdk.threads_enter()
            dia = ChangesConfirmDialog(None, self.task, parent=self.task.parent_window)
            res = dia.run()
            dia.hide()
            dia.destroy()
            Gdk.threads_leave()
            return res == Gtk.ResponseType.OK
        else:
            return True

    def _cancel_transaction(self):
        self.task.cancellable.cancel()
        self.start_transaction.set()

    def _execute_transaction(self):
        if self.task.cancellable.is_cancelled():
            return False

        if self.task.client_progress_cb != None:
            self.task.has_window = True
            GLib.idle_add(self.task.client_progress_cb, self.task.pkginfo, 0, True, " : ", priority=GLib.PRIORITY_DEFAULT)
        else:
            GLib.idle_add(self._show_progress_window, self.task, priority=GLib.PRIORITY_DEFAULT)

        self.start_transaction.set()

    def _show_progress_window(self, task):
        progress_window = FlatpakProgressWindow(self.task)
        progress_window.present()

    def get_operations(self):
        return self.transaction.get_operations()

def list_updated_pkginfos(cache):
    fp_sys = get_fp_sys()

    updated = []

    try:
        updates = fp_sys.list_installed_refs_for_update(None)
    except GLib.Error as e:
        print("Installer: flatpak - could not get updated flatpak refs")
        return []

    for ref in updates:
        pkg_hash = make_pkg_hash(ref)

        try:
            updated.append(cache[pkg_hash])
        except KeyError:
            pass

    return updated

def get_updated_theme_refs():
    fp_sys = get_fp_sys()

    if not fp_sys.list_installed_refs_by_kind(Flatpak.RefKind.APP, None):
        return []

    return _get_system_theme_matches()

def find_pkginfo(cache, string):
    for key in cache.get_subset_of_type("f").keys():
        candidate = cache[key]

        if string == candidate.name:
            return candidate

    return None

def generate_uncached_pkginfos(cache):
    fp_sys = get_fp_sys()

    try:
        for remote in fp_sys.list_remotes():
            remote_name = remote.get_name()

            for ref in fp_sys.list_installed_refs(None):
                # All remotes will see installed refs, but the installed refs will always
                # report their correct origin, so only add installed refs when they match the remote.
                if ref.get_origin() == remote_name:
                    _add_package_to_cache(cache, ref, remote.get_url(), True)

    except GLib.Error as e:
        print("Installer: flatpak - could not check for uncached pkginfos", e.message)

def pkginfo_is_installed(pkginfo):
    fp_sys = get_fp_sys()

    try:
        iref = fp_sys.get_installed_ref(pkginfo.kind,
                                        pkginfo.name,
                                        pkginfo.arch,
                                        pkginfo.branch,
                                        None)

        if iref:
            return True
    except GLib.Error:
        pass

    return False

def list_remotes():
    fp_sys = get_fp_sys()

    remotes = []

    try:
        for remote in fp_sys.list_remotes():
            remotes.append(FlatpakRemoteInfo(remote))

    except GLib.Error as e:
        print("Installer: flatpak - could not fetch remote list", e.message)
        remotes = []

    return remotes

def get_pkginfo_from_file(cache, file, callback):
    thread = threading.Thread(target=_pkginfo_from_file_thread, args=(cache, file, callback))
    thread.start()

def _pkginfo_from_file_thread(cache, file, callback):
    fp_sys = get_fp_sys()

    path = file.get_path()

    if path == None:
        print("Installer: flatpak - no valid .flatpakref path provided")
        return None

    ref = None
    pkginfo = None
    remote_name = None

    with open(path) as f:
        contents = f.read()

        b = contents.encode("utf-8")
        gb = GLib.Bytes(b)

        new_remote = False

        try:
            kf = GLib.KeyFile()
            if kf.load_from_file(path, GLib.KeyFileFlags.NONE):
                name = kf.get_string("Flatpak Ref", "Name")
                url = kf.get_string("Flatpak Ref", "Url")

                try:
                    branch = kf.get_string("Flatpak Ref", "Branch")
                except GLib.Error as e:
                    if e.code == GLib.KeyFileError.KEY_NOT_FOUND:
                        print("Installer: flatpak - flatpakref file doesn't have a Branch key, maybe nightly or testing.")
                        branch = None

                remote_name = _get_remote_name_by_url(fp_sys, url)

                if name and remote_name:
                    ref = Flatpak.RemoteRef(remote_name=remote_name,
                                            kind=Flatpak.RefKind.APP,
                                            arch=Flatpak.get_default_arch(),
                                            branch=branch,
                                            name=name)
                    print("Installer: flatpak - using existing remote '%s' for flatpakref file install" % remote_name)
                else: #If Flatpakref is not installed already
                    try:
                        print("Installer: flatpak - trying to install new remote for flatpakref file")
                        ref = fp_sys.install_ref_file(gb, None)
                        fp_sys.drop_caches(None)

                        remote_name = ref.get_remote_name()
                        new_remote = True
                        print("Installer: flatpak - added remote '%s'" % remote_name)
                    except GLib.Error as e:
                        if e.code != Gio.DBusError.ACCESS_DENIED: # user cancelling auth prompt for adding a remote
                            print("Installer: could not add new remote to system: %s" % e.message)
                            dialogs.show_flatpak_error(e.message)
        except GLib.Error as e:
            print("Installer: flatpak - could not parse flatpakref file: %s" % e.message)
            dialogs.show_flatpak_error(e.message)

        if ref:
            try:
                remote = fp_sys.get_remote_by_name(remote_name, None)

                # We only process if it's not a new remote, otherwise our appstream data
                # will be out of sync with our package cache until we refresh the cache. This
                # can affect versioning especially.
                if new_remote:
                    _process_remote(cache, fp_sys, remote, Flatpak.get_default_arch())

                # Add the ref to the cache, so we can work with it like any other in mintinstall
                pkginfo = _add_package_to_cache(cache, ref, remote.get_url(), False)

                # Fetch the appstream info for the ref
                global _as_pools

                with _as_pool_lock:
                    if remote_name not in _as_pools.keys():
                        _load_appstream_pool(_as_pools, remote)

                # Some flatpakref files will have a pointer to a runtime .flatpakrepo file
                # We need to process and possibly add that remote as well.

                kf = GLib.KeyFile()
                if kf.load_from_file(path, GLib.KeyFileFlags.NONE):
                    try:
                        url = kf.get_string("Flatpak Ref", "RuntimeRepo")
                    except GLib.Error:
                        url = None

                    if url:
                        # Fetch the .flatpakrepo file
                        r = requests.get(url, stream=True)

                        file = tempfile.NamedTemporaryFile(delete=False)

                        with file as fd:
                            for chunk in r.iter_content(chunk_size=128):
                                fd.write(chunk)

                        # Get the true runtime url from the repo file
                        runtime_repo_url = _get_repofile_repo_url(file.name)

                        if runtime_repo_url:
                            existing = False

                            path = Path(file.name)
                            runtime_remote_name = Path(url).stem

                            # Check if the remote is already installed
                            for remote in fp_sys.list_remotes(None):
                                # See comments below in _remote_from_repo_file_thread about get_noenumerate() use.
                                if remote.get_url() == runtime_repo_url and not remote.get_noenumerate():
                                    print("Installer: flatpak - runtime remote '%s' already in system, skipping" % runtime_remote_name)
                                    existing = True
                                    break

                            if not existing:
                                print("Installer: Adding additional runtime remote named '%s' at '%s'" % (runtime_remote_name, runtime_repo_url))

                                cmd_v = ['flatpak',
                                         'remote-add',
                                         '--from',
                                         runtime_remote_name,
                                         file.name]

                                add_repo_proc = subprocess.Popen(cmd_v)
                                retcode = add_repo_proc.wait()

                                fp_sys.drop_caches(None)
                        os.unlink(file.name)
            except GLib.Error as e:
                print("Installer: could not process .flatpakref file: %s" % e.message)
                dialogs.show_flatpak_error(e.message)

    GLib.idle_add(callback, pkginfo, priority=GLib.PRIORITY_DEFAULT)

def add_remote_from_repo_file(cache, file, callback):
    thread = threading.Thread(target=_remote_from_repo_file_thread, args=(cache, file, callback))
    thread.start()

def _remote_from_repo_file_thread(cache, file, callback):
    try:
        path = Path(file.get_path())
    except TypeError:
        print("Installer: flatpak - no valid .flatpakrepo path provided")
        return

    fp_sys = get_fp_sys()

    # Make sure the remote isn't already setup (even under a different name)
    # We need to exclude -origin repos - they're added for .flatpakref files
    # if the remote isn't installed already, and get auto-removed when the app
    # the ref file describes gets uninstalled.  -origin remotes are also marked
    # no-enumerate, so we can filter them here by that.

    existing = False

    url = _get_repofile_repo_url(path)

    if url:
        for remote in fp_sys.list_remotes(None):
            if remote.get_url() == url and not remote.get_noenumerate():
                existing = True
                break

    if existing:
        GObject.idle_add(callback, file, "exists")
        return

    cmd_v = ['flatpak',
             'remote-add',
             '--from',
             path.stem,
             path]

    add_repo_proc = subprocess.Popen(cmd_v, stderr=subprocess.PIPE)
    stdout, stderr = add_repo_proc.communicate()

    if "Error.AccessDenied" in stderr.decode():
        GObject.idle_add(callback, file, "cancel")
        return

    if add_repo_proc.returncode != 0 and "already exists" not in stderr.decode():
        GObject.idle_add(callback, file, "error")
        return

    # We'll do a full cache rebuild - otherwise, after this installer session, the
    # new apps from this remote won't show up until the next scheduled cache rebuild.
    try:
        fp_sys.drop_caches(None)
    except GLib.Error:
        pass

    cache.force_new_cache_async(callback)

def _get_repofile_repo_url(path):
    kf = GLib.KeyFile()

    try:
        if kf.load_from_file(str(path), GLib.KeyFileFlags.NONE):
            url = kf.get_string("Flatpak Repo", "Url")

            return url
    except GLib.Error as e:
        print(e.message)

    return None



# From flatpak-dir-private.h
"""
/**
 * FLATPAK_DEPLOY_DATA_GVARIANT_FORMAT:
 *
 * s - origin
 * s - commit
 * as - subpaths
 * t - installed size
 * a{sv} - Metadata
 */
"""
FLATPAK_DEPLOY_DATA_GVARIANT_STRING = "(ssasta{sv})"
FLATPAK_DEPLOY_DATA_GVARIANT_FORMAT = GLib.VariantType(FLATPAK_DEPLOY_DATA_GVARIANT_STRING)

def _load_deploy_data(installed_ref):
    deploy_dir = Gio.File.new_for_path(installed_ref.get_deploy_dir())

    data_file = deploy_dir.get_child("deploy")

    try:
        contents, etag = data_file.load_bytes(None)
    except GLib.Error as e:
        print("Could not load deploy data: %s" % e.message)
        return None

    deploy_data = GLib.Variant.new_from_bytes(FLATPAK_DEPLOY_DATA_GVARIANT_FORMAT, contents, False)

    return deploy_data

def _get_deployed_version(pkginfo):
    iref = get_fp_sys().get_installed_ref(pkginfo.kind,
                                          pkginfo.name,
                                          pkginfo.arch,
                                          pkginfo.branch,
                                          None)

    if not iref:
        return None

    return iref.get_appdata_version()

    # data = _load_deploy_data(iref)

    # metadata = data.get_child_value(4)
    # version_var =  metadata.lookup_value("appdata-version", None)
    # return version_var.get_string()

