#!/usr/bin/python3
import threading
import time
import tempfile

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GLib, GObject, Gio, Gtk

from . import cache, _flatpak, _apt, dialogs
from .misc import print_timing, check_ml, debug, warn

PKG_TYPE_ALL = None
PKG_TYPE_APT = "a"
PKG_TYPE_FLATPAK = "f"

Gtk.IconTheme.get_default().append_search_path("/usr/share/linuxmint/icons")

class InstallerTask:
    # task types
    INSTALL_TASK = "install"
    UNINSTALL_TASK = "remove"
    UPDATE_TASK = "update"

    # Set after a package selection, reflects whether task can proceed or not
    STATUS_NONE = "none"
    STATUS_OK = "ok"
    STATUS_BROKEN = "broken"
    STATUS_FORBIDDEN = "forbidden"
    STATUS_UNKNOWN = "unknown"

    # Used by standalone progress window to update labels appropriately
    PROGRESS_STATE_INIT = "init"
    PROGRESS_STATE_INSTALLING = "installing"
    PROGRESS_STATE_UPDATING = "updating"
    PROGRESS_STATE_REMOVING = "removing"
    PROGRESS_STATE_FINISHED = "finished"
    PROGRESS_STATE_FAILED = "failed"

    def __init__(self, pkginfo, installer,
                client_info_ready_callback, client_info_error_callback,
                client_installer_finished_cb, client_installer_progress_cb,
                installer_cleanup_cb, installer_error_cleanup_cb, is_addon_task=False, use_mainloop=False, parent_window=None):
        self.type = InstallerTask.INSTALL_TASK

        self.use_mainloop = use_mainloop
        self.parent_window = parent_window

        # pkginfo will be None for an update task
        self.pkginfo = pkginfo
        self.is_addon_task = is_addon_task

        # AsApp if available
        self.as_pkg = None

        self.name = None

        # Lists the refs we selected for an update, vs those added as dependencies (this is for our confirm dialog to
        # make layout decisions)
        self.initial_refs_to_update = []

        # FlatpakRef : pre-transaction-version or commit
        # For activity logging so we can record pre and post-version.
        self.ref_prior_versions_dict = {}
        self.transaction_log = []

        # Set by .select_pkginfo(), the re-entry point after a task is fully
        # calculated, and the UI should be updated with detailed info about
        # the pending operation (disk use, etc..)
        self.info_ready_callback = client_info_ready_callback
        self.info_error_callback = client_info_error_callback
        # To be checked by the info_ready_callback, to allow the UI to reflect
        # the ability to proceed with a task, or report that something is not right.
        self.info_ready_status = self.STATUS_NONE

        # Set by the backend, the functions to call to actually confirm and perform the
        # task (will be none on STATUS_BROKEN or _FORBIDDEN)
        self.confirm = lambda: True
        self.cancel = lambda: True
        self.execute = None

        # Passed to _flatpak operations to respond to the Cancel button in the
        # standalone progress window. eventually it may be used elsewhere.
        self.cancellable = Gio.Cancellable()

        # Callbacks that will be used at various points during a task being operated on.
        # The .client_* callbacks are arguments of Installer.execute_task().  The
        # client_finished_cb is required.  If the progress callback is missing, a standalone
        # progress window will be provided.
        self.client_progress_cb = client_installer_progress_cb
        self.client_finished_cb = client_installer_finished_cb

        # These are internally used - called as the 'real' error and finished callback,
        # to do some cleanup like removing the task and reloading the apt cache before
        # finally calling task.client_finished_cb
        self.error_cleanup_cb = installer_error_cleanup_cb
        self.finished_cleanup_cb = installer_cleanup_cb

        self.has_window = False
        # Updated throughout a flatpak operation - for now it's used for updating the
        # standalone flatpak progress window
        self.progress_state = self.PROGRESS_STATE_INIT
        # Same - allows the flatpak window to update the current package being installed/removed
        self.current_package_name = None
        # The error message displayed in a popup if a flatpak operation fails.
        self.error_message = None

        self.transaction = None
        self.pkit_request_id = 0

        # The command that can be used to launch the current target package, if it's installed
        self.exec_string = None

        # List of additional packages to install, remove or update, based on the selected
        # pkginfo. Depending on the backend, they will consist of PkPackages or stringified
        # flatpak refs (the result of ref.format_ref()).
        self.to_install = []
        self.to_reinstall = [] # unused
        self.to_remove = []
        self.to_purge = [] # unused
        self.to_update = []
        self.to_downgrade = [] # unused
        self.to_skip_upgrade = [] # unused

        # Size info for display, calculated by the backend during .select_pkginfo()
        self.download_size = 0
        self.install_size = 0
        self.freed_size = 0

        # Static info filled in for display
        if pkginfo:
            self.name = pkginfo.name

            if pkginfo.pkg_hash.startswith("a"):
                self.arch = ""
                self.branch = ""
                self.remote = ""
            else:
                self.arch = pkginfo.arch
                self.remote = pkginfo.remote
                self.branch = pkginfo.branch

    def set_version(self, installer):
        if self.type == InstallerTask.INSTALL_TASK:
            # install packages, show pending version
            self.version = installer.get_version(self.pkginfo)
        else:
            # Remove packages, show current version
            self.version = installer.get_installed_version(self.pkginfo)

    def get_transaction_log(self):
        return self.transaction_log

    def call_info_ready_callback(self):
        if self.info_ready_callback is None:
            return

        if self.use_mainloop:
            GLib.idle_add(self.info_ready_callback, self, priority=GLib.PRIORITY_DEFAULT)
        else:
            self.info_ready_callback(self)

    def handle_error(self, error, info_stage=False):
        try:
            self.error_message = error.message
        except:
            self.error_message = str(error)

        if info_stage:
            if self.info_error_callback is None:
                dialogs.show_error(self.error_message, self.parent_window)
                return

            if self.use_mainloop:
                GLib.idle_add(self.info_error_callback, self, priority=GLib.PRIORITY_DEFAULT)
            else:
                self.info_error_callback(self)
        else:
            dialogs.show_error(self.error_message, self.parent_window)

    def call_finished_cleanup_callback(self):
        if not self.finished_cleanup_cb:
            return

        if self.use_mainloop:
            GLib.idle_add(self.finished_cleanup_cb, self, priority=GLib.PRIORITY_DEFAULT)
        else:
            self.finished_cleanup_cb(self)

    def call_error_cleanup_callback(self):
        if not self.error_cleanup_cb:
            return

        if self.use_mainloop:
            GLib.idle_add(self.error_cleanup_cb, self, priority=GLib.PRIORITY_DEFAULT)
        else:
            self.error_cleanup_cb(self)

class Installer(GObject.Object):
    __gsignals__ = {
        'appstream-changed': (GObject.SignalFlags.RUN_LAST, None, ()),
    }
    def __init__(self, pkg_type=PKG_TYPE_ALL, temp=False):
        GObject.Object.__init__(self)

        self.tasks = {}
        self.pkg_type = pkg_type

        if temp:
            f = tempfile.NamedTemporaryFile(prefix="mint-common-installer-tmp")
            self.cache_path = f.name
        else:
            self.cache_path = None

        self.remotes_changed = False
        self.inited = False

        self.have_flatpak = False
        self.have_flatpak = self._get_flatpak_status()

        self.cache = {}
        self._init_cb = None

        self.startup_timer = time.time()

    def _get_flatpak_status(self):
        try:
            gi.require_version('Flatpak', '1.0')
            from gi.repository import Flatpak

            return True
        except:
            warn("No flatpak support, install flatpak and gir1.2-flatpak-1.0 and restart mintinstall to enable it.")

        return False

    def init_sync(self):
        """
        Loads the cache synchronously.  Returns True if all went ok, and returns False if there
        is no cache (or it's too old.)  You should then call init() with a callback so the cache
        can be regenerated.
        """
        
        if self.pkg_type == PKG_TYPE_FLATPAK and not self.have_flatpak:
            debug("Not syncing for flatpaks only, as there is currently no support")
            return True

        self.settings = Gio.Settings(schema_id="com.linuxmint.install")

        if self._fp_remotes_have_changed():
            self.remotes_changed = True

        self.backend_table = {}

        self.cache = cache.PkgCache(self.pkg_type, self.cache_path, self.have_flatpak)

        if self.cache.status == self.cache.STATUS_OK and not self.remotes_changed:
            self.inited = True

            self.initialize_appstream()

            return True

        return False

    def init(self, ready_callback=None):
        """
        Loads the cache asynchronously.  If there is no cache (or it's too old,) it causes
        one to be generated and saved.  The ready_callback is called on idle once this is finished.
        """
        self.backend_table = {}

        self.cache = cache.PkgCache(self.pkg_type, self.cache_path, self.have_flatpak)

        self._init_cb = ready_callback

        if self.cache.status == self.cache.STATUS_OK and not self.remotes_changed:
            self.inited = True

            GObject.idle_add(self._idle_cache_load_done)
        else:
            if self.remotes_changed:
                debug("Installer: Flatpak remotes have changed, forcing a new cache.")

            self.cache.force_new_cache_async(self._idle_cache_load_done)

        return self

    def force_new_cache(self, ready_callback=None):
        """
        Forces the cache to regenerate, calling read_callback when complete
        """
        self.cache.force_new_cache_async(ready_callback)

    def force_new_cache_sync(self):
        """
        Forces the cache to regenerate synchronously
        """
        self.cache.force_new_cache()

    def _idle_cache_load_done(self):
        self.inited = True

        if self.remotes_changed:
            self._store_remotes()
            self.remotes_changed = False

        self.initialize_appstream()

        debug('Full installer startup took %0.3f ms' % ((time.time() - self.startup_timer) * 1000.0))

        if self._init_cb:
            self._init_cb()

    @print_timing
    def _fp_remotes_have_changed(self):
        """
        We check here for changed remotes.  We care if names, urls, and disabled status changed.
        The 'noenumerate' property won't change, and is usually marked on standalone (-source) ref
        installs.  We don't want to generate a new cache for those - their app can be accessed via
        installed apps, plus if you uninstall the app, the remote gets auto-removed.
        """
        changed = False
        real_remote_count = 0

        saved_remotes = self.settings.get_strv("flatpak-remotes")
        fp_remotes = self.list_flatpak_remotes()

        for remote_info in fp_remotes:
            real_remote_count += 1

            item = "%s::%s::%s" % (remote_info.name, remote_info.url, str(remote_info.disabled))

            if item not in saved_remotes:
                changed = True
                break

        if not changed:
            if len(saved_remotes) != real_remote_count:
                changed = True

        debug("Remotes have changed:", changed)

        return changed

    @print_timing
    def _store_remotes(self):
        new_remotes = []

        fp_remotes = self.list_flatpak_remotes()

        for remote_info in fp_remotes:
            item = "%s::%s::%s" % (remote_info.name, remote_info.url, str(remote_info.disabled))

            new_remotes.append(item)

        self.settings.set_strv("flatpak-remotes", new_remotes)

    def select_pkginfo(self, pkginfo,
                       client_info_ready_callback, client_info_error_callback,
                       client_installer_finished_cb, client_installer_progress_cb,
                       use_mainloop=False, parent_window=None):
        """
        Initiates calculations for installing or removing a particular package
        (depending upon whether or not the selected package is installed.  Creates
        an InstallerTask instance and populates it with info relevant for display
        and for execution later.  When this is completed, ready_callback is called,
        with the newly-created task as its argument.  Note:  At that point, this is
        the *only* reference to the task object.  It can be safely discarded.  If
        the task is to be run, Installer.execute_task() is called, passing this task
        object, along with callback functions.  The task object is then added to a
        queue (and is tracked in self.tasks from there on out.)
        """
        if pkginfo.pkg_hash in self.tasks.keys():
            task = self.tasks[pkginfo.pkg_hash]

            GObject.idle_add(task.info_ready_callback, task)
            return task.cancellable

        task = InstallerTask(pkginfo, self,
                             client_info_ready_callback, client_info_error_callback,
                             client_installer_finished_cb, client_installer_progress_cb,
                             self._task_finished, self._task_error,
                             use_mainloop=use_mainloop, parent_window=parent_window)

        if self.pkginfo_is_installed(pkginfo):
            # It's not installed, so assume we're installing
            task.type = InstallerTask.UNINSTALL_TASK
        else:
            task.type = InstallerTask.INSTALL_TASK

        task.set_version(self)
        task.as_pkg = self.get_appstream_pkg_for_pkginfo(pkginfo)

        if pkginfo.pkg_hash.startswith("a"):
            _apt.select_packages(task)
        else:
            _flatpak.select_packages(task)

        return task.cancellable

    def select_flatpak_updates(self, refs,
                               client_info_ready_callback, client_info_error_callback,
                               client_installer_finished_cb, client_installer_progress_cb,
                               use_mainloop=False):
        """
        Creates an InstallerTask populated with all flatpak packages that can be
        updated. If refs is empty, selects all possible updates, otherwise, only attempts
        to update refs.
        """
        task = InstallerTask(None, self,
                             client_info_ready_callback, client_info_error_callback,
                             client_installer_finished_cb, client_installer_progress_cb,
                             self._task_finished, self._task_error,
                             use_mainloop=use_mainloop)

        task.type = InstallerTask.UPDATE_TASK
        task.initial_refs_to_update = refs if refs else []

        _flatpak.select_updates(task)

    def list_updated_flatpak_pkginfos(self):
        """
        Returns a list of flatpak pkginfos that can be updated.  Unlike
        prepare_flatpak_update, this is for the convenience of displaying information
        to the user.
        """
        return _flatpak.list_updated_pkginfos(self.cache)

    def find_pkginfo(self, name, pkg_type=PKG_TYPE_ALL, remote=None):
        """
        Attempts to find and return a PkgInfo object, given a package name.  If
        pkg_type is None, looks in first apt, then flatpaks.
        """
        return self.cache.find_pkginfo(name, pkg_type, remote)

    def get_pkginfo_from_ref_file(self, file, ready_callback):
        """
        Accepts a GFile to a .flatpakref on a local path.  If the flatpak's remote
        has not been previously added to the system installation, this also adds
        it and downloads Appstream info as well, before calling ready_callback with
        the created (or existing) PkgInfo as an argument.
        """
        if self.have_flatpak:
            _flatpak.get_pkginfo_from_file(self.cache, file, ready_callback)

    def add_remote_from_repo_file(self, file, ready_callback):
        """
        Accepts a GFile to a .flatpakrepo on a local path.  Adds the remote if it
        doesn't exist already, fetches any appstream data, and then calls
        ready_callback
        """

        if self.have_flatpak:
            _flatpak.add_remote_from_repo_file(self.cache, file, ready_callback)
        else:
            ready_callback(None, "no-flatpak-support")

    def list_flatpak_remotes(self):
        """
        Returns a list of FlatpakRemoteInfos.  The remote_name can be used to match
        with PkgInfo.remote and the title is for display.
        """
        if self.have_flatpak:
            return _flatpak.list_remotes()
        else:
            return []

    def get_remote_info_for_name(self, remote_name):
        if self.have_flatpak:
            for remote in _flatpak.list_remotes():
                if remote.name == remote_name:
                    return remote

        return []

    def pkginfo_is_installed(self, pkginfo):
        """
        Returns whether or not a given package is currently installed.  This uses
        the AptCache or the FlatpakInstallation to check.
        """
        if self.inited:
            if pkginfo.pkg_hash.startswith("a"):
                return _apt.pkginfo_is_installed(pkginfo)
            elif self.have_flatpak and pkginfo.pkg_hash.startswith("f"):
                return _flatpak.pkginfo_is_installed(pkginfo)

        return False

    @print_timing
    def generate_uncached_pkginfos(self):
        """
        Flatpaks installed from .flatpakref files may not actually be in the saved
        pkginfo cache, specifically, if they're added from no-enumerate-marked remotes.
        This gets run at startup to collect and generate their info.
        """
        if self.have_flatpak:
            _flatpak.generate_uncached_pkginfos(self.cache)

    @print_timing
    def initialize_appstream(self):
        """
        Loads and caches the xmlb pools so they can be used to provide
        display info for packages.
        """
        if self.have_flatpak:
            _flatpak.initialize_appstream(cb=self.on_appstream_loaded)

        # Open the apt cache while we're in a thread.
        _apt.get_apt_cache()

    def on_appstream_loaded(self):
        self.generate_uncached_pkginfos()
        self.emit("appstream-changed")

    def get_appstream_pkg_for_pkginfo(self, pkginfo):
        backend_component = None

        if pkginfo.pkg_hash.startswith("a"):
            backend_component = _apt.search_for_pkginfo_apt_pkg(pkginfo)
            if backend_component is not None:
                self.backend_table[pkginfo] = backend_component
        else:
            backend_component = _flatpak.search_for_pkginfo_appstream_package(pkginfo)

        return backend_component

    def get_flatpak_launchables(self, pkginfo):
        """
        Return the launchables associated with the AsApp for this pkginfo.
        """

        if pkginfo.pkg_hash.startswith("a"):
            debug("launch_flatpak: pkginfo is not a flatpak")

        as_pkg = self.get_appstream_pkg_for_pkginfo(pkginfo)

        if as_pkg is None:
            return None

        return as_pkg.get_launchables()

    def get_flatpak_root_path(self):
        """
        Return the root path for the flatpak installation (generally /var/lib/flatpak for system
        and ~/.local/share/flatpak for user.
        """

        return _flatpak.get_fp_sys().get_path().get_path()

    def get_addons(self, pkginfo):
        """
        Returns an array of app ids of names of available addons
        """
        if pkginfo.pkg_hash.startswith("a"):
            return None

        addons = _flatpak._get_addons_for_pkginfo(pkginfo)

        if len(addons) == 0:
            return None

        return addons

    def get_description(self, pkginfo, for_search=False):
        """
        Returns the description of the package.  If for_search is True,
        this is the raw, unformatted string in the case of apt.
        """
        if for_search and pkginfo.pkg_hash.startswith("a"):
            try:
                return _apt._apt_cache[pkginfo.name].candidate.description
            except Exception:
                pass

        as_pkg = self.get_appstream_pkg_for_pkginfo(pkginfo)
        return pkginfo.get_description(as_pkg)

    def get_screenshots(self, pkginfo):
        """
        Returns a list of screenshot urls
        """
        as_pkg = self.get_appstream_pkg_for_pkginfo(pkginfo)

        return pkginfo.get_screenshots(as_pkg)

    def get_version(self, pkginfo):
        """
        Returns the current version string, if available
        """
        as_pkg = self.get_appstream_pkg_for_pkginfo(pkginfo)

        return pkginfo.get_version(as_pkg)

    def get_developer(self, pkginfo):
        """
        Returns the current version string, if available
        """
        as_pkg = self.get_appstream_pkg_for_pkginfo(pkginfo)

        return pkginfo.get_developer(as_pkg)

    def get_installed_version(self, pkginfo):
        """
        Returns the currently deployed version of a flatpak.
        """
        if pkginfo.pkg_hash.startswith("a"):
            # apt packages we don't really need to make a distinction.
            return self.get_version(pkginfo)
        else:
            # flatpak packages, the appstream as_pkg shows the latest version provided in the xml,
            # not the actual installed version.
            return _flatpak._get_deployed_version(pkginfo)

    def get_homepage_url(self, pkginfo):
        """
        Returns the home page url for a package.  If there is
        no url for the package, in the case of flatpak, the remote's url
        is displayed instead
        """
        as_pkg = self.get_appstream_pkg_for_pkginfo(pkginfo)

        return pkginfo.get_homepage_url(as_pkg)

    def get_help_url(self, pkginfo):
        """
        Returns the help url for a package.  If there is
        no url for the package, returns an empty string. Apt always returns
        an empty string.
        """
        as_pkg = self.get_appstream_pkg_for_pkginfo(pkginfo)

        return pkginfo.get_help_url(as_pkg)

    def is_busy(self):
        return len(self.tasks.keys()) > 0

    def get_task_count(self):
        return len(self.tasks.keys())

    def get_active_pkginfos(self):
        pkginfos = []

        for pkg_hash in self.tasks.keys():
            pkginfos.append(self.tasks[pkg_hash].pkginfo)

        return pkginfos

    def task_running(self, task):
        """
        Returns whether a given task is currently executing.
        """
        return task.pkginfo.pkg_hash in self.tasks.keys()

    def confirm_task(self, task):
        return task.confirm()

    def cancel_task(self, task):
        task.cancel()

    def execute_task(self, task):
        """
        Executes a given task.  The client_finished_cb is required always, to notify
        when the task completes. The progress and error callbacks are optional.  If
        they're left out, a standalone progress window is created to allow the user to
        see the task's progress (and cancel it if desired.)
        """

        if task.pkginfo is not None:
            key = task.pkginfo.pkg_hash
        else:
            key = "updates"

        self.tasks[key] = task

        debug("Starting task for package %s, type '%s'" % (key, task.type))

        task.execute()

    def _task_finished(self, task):
        if not task.pkginfo:
            try:
                del self.tasks["updates"]
                debug("Done with update task (success)")
            except:
                pass
        else:
            key = task.pkginfo.pkg_hash

            if key:
                try:
                    del self.tasks[key]
                    debug("Done with task (success)", key)
                except:
                    pass

        self._post_task_update(task)

    def _task_error(self, task):
        if not task.pkginfo:
            try:
                del self.tasks["updates"]
                debug("Done with update task (failure)")
            except:
                pass
        else:
            key = task.pkginfo.pkg_hash

            if key:
                try:
                    del self.tasks[key]
                    debug("Done with task (failure)", key)
                except:
                    pass

        self._post_task_update(task)

    def _post_task_update(self, task):
        if task.pkginfo and task.pkginfo.pkg_hash.startswith("a"):
            thread = threading.Thread(target=self._apt_post_task_update_thread, args=(task,))
            thread.start()
        else:
            self._run_client_callback(task)

    def _apt_post_task_update_thread(self, task):
        _apt.sync_cache_installed_states()

        # This needs to be called after reloading the apt cache, otherwise our installed
        # apps don't update correctly
        self._run_client_callback(task)

    def _run_client_callback(self, task):
        if task.client_finished_cb:
            GObject.idle_add(task.client_finished_cb, task, priority=GLib.PRIORITY_DEFAULT)
