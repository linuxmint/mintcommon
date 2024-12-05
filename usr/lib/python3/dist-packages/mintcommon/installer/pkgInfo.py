import sys
if sys.version_info.major < 3:
    raise "python3 required"
import os

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .misc import warn, xml_markup_convert_to_text

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
        "installed",
        "verified",
        "developer",
        "keywords"
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

        # Display info fetched by methods always
        self.display_name = None
        self.summary = None
        self.description = None
        self.developer = None
        self.version = None
        self.icon = {}
        self.screenshots = []
        self.homepage_url = None
        self.help_url = None
        self.keywords = None

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

    def get_keywords(self):
        return ""

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
                if apt_pkg.candidate is not None:
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
                if apt_pkg.candidate is not None:
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
        self.verified = False

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
        inst.display_name = json_data["display_name"]
        inst.summary = json_data["summary"]
        inst.icon = json_data["icon"]
        inst.keywords = json_data["keywords"]
        return inst

    def to_json(self):
        trimmed_dict = {
            key: getattr(self, key, None)
                for key in (
                    "pkg_hash",
                    "name",
                    "refid",
                    "remote",
                    "kind",
                    "arch",
                    "branch",
                    "commit",
                    "remote_url",
                    "verified",
                    "display_name",
                    "summary",
                    "icon",
                    "keywords"
                )
            }

        return trimmed_dict

    def add_cached_appstream_data(self, as_pkg):
        if as_pkg:
            self.display_name = as_pkg.get_display_name()

            summary = as_pkg.get_summary()
            if summary is None:
                summary = ""

            self.summary = summary
            self.icon["48"] = as_pkg.get_icon(48)
            self.verified = as_pkg.get_verified()

            try:
                self.keywords = ",".join(as_pkg.get_keywords())
            except TypeError:
                self.keywords = ""
        else:
            self.display_name = self.name
            self.summary = ""
            self.icon = {}
            self.verified = False
            self.keywords = ""

    def get_display_name(self):
        return self.display_name

    def get_summary(self):
        return self.summary

    def get_description(self, as_pkg=None):
        if self.description:
            return self.description

        if as_pkg:
            description = as_pkg.get_description()
            if description is not None:
                self.description = xml_markup_convert_to_text(description)

        if self.description is None:
            return ""

        return self.description

    def get_keywords(self):
        return self.keywords

    def get_icon(self, size=64, as_pkg=None):
        try:
            return self.icon[str(size)]
        except KeyError:
            pass

        if as_pkg:
            icon = as_pkg.get_icon(size)
            if icon:
                self.icon[str(size)] = icon
                return icon

        return None

    def get_screenshots(self, as_pkg=None):
        if len(self.screenshots) > 0:
            return self.screenshots

        if as_pkg:
            self.screenshots = as_pkg.get_screenshots()

        return self.screenshots

    def get_version(self, as_pkg=None):
        if self.version:
            return self.version

        if as_pkg:
            version = as_pkg.get_version()
            if version:
                self.version = version

        if self.version is None:
            return ""

        return self.version

    def get_developer(self, as_pkg=None):
        if self.developer:
            return self.developer

        if as_pkg:
            self.developer = as_pkg.get_developer()

        if self.developer is None:
            return ""

        return self.developer

    def get_homepage_url(self, as_pkg=None):
        if self.homepage_url:
            return self.homepage_url

        if as_pkg:
            url = as_pkg.get_homepage_url()

            if url is not None:
                self.homepage_url = url

        if self.homepage_url is None:
            return ""

        return self.homepage_url

    def get_help_url(self, as_pkg=None):
        if self.help_url:
            return self.help_url

        if as_pkg:
            url = as_pkg.get_help_url()

            if url is not None:
                self.help_url = url

        if self.help_url is None:
            return ""

        return self.help_url

