import time
import threading
import apt

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version("PackageKitGlib", "1.0")

from gi.repository import Gtk, GLib
from gi.repository import PackageKitGlib as packagekit

from aptdaemon.gtk3widgets import AptProgressDialog

from .pkgInfo import AptPkgInfo
from .dialogs import ChangesConfirmDialog
from .misc import check_ml, warn, debug
from . import dialogs

# List extra packages that aren't necessarily marked in their control files, but
# we know better...
CRITICAL_PACKAGES = ["mint-common", "mint-translations", "mint-meta-core", "mintdesktop", "python3", "perl"]

def capitalize(string):
    if len(string) > 1:
        return (string[0].upper() + string[1:])

    return (string)

_apt_cache = None
_apt_cache_lock = threading.Lock()
_as_pool = None

def get_apt_cache(full=False):
    global _apt_cache

    if full or (not _apt_cache):
        with _apt_cache_lock:
            _apt_cache = apt.Cache()

    return _apt_cache

def add_prefix(name):
    return "apt:%s" % (name)

def get_real_error(code):
    n = int(code)
    if n > 255:
        return packagekit.ErrorEnum(n - 255)
    else:
        return packagekit.ClientError(n)

def make_pkg_hash(apt_pkg):
    if not isinstance(apt_pkg, apt.Package):
        raise TypeError("apt.make_pkg_hash_make must receive apt.Package, not %s" % type(apt_pkg))

    return add_prefix(apt_pkg.name)

def process_full_apt_cache(cache):
    apt_time = time.time()
    apt_cache = get_apt_cache()

    sections = {}

    keys = apt_cache.keys()

    for key in keys:
        name = apt_cache[key].name
        pkg = apt_cache[key]

        if name.startswith("lib") and not name.startswith(("libreoffice", "librecad", "libk3b7", "libimage-exiftool-perl")):
            continue
        if name.endswith(":i386") and name != "steam:i386":
            continue
        if name.endswith("-dev"):
            continue
        if name.endswith("-dbg"):
            continue
        if name.endswith("-doc"):
            continue
        if name.endswith("-common"):
            continue
        if name.endswith("-data"):
            continue
        if "-locale-" in name:
            continue
        if "-l10n-" in name:
            continue
        if name.endswith("-dbgsym"):
            continue
        if name.endswith("l10n"):
            continue
        if name.endswith("-perl"):
            continue
        if name == "snapd":
            continue
        if name == "pepperflashplugin-nonfree": # formerly marked broken, it's now a dummy and has no dependents (and only exists in Mint 20).
            continue
        if pkg.candidate is None:
            continue
        # kernel, universe/kernel, multiverse/kernel, restricted/kernel
        if pkg.candidate.section.endswith("kernel"):
            continue
        if name.startswith(("linux-headers-", "linux-tools-")):
            continue
        if ":" in name and name.split(":")[0] in keys:
            continue
        try:
            if "transitional" in pkg.candidate.summary.lower():
                continue
        except Exception as e:
            warn("Problem parsing package (maybe it's virtual): %s: %s" % (name, e))
            continue
            # pass

        pkg_hash = make_pkg_hash(pkg)

        section_string = pkg.candidate.section

        if "/" in section_string:
            section = section_string.split("/")[1]
        else:
            section = section_string

        sections.setdefault(section, []).append(pkg_hash)

        cache[pkg_hash] = AptPkgInfo(pkg_hash, pkg)

    debug('Installer: Processing APT packages for cache took %0.3f ms' % ((time.time() - apt_time) * 1000.0))

    return cache, sections

def search_for_pkginfo_apt_pkg(pkginfo):
    name = pkginfo.name

    apt_cache = get_apt_cache()

    try:
        return apt_cache[name]
    except:
        return None

def pkginfo_is_installed(pkginfo):
    global _apt_cache_lock
    apt_cache = get_apt_cache()

    with _apt_cache_lock:
        try:
            return apt_cache[pkginfo.name].installed is not None
        except:
            return False

def sync_cache_installed_states():
    get_apt_cache(full=True)

def select_packages(task):
    task.transaction = MetaTransaction(task)

    debug("Installer: Calculating changes required for APT package: %s" % task.pkginfo.name)

class MetaTransaction(packagekit.Task):
    def __init__(self, task):
        packagekit.Task.__init__(self)

        self.task = task
        self.simulated_download_size = 0

        thread = threading.Thread(target=self._calculate_apt_changes)
        thread.start()

    def _calculate_apt_changes(self):
        global _apt_cache_lock
        apt_cache = get_apt_cache()
        with _apt_cache_lock:
            apt_cache.clear()
            apt_pkg = apt_cache[self.task.pkginfo.name]
            results = None

            pkg_id = packagekit.Package.id_build(apt_pkg.shortname, "", apt_pkg.architecture(), "")

        self.set_simulate(True)

        try:
            if self.task.type == "remove":
                results = self.remove_packages_sync(
                    [pkg_id],
                    True, True, # allow_deps, autoremove
                    self.task.cancellable,  # cancellable
                    self.on_transaction_progress,
                    None  # progress data
                )
            elif self.task.type == "install":
                results = self.install_packages_sync(
                    [pkg_id],
                    self.task.cancellable,  # cancellable
                    self.on_transaction_progress,
                    None  # progress data
                )
            elif self.task.type == "update":
                debug("todo update")
        except GLib.Error as e:
            self.on_transaction_error(e)

        self.on_transaction_finished(results)

    def on_transaction_error(self, error):
        # PkErrorEnums are sent from the backend mainly
        # PkClientErrors are related to interaction with a task/client - accept/deny, etc...
        if error.code == packagekit.ClientError.DECLINED_SIMULATION:
            # canceled via additional-changes dialog
            return

        # it thinks it's a PkClientError but it's really PkErrorEnum
        # the GError code is set to 0xFF + code
        real_code = error.code
        if error.code >= 0xFF:
            real_code = error.code - 0xFF

            if real_code == packagekit.ErrorEnum.NOT_AUTHORIZED:
                # Silently ignore auth failures or cancellation.
                return

        if self.task.cancellable.is_cancelled():
            # user navigated away before simulation was complete, etc...
            return

        if real_code == packagekit.ErrorEnum.CANNOT_REMOVE_SYSTEM_PACKAGE or self.task.pkginfo.name in CRITICAL_PACKAGES:
            self.task.info_ready_status = self.task.STATUS_FORBIDDEN

        if self.task.info_ready_status == self.task.STATUS_NONE:
            if real_code == packagekit.ErrorEnum.DEP_RESOLUTION_FAILED:
                self.task.info_ready_status = self.task.STATUS_BROKEN
            else:
                self.task.info_ready_status = self.task.STATUS_UNKNOWN

        self.task.handle_error(error, info_stage = self.get_simulate())

    def on_transaction_finished(self, results):
        # == operation was successful
        if results:
            exit_code = results.get_exit_code()
            pkerror = results.get_error_code()
            if pkerror:
                warn("Finished code: ", pkerror.get_code(), pkerror.get_details())
            debug("Exit code:", exit_code)

        if self.task.error_message:
            self.task.call_error_cleanup_callback()
        else:
            self.task.call_finished_cleanup_callback()

    def on_transaction_progress(self, progress, ptype, data=None):
        if progress.get_status() == packagekit.StatusEnum.UNKNOWN:
            return

        if self.get_simulate():
            if ptype == packagekit.ProgressType.DOWNLOAD_SIZE_REMAINING:
                new_size = progress.get_download_size_remaining()
                if new_size > self.simulated_download_size:
                    self.simulated_download_size = new_size
                # print("current:", progress.get_package_id(), progress.get_status())
            return

        if ptype == packagekit.ProgressType.PERCENTAGE:
            if self.task.client_progress_cb:
                GLib.idle_add(self.task.client_progress_cb,
                              self.task.pkginfo,
                              progress.get_percentage(),
                              False,
                              priority=GLib.PRIORITY_DEFAULT)

    def do_simulate_question(self, request, results):
        if self.task.cancellable.is_cancelled():
            self.user_declined()
            return;

        self.task.pkit_request_id = request
        sack = results.get_package_sack()

        install_dbginfo = []
        remove_dbginfo = []
        update_dbginfo = []
        added_size = 0
        freed_size = 0

        global _apt_cache_lock
        apt_cache = get_apt_cache()

        with _apt_cache_lock:
            for pkg in sack.get_array():
                info = pkg.get_info()

                def calc_space(pkg, is_update=False):
                    apt_pkg = apt_cache["%s:%s" % (pkg.get_name(), pkg.get_arch())]

                    candidate = apt_pkg.candidate

                    if is_update:
                        for version in apt_pkg.versions:
                            if version.is_installed:
                                return candidate.installed_size - version.installed_size

                    return candidate.installed_size

                if info == packagekit.InfoEnum.INSTALLING:
                    self.task.to_install.append(pkg)
                    added_size += calc_space(pkg)
                    install_dbginfo.append("%s:%s (%s)" % (pkg.get_name(), pkg.get_arch(), pkg.get_version()))
                elif info == packagekit.InfoEnum.UPDATING:
                    self.task.to_update.append(pkg)
                    added_size += calc_space(pkg, is_update=True)
                    update_dbginfo.append("%s:%s (%s)" % (pkg.get_name(), pkg.get_arch(), pkg.get_version()))
                elif info == packagekit.InfoEnum.REMOVING:
                    self.task.to_remove.append(pkg)
                    freed_size += calc_space(pkg)
                    remove_dbginfo.append("%s:%s (%s)" % (pkg.get_name(), pkg.get_arch(), pkg.get_version()))

            debug("For install:", install_dbginfo)
            debug("For removal:", remove_dbginfo)
            debug("For upgrade:", update_dbginfo)

            self.task.download_size = self.simulated_download_size

            space = added_size - freed_size

            if space < 0:
                self.task.freed_size = space * -1
                self.task.install_size = 0
            else:
                self.task.freed_size = 0
                self.task.install_size = space

            for pkg in self.task.to_remove:
                apt_pkg_name = apt_cache["%s:%s" % (pkg.get_name(), pkg.get_arch())]

                if self._is_critical_package(apt_cache[apt_pkg_name]):
                    warn("Installer: apt - cannot remove critical package: %s" % apt_pkg_name)
                    self.task.info_ready_status = self.task.STATUS_FORBIDDEN

            if self.task.info_ready_status not in (self.task.STATUS_FORBIDDEN, self.task.STATUS_BROKEN):
                self.task.info_ready_status = self.task.STATUS_OK
                self.task.confirm = self._confirm_transaction
                self.task.cancel = self._cancel_transaction
                self.task.execute = self._execute_transaction

            self.task.call_info_ready_callback()

    def _is_critical_package(self, pkg):
        try:
            if pkg.versions[0].priority == "required" or pkg.name in CRITICAL_PACKAGES:
                return True

            return False
        except Exception:
            return False

    def _confirm_transaction(self):
        if len(self.task.to_install) > 1 or len(self.task.to_remove) > 1 or len(self.task.to_update) > 0:
            dia = ChangesConfirmDialog(self, self.task, parent=self.task.parent_window)
            res = dia.run()
            dia.hide()
            dia.destroy()

            return res == Gtk.ResponseType.OK
        else:
            return True

    def _cancel_transaction(self):
        self.task.cancellable.cancel()

        if self.task.pkit_request_id > 0:
            self.user_declined(self.task.pkit_request_id)
            self.task.pkit_request_id = 0

    def _execute_transaction(self):
        self.set_simulate(False)

        if self.task.cancellable.is_cancelled():
            return

        if self.task.client_progress_cb is not None:
            self.task.has_window = True

        if self.task.has_window:
            self.user_accepted(self.task.pkit_request_id)
        else:
            progress_window = AptProgressDialog(self)
            progress_window.run(show_error=False, error_handler=self._on_error)
