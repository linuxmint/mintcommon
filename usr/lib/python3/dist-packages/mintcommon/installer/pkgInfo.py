import sys
if sys.version_info.major < 3:
    raise "python3 required"
import os

import gi
gi.require_version("AppStream", "1.0")
gi.require_version("Gtk", "3.0")
from gi.repository import AppStream, Gtk

# this should hopefully be supplied by remote info someday.
FLATHUB_MEDIA_BASE_URL = "https://dl.flathub.org/media/"

def capitalize(string):
    if string and len(string) > 1:
        return (string[0].upper() + string[1:])
    else:
        return (string)

class PkgInfo:
    __slots__ = (
        "name",
        "pkg_hash",
        "refid",
        "remote",
        "kind",
        "arch",
        "branch",
        "commit",
        "remote_url",
        "display_name",
        "summary",
        "description",
        "version",
        "icon",
        "screenshots",
        "homepage_url",
        "help_url",
        "categories",
        "cached_display_name",
        "cached_summary",
        "cached_icon",
        "installed",
        "verified",
        "developer"
    )

    def __init__(self, pkg_hash=None):
        # Saved stuff
        self.pkg_hash = None
        if pkg_hash:
            self.pkg_hash = pkg_hash

        self.name = None
        # some flatpak-specific things
        self.refid = ""
        self.remote = ""
        self.kind = 0
        self.arch = ""
        self.branch = ""
        self.commit = ""
        self.remote_url = ""
        # We need these at minimum for a nice startup state before appstream is loaded.
        self.cached_display_name = None
        self.cached_summary = None
        self.cached_icon = None

        # Display info fetched by methods always
        self.display_name = None
        self.summary = None
        self.description = None
        self.version = None
        self.icon = {}
        self.screenshots = []
        self.homepage_url = None
        self.help_url = None

        # Runtime categories
        self.categories = []

class AptPkgInfo(PkgInfo):
    def __init__(self, pkg_hash=None, apt_pkg=None):
        super(AptPkgInfo, self).__init__(pkg_hash)

        # This is cheap.. but keeps from having an additional fp/apt check every time we check it.
        self.verified = True

        if apt_pkg:
            self.name = apt_pkg.name
            self.display_name = self.get_display_name(apt_pkg)
            self.summary = self.get_summary(apt_pkg)
            self.get_icon(apt_pkg, 48)
            self.get_icon(apt_pkg, 64)

    @classmethod
    def from_json(cls, json_data:dict):
        inst = cls()
        inst.pkg_hash = json_data["pkg_hash"]
        inst.name = json_data["name"]
        inst.display_name = json_data["display_name"]
        inst.summary = json_data["summary"]

        try:
            cached = json_data["icon"]

            while True:
                size, icon = cached.popitem()
                inst.icon[int(size)] = icon
        except Exception as e:
            pass

        return inst

    def to_json(self):
        trimmed_dict = {
            key: getattr(self, key, None)
                for key in ("pkg_hash",
                            "name",
                            "display_name",
                            "summary",
                            "icon")
            }

        return trimmed_dict

    def get_display_name(self, apt_pkg=None):
        # fastest
        if self.display_name:
            return self.display_name

        if apt_pkg:
            self.display_name = apt_pkg.name.capitalize()

        if not self.display_name:
            self.display_name = self.name.capitalize()

        self.display_name = self.display_name.replace(":i386", "")

        return self.display_name

    def get_summary(self, apt_pkg=None):
        # fastest
        if self.summary:
            return self.summary

        if apt_pkg and apt_pkg.candidate:
            candidate = apt_pkg.candidate

            summary = ""
            if candidate.summary is not None:
                summary = candidate.summary

                self.summary = capitalize(summary)

        if self.summary is None:
            self.summary = ""

        return self.summary

    def get_description(self, apt_pkg=None):
        # fastest
        if self.description:
            return self.description

        if apt_pkg and apt_pkg.candidate:
            candidate = apt_pkg.candidate

            description = ""
            if candidate.description is not None:
                description = candidate.description
                description = description.replace("<p>", "").replace("</p>", "\n")
                for tags in ["<ul>", "</ul>", "<li>", "</li>"]:
                    description = description.replace(tags, "")

                self.description = capitalize(description)

        if self.description is None:
            self.description = ""

        return self.description

    def get_icon(self, apt_pkg=None, size=64):
        try:
            return self.icon[size]
        except:
            pass

        theme = Gtk.IconTheme.get_default()

        for name in [self.name, self.name.split(":")[0], self.name.split("-")[0], self.name.split(".")[-1].lower()]:
            if theme.has_icon(name):
                self.icon[size] = name
                return self.icon[size]

        # Look in app-install-data and pixmaps
        for extension in ['svg', 'png', 'xpm']:
            for suffix in ['', '-icon']:
                icon_path = "/usr/share/app-install/icons/%s%s.%s" % (self.name, suffix, extension)
                if os.path.exists(icon_path):
                    self.icon[size] = icon_path
                    return self.icon[size]

                icon_path = "/usr/share/pixmaps/%s.%s" % (self.name, extension)
                if os.path.exists(icon_path):
                    self.icon[size] = icon_path
                    return self.icon[size]

        return None

    def get_screenshots(self, apt_pkg=None):
        return [] # handled in mintinstall for now

    def get_version(self, apt_pkg=None):
        if self.version:
            return self.version

        if apt_pkg:
            if apt_pkg.is_installed:
                self.version = apt_pkg.installed.version
            else:
                self.version = apt_pkg.candidate.version

        if self.version is None:
            self.version = ""

        return self.version

    def get_homepage_url(self, apt_pkg=None):
        if self.homepage_url:
            return self.homepage_url

        if apt_pkg:
            if apt_pkg.is_installed:
                self.homepage_url = apt_pkg.installed.homepage
            else:
                self.homepage_url = apt_pkg.candidate.homepage

        if self.homepage_url is None:
            self.homepage_url = ""

        return self.homepage_url

    def get_help_url(self, apt_pkg=None):
        # We can only get the homepage from apt
        return ""

class FlatpakPkgInfo(PkgInfo):
    def __init__(self, pkg_hash=None, remote=None, ref=None, remote_url=None, installed=False):
        super(FlatpakPkgInfo, self).__init__(pkg_hash)

        if not pkg_hash:
            return

        self.name = ref.get_name() # org.foo.Bar
        self.remote = remote # "flathub"
        self.remote_url = remote_url

        self.installed = installed

        self.refid = ref.format_ref() # app/org.foo.Bar/x86_64/stable
        self.kind = ref.get_kind() # Will be app for now
        self.arch = ref.get_arch()
        self.branch = ref.get_branch()
        self.commit = ref.get_commit()

    @classmethod
    def from_json(cls, json_data:dict):
        inst = cls()
        inst.pkg_hash = json_data["pkg_hash"]
        inst.name = json_data["name"]
        inst.refid = json_data["refid"]
        inst.remote = json_data["remote"]
        inst.kind = json_data["kind"]
        inst.arch = json_data["arch"]
        inst.branch = json_data["branch"]
        inst.commit = json_data["commit"]
        inst.remote_url = json_data["remote_url"]
        inst.verified = json_data["verified"]
        inst.developer = json_data["developer"]

        try:
            inst.cached_display_name = json_data["cached_display_name"]
        except:
            pass
        try:
            inst.cached_summary = json_data["cached_summary"]
        except:
            pass
        try:
            cached = json_data["cached_icon"]
            size, icon = cached.popitem()
            inst.cached_icon = { int(size): icon }
        except Exception as e:
            pass
        return inst

    def to_json(self):
        trimmed_dict = {
            key: getattr(self, key, None)
                for key in ("pkg_hash",
                            "name",
                            "refid",
                            "remote",
                            "kind",
                            "arch",
                            "branch",
                            "commit",
                            "remote_url",
                            "verified",
                            "developer")
            }

        if self.display_name is not None:
            trimmed_dict["cached_display_name"] = self.display_name
        if self.summary is not None:
            trimmed_dict["cached_summary"] = self.summary
        if len(self.icon.keys()) > 0:
            trimmed_dict["cached_icon"] = self.icon

        return trimmed_dict

    def add_cached_ascomp_data(self, ascomp):
        self.cached_display_name = self.get_display_name(ascomp)
        self.cached_summary = self.get_summary(ascomp)
        self.cached_icon = self.get_icon(ascomp, 48)
        self.developer = ascomp.get_project_group()

    def get_display_name(self, as_component=None):
        # fastest
        if self.display_name:
            return self.display_name

        if as_component:
            display_name = as_component.get_name()

            if display_name is not None:
                self.display_name = capitalize(display_name)

        if self.display_name is None:
            if self.cached_display_name is not None:
                return self.cached_display_name
            else:
                return self.name

        return self.display_name

    def get_summary(self, as_component=None):
        # fastest
        if self.summary:
            return self.summary

        if as_component:
            summary = as_component.get_summary()

            if summary is not None:
                self.summary = summary

        if self.summary is None:
            if self.cached_summary is not None:
                return self.cached_summary
            else:
                return ""

        return self.summary

    def get_description(self, as_component=None):
        # fastest
        if self.description:
            return self.description

        if as_component:
            description = as_component.get_description()

            if description is not None:
                try:
                    self.description = AppStream.markup_convert(description, AppStream.MarkupKind.TEXT)
                except GLib.Error as e:
                    warn("Could not convert description to text: %s" % e.message)
                    self.description = description

        if self.description is None:
            return ""

        return self.description

    def get_icon(self, as_component=None, size=64):
        try:
            return self.icon[size]
        except:
            pass

        if as_component:
            icons = as_component.get_icons()

            if icons:
                icon_to_use = None
                remote_icon = None
                local_exists_icon = None
                good_size_icon = None

                for icon in icons:
                    if icon.get_kind() == AppStream.IconKind.REMOTE:
                        remote_icon = icon
                        continue

                    if icon.get_kind() in (AppStream.IconKind.LOCAL,  \
                                           AppStream.IconKind.CACHED, \
                                           AppStream.IconKind.STOCK):
                        test_path = icon.get_filename()
                        if test_path is None or (not os.path.exists(test_path)):
                            continue
                        else:
                            local_exists_icon = icon

                        if size <= icon.get_height() or ("%dx%d" % (size, size)) in icon.get_prefix():
                            good_size_icon = icon
                            break

                icon_to_use = good_size_icon or local_exists_icon or remote_icon
                if icon_to_use is not None:
                    kind = icon_to_use.get_kind()

                    if kind != AppStream.IconKind.REMOTE:
                        self.icon[size] = icon_to_use.get_filename()
                    else:
                        url = icon_to_use.get_url()
                        if not url.startswith("http") and self.remote == "flathub":
                            url = FLATHUB_MEDIA_BASE_URL + url
                        self.icon[size] = url
                else:
                    # All else fails, try using the package's name (which icon names should match for flatpaks).
                    # You may end up with a third-party icon, but it's better than none.
                    self.icon[size] = self.name

        try:
            return self.icon[size]
        except:
            if self.cached_icon is not None:
                try:
                    return self.cached_icon[size]
                except:
                    pass

                return None

    def get_screenshots(self, as_component=None):
        if len(self.screenshots) > 0:
            return self.screenshots

        if as_component:
            # compatibility with libappstream < 1.0.0
            try:
                self.screenshots = as_component.get_screenshots_all()
            except AttributeError:
                self.screenshots = as_component.get_screenshots()

        return self.screenshots

    def get_version(self, as_component=None):
        if self.version:
            # as_component.get_release_default().get_version()
            return self.version

        if as_component:
            # compatibility with libappstream < 1.0.0
            try:

                releases = as_component.get_releases_plain().get_entries()
            except AttributeError:
                releases = as_component.get_releases()

            if len(releases) > 0:
                releases.sort(key=lambda r: r.get_timestamp(), reverse=True)
                version = releases[0].get_version()

                if version:
                    self.version = version

        if self.version is None:
            return ""

        return self.version

    def get_homepage_url(self, as_component=None):
        if self.homepage_url:
            return self.homepage_url

        if as_component:
            url = as_component.get_url(AppStream.UrlKind.HOMEPAGE)

            if url is not None:
                self.homepage_url = url

        if self.homepage_url is None:
            return ""

        return self.homepage_url

    def get_help_url(self, as_component=None):
        if self.help_url:
            return self.help_url

        if as_component:
            url = as_component.get_url(AppStream.UrlKind.HELP)

            if url is not None:
                self.help_url = url

        if self.help_url is None:
            return ""

        return self.help_url

