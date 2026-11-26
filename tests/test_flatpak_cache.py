"""Cache installed end-of-life applications without advertising new installs."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'usr/lib/python3/dist-packages'))

from mintcommon.installer import _flatpak
from gi.repository import Flatpak


class FlatpakCacheTests(unittest.TestCase):
    def make_ref(self, installed, name, eol=None, **kwargs):
        properties = dict(name=name, arch=Flatpak.get_default_arch(), branch='stable',
                          kind=Flatpak.RefKind.APP, end_of_life=eol)
        properties.update(kwargs)
        if installed:
            return Flatpak.InstalledRef(origin='test', **properties)
        return Flatpak.RemoteRef(remote_name='test', **properties)

    def build_cache(self, installed_refs, remote_refs):
        remote = Flatpak.Remote.new('test')
        remote.set_url('file:///unused-test-remote')
        installation = Mock()
        installation.list_remotes.return_value = [remote]
        installation.list_remote_refs_sync.return_value = remote_refs
        installation.list_installed_refs.return_value = installed_refs
        pool = Mock()
        pool.lookup_appstream_package.return_value = None
        with patch.object(_flatpak, 'get_fp_sys', return_value=installation):
            with patch.object(_flatpak.appstream_pool, 'Pool', return_value=pool):
                return _flatpak.process_full_flatpak_installation({})[0]

    def test_installed_eol_app_remains_available_for_removal(self):
        name = 'com.github.alexhuntley.Plots'
        installed = self.make_ref(True, name, 'No longer maintained')
        remote = self.make_ref(False, name, 'No longer maintained')
        cache = self.build_cache([installed], [remote])
        info = cache[_flatpak.make_pkg_hash(installed)]
        self.assertTrue(info.installed)
        self.assertEqual(info.refid, installed.format_ref())
        self.assertEqual(info.remote, 'test')

    def test_uninstalled_eol_app_is_not_offered(self):
        ref = self.make_ref(False, 'org.example.Obsolete', 'Retired')
        self.assertEqual(self.build_cache([], [ref]), {})

    def test_supported_app_is_cached_and_marked_installed(self):
        installed = self.make_ref(True, 'org.example.Current')
        remote = self.make_ref(False, 'org.example.Current')
        cache = self.build_cache([installed], [remote])
        self.assertEqual(len(cache), 1)
        self.assertTrue(cache[_flatpak.make_pkg_hash(installed)].installed)

    def test_other_filters_still_apply_to_installed_refs(self):
        for properties in [dict(kind=Flatpak.RefKind.RUNTIME), dict(arch='unsupported'),
                           dict(name='org.example.BaseApp'),
                           dict(name='org.example.BaseExtension')]:
            with self.subTest(properties=properties):
                name = properties.pop('name', 'org.example.Obsolete')
                ref = self.make_ref(True, name, 'Retired', **properties)
                self.assertEqual(self.build_cache([ref], []), {})


if __name__ == '__main__':
    unittest.main()
