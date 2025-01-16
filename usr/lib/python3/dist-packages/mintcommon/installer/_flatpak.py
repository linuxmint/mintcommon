import time
import threading
import datetime
import math
from pathlib import Path
import subprocess
import requests
import tempfile
import os

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Xmlb', '2.0')
from gi.repository import GLib, GObject, Gtk, Gio, Gdk, Xmlb

try:
    gi.require_version('Flatpak', '1.0')
    from gi.repository import Flatpak
except:
    pass

from .pkgInfo import FlatpakPkgInfo
from . import dialogs
from .dialogs import ChangesConfirmDialog, FlatpakProgressWindow
from .misc import debug, warn, print_timing
from . import appstream_pool

class FlatpakRemoteInfo():
    def __init__(self, remote=None):
        if remote:
            self.name = remote.get_name()
            self.title = remote.get_title()
            self.summary = remote.get_comment()
            self.url = remote.get_url()
            self.disabled = remote.get_disabled()
            self.noenumerate = remote.get_noenumerate()
            if not self.title or self.title == "":
                self.title = " ".join( [word for word in self.name.split("-")])

            self.title = self.title.title()
        else:
            self.name = None
            self.title = None
            self.summary = None
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

def get_fp_sys():
    global _fp_sys

    if _fp_sys is None:
        _fp_sys = Flatpak.Installation.new_system(None)

    return _fp_sys

ALIASES = {
}

pools = {}

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

        if remote_url is None:
            break

        if remote_url.rstrip("/") == url.rstrip("/"):
            name = remote.get_name()

    return name

def _should_cache_ref(ref, arch):
    if ref.get_kind() == Flatpak.RefKind.RUNTIME:
        return False

    if ref.get_name().endswith("BaseApp"):
        return False

    if ref.get_name().endswith("BaseExtension"):
        return False

    if ref.get_arch() != arch:
        return False

    if ref.get_eol() is not None:
        return False

    return True

def _process_remote(cache, rpool, fp_sys, remote, arch):
    remote_name = remote.get_name()

    if remote.get_disabled():
        debug("Installer: flatpak - remote '%s' is disabled, skipping" % remote_name)
        return

    # get_noenumerate indicates whether a remote should be used to list applications.
    # Instead, they're intended for single downloads (via .flatpakref files)
    if remote.get_noenumerate():
        debug("Installer: flatpak - remote '%s' is marked as no-enumerate skipping package listing" % remote_name)
        return

    remote_url = remote.get_url()

    try:
        for ref in fp_sys.list_remote_refs_sync(remote_name, None):
            if not _should_cache_ref(ref, arch):
                continue
            _add_package_to_cache(cache, rpool, ref, remote_url, False)
    except GLib.Error as e:
        warn("Process remote:", e.message)

def _add_package_to_cache(cache, rpool, ref, remote_url, installed):
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

        as_package = None

        if rpool is not None:
            as_package = rpool.lookup_appstream_package(pkginfo)
        if as_package is not None:
            debug("Have as package: %s" % as_package.get_bundle_id())
        pkginfo.add_cached_appstream_data(as_package)

        cache[pkg_hash] = pkginfo

    return pkginfo

def process_full_flatpak_installation(cache):
    fp_time = time.time()

    arch = Flatpak.get_default_arch()
    fp_sys = get_fp_sys()

    flatpak_remote_infos = {}

    try:
        for remote in fp_sys.list_remotes():
            remote_name = remote.get_name()

            debug("Installer: flatpak - updating appstream data for remote '%s'..." % remote_name)
            try:
                success = fp_sys.update_appstream_sync(remote_name, arch, None)
            except GLib.Error as e:
                warn("Could not update appstream for %s: %s" % (remote_name, e.message))

            rpool = appstream_pool.Pool(remote)
            _process_remote(cache, rpool, fp_sys, remote, arch)

            try:
                for ref in fp_sys.list_installed_refs(None):
                    # All remotes will see installed refs, but the installed refs will always
                    # report their correct origin, so only add installed refs when they match the remote.
                    if ref.get_origin() == remote_name and _should_cache_ref(ref, arch):
                        _add_package_to_cache(cache, rpool, ref, remote.get_url(), True)
            except GLib.Error as e:
                warn("adding packages:", e.message)

            flatpak_remote_infos[remote_name] = FlatpakRemoteInfo(remote)

    except GLib.Error as e:
        warn("Installer: flatpak - could not get remote list", e.message)
        cache = {}

    debug('Installer: Processing Flatpaks for cache took %0.3f ms' % ((time.time() - fp_time) * 1000.0))

    return cache, flatpak_remote_infos

def initialize_appstream(cb=None):
    thread = threading.Thread(target=_initialize_appstream_thread, args=(cb,))
    thread.start()

def _initialize_appstream_thread(cb=None):
    global pools
    fp_sys = get_fp_sys()
    pools = {}

    try:
        for remote in fp_sys.list_remotes():
            try:
                # This won't always download anything, and if it does, cached info (display name,
                # summary, icon, verified status) won't be updated until the native package cache
                # is rebuilt, though that stuff is unlikely to change much over a short period of
                # time. More importantly, we'll get up-to-date release info, so they match the
                # Flatpak system for installing/updating.
                fp_sys.update_appstream_sync(remote.get_name(), None, None)
            except GLib.Error as e:
                debug("Problem checking for updated appstream, using existing (may be out of date): %s" % e.message)
            pool = appstream_pool.Pool(remote)
            pools[remote.get_name()] = pool
    except (GLib.Error, Exception) as e:
        try:
            msg = e.message
        except:
            msg = str(e)
        warn("Installer: Could not initialize appstream components for flatpaks: %s" % msg)

    if cb is not None:
        GLib.idle_add(cb)

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
            warn("Installer: Couldn't look up InstalledRef: %s" % e.message)

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
            warn("Installer: Couldn't look up RemoteRef (%s): %s" % (remote_name, e.message))

    return None

def create_pkginfo_from_as_pkg(as_pkg, remote_name, remote_url):
    bundle_id = as_pkg.get_bundle_id()

    shallow_ref = Flatpak.Ref.parse(bundle_id)

    ref = get_remote_or_installed_ref(shallow_ref, remote_name)
    if ref is None:
        return None

    pkg_hash = make_pkg_hash(ref)
    pkginfo = FlatpakPkgInfo(pkg_hash, remote_name, ref, remote_url)
    pkginfo.add_cached_appstream_data(as_pkg)
    pkginfo.installed = isinstance(ref, Flatpak.InstalledRef)

    return pkginfo

def search_for_pkginfo_appstream_package(pkginfo):
    try:
        package = pools[pkginfo.remote].lookup_appstream_package(pkginfo)
        return package
    except KeyError:
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
                debug("Looking for theme %s in %s" % (name, remote_name))

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
                    debug("Found theme ref '%s' in remote %s" % (theme_ref.format_ref(), remote_name))
                    break

            except GLib.Error as e:
                theme_ref = None
                warn("Error finding themes for flatpak: %s" % e.message)

        if theme_ref:
            theme_refs.append(theme_ref)

    return theme_refs

def _get_related_refs_for_removal(parent_pkginfo):
    return_refs = []

    # .Locale files
    related_refs = get_fp_sys().list_installed_related_refs_sync(parent_pkginfo.remote,
                                                                 parent_pkginfo.refid,
                                                                 None)
    return related_refs

def _get_addons_for_pkginfo(parent_pkginfo):
    global pools

    matched_addons = []
    try:
        aspool = pools[parent_pkginfo.remote]
        as_pkg = aspool.lookup_appstream_package(parent_pkginfo)

        if as_pkg is not None:
            addons = as_pkg.get_addons()

            for addon in addons:
                info = create_pkginfo_from_as_pkg(addon, parent_pkginfo.remote, parent_pkginfo.remote_url)
                if info:
                    if _addon_is_compatible(parent_pkginfo, info):
                        matched_addons.append(info)
    except Exception as e:
        warn("Could not get a list of addons: %s" % str(e))

    return matched_addons

def _get_metadata(remote_name, ref):
    try:
        # RemoteRef
        meta = ref.get_metadata()
    except AttributeError:
        meta = get_fp_sys().fetch_remote_metadata_sync(remote_name, ref, None)

    data = meta.get_data().decode()

    keyfile = GLib.KeyFile.new()
    keyfile.load_from_data(data, len(data), GLib.KeyFileFlags.NONE)

    return keyfile

def _addon_is_compatible(parent, addon):
    # Get the extension point name
    parent_meta = _get_metadata(parent.remote, Flatpak.Ref.parse(parent.refid))
    child_meta = _get_metadata(addon.remote, Flatpak.Ref.parse(addon.refid))

    # When multiple extensions of the same type can be used, the
    # addon's ID will have the prefix of its intended extension point:
    # org.gimp.GIMP.Plugin.BIMP -> org.gimp.GIMP.Plugin.
    #
    # Plugins built with the primary package will have their full name as
    # the extension group.
    addon_prefix = addon.name.rpartition(".")[0]
    ext_point = f"Extension {addon_prefix}"

    # Addons should always have a 'ref' field, at minimum, to match them with their app.
    try:
        eo_ref = child_meta.get_string("ExtensionOf", "ref")
        if eo_ref != parent.refid:
            return False
    except:
        pass

    groups, l = parent_meta.get_groups()

    for group in groups:
        # skip irrelevant groups
        if not group.startswith("Extension "):
            continue
        if group not in (ext_point, f"Extension {addon.name}"):
            continue

        # Look for a version field, see if it matches the addon's branch
        versions = []
        try:
            versions = parent_meta.get_string_list(group, "versions")
        except GLib.Error as e:
            try:
                versions = [parent_meta.get_string(group, "version")]
            except:
                pass
        if len(versions) > 0:
            return addon.branch in versions

        # See if the extension specifies a runtime, and if it matches the app's.
        # This may end up filtering out some valid addons if no extension versioning
        # is used, but...
        try:
            child_runtime = child_meta.get_string("ExtensionOf", "runtime")
            parent_runtime = parent_meta.get_string("Application", "runtime")

            if child_runtime != parent_runtime:
                return False
        except GLib.Error as e:
            pass

    # All else fails, let it thru anyhow. Who knows? Do you??
    return True

def select_packages(task):
    task.transaction = FlatpakTransaction(task)

    debug("Installer: Calculating changes required for Flatpak package: %s" % task.pkginfo.name)

def select_updates(task):
    task.transaction = FlatpakTransaction(task)

    debug("Installer: Calculating Flatpak updates.")

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
        self.transaction.connect("add-new-remote", self._transaction_add_new_remote)
        self.transaction.connect("end-of-lifed", self._ref_eoled)
        self.transaction.connect("end-of-lifed-with-rebase", self._ref_eoled_with_rebase)

        # Runtimes explicitly installed are 'pinned' - which means they'll never be automatically
        # removed due to being unused. Addons are useless without the apps they're for, so we can
        # disable pinning for them.
        if self.task.is_addon_task:
            self.transaction.set_disable_auto_pin(True)

        thread = threading.Thread(target=self._transaction_thread, name="flatpak-transaction-thread")
        thread.start()

    def _transaction_thread(self):
        try:
            if self.task.type == "install":
                self.transaction.add_install(self.task.pkginfo.remote,
                                             self.task.pkginfo.refid,
                                             None)
            elif self.task.type == "remove":
                self.transaction.add_uninstall(self.task.pkginfo.refid)

                if not self.task.is_addon_task:
                    for related_ref in _get_related_refs_for_removal(self.task.pkginfo):
                        self.transaction.add_uninstall(related_ref.format_ref())
                    for addon_info in _get_addons_for_pkginfo(self.task.pkginfo):
                        try:
                            self.transaction.add_uninstall(addon_info.refid)
                        except GLib.Error as e:
                            if e.code != Flatpak.Error.NOT_INSTALLED:
                                warn("Could not add uninstall for addon '%s': %s" % (addon_formatted_ref, e.message))
                            continue
            else:
                try:
                    all_updates = get_fp_sys().list_installed_refs_for_update(self.task.cancellable)

                    if self.task.initial_refs_to_update != []:
                        for ref in self.task.initial_refs_to_update:
                            # Sometimes it turns out we have a new package to install that is not part of
                            # another package's pulled-in dependencies. It ends up as a selectable update in
                            # mintupdate. Once it does, though, we have to find its associated package in
                            # the original update list so we know which remote to try and pull it from.
                            #
                            # FIXME: this is because select_updates only takes a ref string. It could take a a remote
                            # or installed- ref instead.
                            if not ref_is_installed(Flatpak.Ref.parse(ref)):
                                for installed_ref in all_updates:
                                    related_refs = get_fp_sys().list_remote_related_refs_sync(installed_ref.get_origin(),
                                                                                              installed_ref.format_ref(),
                                                                                              self.task.cancellable)
                                    for related_ref in related_refs:
                                        if related_ref.format_ref() == ref:
                                            self.transaction.add_install(installed_ref.get_origin(), ref, None)
                            else:
                                self.transaction.add_update(ref, None, None)

                    else:
                        for ref in all_updates:
                            self.transaction.add_update(ref.format_ref(), None, None)
                except GLib.Error as e:
                    warn("Problem checking installed flatpaks updates: %s" % e.message)
                    raise


            # Always install the corresponding theme if we didn't already
            # have it.
            if self.task.type != "remove":
                if self.task.as_pkg is not None and self.task.as_pkg.kind != "addon":
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

    def save_ref_current_version(self, ref):
        version = "<unknown>"

        try:
            version = ref.get_appdata_version()

            if version is None:
                version = ref.get_latest_commit()
        except:
            # not installed
            version = "installing"
            pass

        debug("Adding prior ref version for %s: %s" % (ref.format_ref(), version))
        self.task.ref_prior_versions_dict[ref.format_ref()] = version

    def on_transaction_error(self, error):
        if not self.op_error:
            if error.code in (Flatpak.Error.ABORTED, Gio.IOErrorEnum.CANCELLED):
                return

        if self.task.info_ready_status == self.task.STATUS_NONE:
            self.task.info_ready_status = self.task.STATUS_UNKNOWN

        if not self.transaction_ready:
            self.task.handle_error(error, info_stage=True)
        else:
            if self.op_error:
                self.task.handle_error(self.op_error)
            else:
                self.task.handle_error(error)

    def on_transaction_finished(self):
        get_fp_sys().drop_caches(None)

        # If an op failed, show an error, even though we 'finished successfully'
        if self.task.type == self.task.UPDATE_TASK and self.op_error:
            self.on_transaction_error(self.op_error)

        if self.task.error_message:
            self.task.call_error_cleanup_callback()
        else:
            self.task.call_finished_cleanup_callback()

    def on_transaction_progress(self, progress):
        package_chunk_size = 1.0 / self.item_count
        partial_chunk = (progress.get_progress() / 100.0) * package_chunk_size
        actual_progress = math.floor(((self.current_count * package_chunk_size) + partial_chunk) * 100.0)
        if self.task.client_progress_cb:
            Gdk.threads_add_idle(GLib.PRIORITY_DEFAULT,
                                 self.task.client_progress_cb,
                                 self.task.pkginfo,
                                 actual_progress,
                                 progress.get_is_estimating(),
                                 progress.get_status())

    def _new_operation(self, transaction, op, progress):
        progress.set_update_frequency(500)
        progress.connect("changed", self.on_transaction_progress)

    def _operation_error(self, transaction, operation, error, details):
        # Set error from the failing operation - Overall transaction errors from real failure
        # use the same ABORTED code. The op error will be more specific and useful (and let us
        # distinguish cancel from fail).

        # If the user cancelled the operation, cancel the transaction, but don't log it.
        if error.code == Gio.IOErrorEnum.CANCELLED:
            return False

        if self.task.type == self.task.UNINSTALL_TASK and error.code == Flatpak.Error.NOT_INSTALLED:
            return True

        self.op_error = error
        self.log_operation_result(operation, None, error)

        # Don't abort remaining operations if we're doing updates.
        return self.task.type == self.task.UPDATE_TASK

    def _operation_done(self, transaction, operation, commit, result, data=None):
        self.log_operation_result(operation, result)

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

                    self.save_ref_current_version(ref)
                    self._add_to_list(self.task.to_install, ref)
                elif op_type == Flatpak.TransactionOperationType.UNINSTALL:
                    iref = fp_sys.get_installed_ref(ref.get_kind(),
                                                    ref.get_name(),
                                                    ref.get_arch(),
                                                    ref.get_branch(),
                                                    None)
                    disk_size -= iref.get_installed_size()

                    self.save_ref_current_version(iref)
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

                    self.save_ref_current_version(iref)
                    self._add_to_list(self.task.to_update, ref)

            self.task.download_size = dl_size
            if disk_size > 0:
                self.task.install_size = disk_size
            else:
                self.task.freed_size = abs(disk_size)

        except Exception as e:
            # Something went wrong, bail out
            self.task.info_ready_status = self.task.STATUS_BROKEN
            self.task.handle_error(e, info_stage=True)
            return False # Close 'ready' callback, cancel.

        if len(self.task.to_install) > 0:
            debug("For install:")
            for ref in self.task.to_install:
                debug(ref.format_ref())
        if len(self.task.to_remove) > 0:
            debug("For removal:")
            for ref in self.task.to_remove:
                debug(ref.format_ref())
        if len(self.task.to_update) > 0:
            debug("For updating:")
            for ref in self.task.to_update:
                debug(ref.format_ref())

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

    def _transaction_add_new_remote(self, transaction, reason_code, from_id, suggested_remote_name, url, data=None):
        if reason_code == Flatpak.TransactionRemoteReason.GENERIC_REPO:
            reason = "The remote has additional apps."
        elif reason_code == Flatpak.TransactionRemoteReason.RUNTIME_DEPS:
            reason = "The remote has runtimes needed for the application."
        else:
            reason = "Reason unknown"

        debug("Adding new remote '%s' (%s) for %s: %s" % (suggested_remote_name, url, from_id, reason))
        return True

    def _ref_eoled(self, transaction, ref, reason, rebase):
        warn("%s is end-of-life (EOL) (%s)" % (ref, reason))

    def _ref_eoled_with_rebase(self, transaction, remote, ref, reason, rebased_to_ref, prev_ids):
        warn("%s is end-of-life (EOL): (%s)" % (ref, reason))

        if rebased_to_ref is not None:
            try:
                warn("Replacing with %s" % rebased_to_ref)
                transaction.add_rebase(remote, rebased_to_ref, None, prev_ids)
                transaction.add_uninstall(ref)
                return True
            except GLib.Error as e:
                debug("Problem adding replacement ref: %s" % e.message)
                return False

        warn("No updated ref to use, using the EOL'd one.")
        return False

    def _add_to_list(self, ref_list, ref):
        ref_str = ref.format_ref()

        for existing_ref in ref_list:
            if ref_str == existing_ref.format_ref():
                debug("Skipping %s, already added to task" % ref_str)
                return

        ref_list.append(ref)

    def _confirm_transaction(self):
        # only show a confirmation if:
        # - (install/remove) Additional changes are triggered for more than just the selected package.
        # - we're updating all available packages
        # - the packages specifically selected to be updated (initial_refs_to_update) trigger additional package installs/updates/removals
        total_count = len(self.task.to_install + self.task.to_remove + self.task.to_update)
        additional = False

        if total_count == 0:
            debug("No work to perform now - are you online still?")
            # FIXME: If the network's down, flatpak doesn't consider not being able to access remote refs as fatal, since it's an update
            # and they're already installed. We should popup a message to say so.
            return False

        if self.task.type in (self.task.INSTALL_TASK, self.task.UNINSTALL_TASK) and total_count > 1:
            additional = True
        elif self.task.type == self.task.UPDATE_TASK:
            if len(self.task.initial_refs_to_update) == 0 or (total_count - len(self.task.initial_refs_to_update)) > 0:
                additional = True

        if additional:
            dia = ChangesConfirmDialog(None, self.task, parent=self.task.parent_window)
            res = dia.run()
            dia.hide()
            dia.destroy()
            return res == Gtk.ResponseType.OK
        else:
            return True

    def _cancel_transaction(self):
        self.task.cancellable.cancel()
        self.start_transaction.set()

    def _execute_transaction(self):
        if self.task.cancellable.is_cancelled():
            return False

        if self.task.client_progress_cb is not None:
            self.task.has_window = True
            GLib.idle_add(self.task.client_progress_cb, self.task.pkginfo, 0, True, " : ")
        else:
            GLib.idle_add(self._show_progress_window, self.task)

        self.start_transaction.set()

    def _show_progress_window(self, task):
        progress_window = FlatpakProgressWindow(self.task)
        progress_window.present()

    def get_operations(self):
        return self.transaction.get_operations()

    def log_operation_result(self, operation, result, error=None):
        log_timestamp = datetime.datetime.now().strftime("%F::%T")
        basic_ref = Flatpak.Ref.parse(operation.get_ref())

        old_version = self.task.ref_prior_versions_dict[basic_ref.format_ref()]

        new_version = "<none>"
        if operation.get_operation_type() in (Flatpak.TransactionOperationType.INSTALL, Flatpak.TransactionOperationType.UPDATE):
            try:
                iref = get_fp_sys().get_installed_ref(basic_ref.get_kind(),
                                                      basic_ref.get_name(),
                                                      basic_ref.get_arch(),
                                                      basic_ref.get_branch(),
                                                      None)
                new_version = iref.get_appdata_version()

                if new_version is None:
                    new_version = iref.get_latest_commit()
            except Exception as e:
                pass
        else:
            new_version = "removed"

        if error is None:
            log_entry = "%s::%s::%s::%s::%s::%s" % (log_timestamp,
                                               basic_ref.get_kind().value_nick,
                                               Flatpak.transaction_operation_type_to_string(operation.get_operation_type()),
                                               basic_ref.get_name(),
                                               old_version,
                                               new_version)
        else:
            log_entry = "%s::%s::%s::%s::%s::FAILED: (%d): %s" % (log_timestamp,
                                               basic_ref.get_kind().value_nick,
                                               Flatpak.transaction_operation_type_to_string(operation.get_operation_type()),
                                               basic_ref.get_name(),
                                               old_version,
                                               error.code,
                                               error.message)

        debug("Logging: %s" % log_entry)
        self.task.transaction_log.append(log_entry)

def list_updated_pkginfos(cache):
    fp_sys = get_fp_sys()

    updated = []

    try:
        updates = fp_sys.list_installed_refs_for_update(None)
    except GLib.Error as e:
        warn("Installer: flatpak - could not get updated flatpak refs")
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

def find_pkginfo(cache, string, remote=None):
    for key in cache.get_subset_of_type("f").keys():
        candidate = cache[key]
        if string.partition("/")[0] in ("runtime", "app"):
            if string == candidate.refid:
                if remote is None or candidate.remote == remote:
                    return candidate
        elif string == candidate.name:
            if remote is None or candidate.remote == remote:
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
                    global pools
                    try:
                        pool = pools[remote_name]
                    except:
                        pool = None
                    debug("Generate uncached for: %s" % ref.format_ref())
                    _add_package_to_cache(cache, pool, ref, remote.get_url(), True)

    except GLib.Error as e:
        warn("Installer: flatpak - could not check for uncached pkginfos", e.message)

def _ref_is_installed(kind, name, arch, branch):
    fp_sys = get_fp_sys()

    try:
        iref = fp_sys.get_installed_ref(kind,
                                        name,
                                        arch,
                                        branch,
                                        None)

        if iref:
            return True
    except GLib.Error:
        pass

    return False

def ref_is_installed(ref):
    return _ref_is_installed(ref.get_kind(),
                             ref.get_name(),
                             ref.get_arch(),
                             ref.get_branch())

def pkginfo_is_installed(pkginfo):
    return _ref_is_installed(pkginfo.kind,
                             pkginfo.name,
                             pkginfo.arch,
                             pkginfo.branch)

def list_remotes():
    fp_sys = get_fp_sys()

    remotes = []

    try:
        for remote in fp_sys.list_remotes():
            remotes.append(FlatpakRemoteInfo(remote))

    except GLib.Error as e:
        warn("Installer: flatpak - could not fetch remote list", e.message)
        remotes = []

    return remotes

def get_pkginfo_from_file(cache, file, callback):
    thread = threading.Thread(target=_pkginfo_from_file_thread, args=(cache, file, callback))
    thread.start()

def _pkginfo_from_file_thread(cache, file, callback):
    fp_sys = get_fp_sys()

    path = file.get_path()

    if path is None:
        warn("Installer: flatpak - no valid .flatpakref path provided")
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
                        warn("Installer: flatpak - flatpakref file doesn't have a Branch key, maybe nightly or testing.")
                        branch = "master"

                remote_name = _get_remote_name_by_url(fp_sys, url)

                if name and remote_name:
                    ref = Flatpak.RemoteRef(remote_name=remote_name,
                                            kind=Flatpak.RefKind.APP,
                                            arch=Flatpak.get_default_arch(),
                                            branch=branch,
                                            name=name)
                    warn("Installer: flatpak - using existing remote '%s' for flatpakref file install" % remote_name)
                else: #If Flatpakref is not installed already
                    try:
                        warn("Installer: flatpak - trying to install new remote for flatpakref file")
                        ref = fp_sys.install_ref_file(gb, None)
                        fp_sys.drop_caches(None)

                        remote_name = ref.get_remote_name()
                        new_remote = True
                        warn("Installer: flatpak - added remote '%s'" % remote_name)
                    except GLib.Error as e:
                        if e.code != Gio.DBusError.ACCESS_DENIED: # user cancelling auth prompt for adding a remote
                            warn("Installer: could not add new remote to system: %s" % e.message)
                            dialogs.show_flatpak_error(e.message)
                        else:
                            warn("Installer: %s" % e.message)
        except GLib.Error as e:
            warn("Installer: flatpak - could not parse flatpakref file: %s" % e.message)
            dialogs.show_flatpak_error(e.message)

        if ref:
            try:
                global pools
                remote = fp_sys.get_remote_by_name(remote_name, None)

                try:
                    rpool = pools[remote.get_name()]
                except KeyError:
                    rpool = appstream_pool.Pool(remote)
                    _process_remote(cache, rpool, fp_sys, remote, Flatpak.get_default_arch())

                # Add the ref to the cache, so we can work with it like any other in mintinstall
                pkginfo = _add_package_to_cache(cache, rpool, ref, remote.get_url(), False)

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
                                    warn("Installer: flatpak - runtime remote '%s' already in system, skipping" % runtime_remote_name)
                                    existing = True
                                    break

                            if not existing:
                                warn("Installer: Adding additional runtime remote named '%s' at '%s'" % (runtime_remote_name, runtime_repo_url))

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
                warn("Installer: could not process .flatpakref file: %s" % e.message)
                dialogs.show_flatpak_error(e.message)

    GLib.idle_add(callback, pkginfo, priority=GLib.PRIORITY_DEFAULT)

def add_remote_from_repo_file(cache, file, callback):
    thread = threading.Thread(target=_remote_from_repo_file_thread, args=(cache, file, callback))
    thread.start()

def _remote_from_repo_file_thread(cache, file, callback):
    try:
        path = Path(file.get_path())
    except TypeError:
        warn("Installer: flatpak - no valid .flatpakrepo path provided")
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
        warn(e.message)

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
        warn("Could not load deploy data: %s" % e.message)
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

