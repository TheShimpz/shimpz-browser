"""Behavior contracts for the defensive KasmVNC HTML patcher."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "image" / "rootfs" / "usr" / "local" / "bin" / "shimpz-kasm-patch"


def _load_patcher():
    loader = importlib.machinery.SourceFileLoader("shimpz_kasm_patch_test_target", str(PATCHER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError(f"cannot load {PATCHER}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


PATCH = _load_patcher()
IFRAME = (
    '<iframe class="vnc" src="vnc/index.html?autoconnect=1&resize=remote&clipboard_up=true'
    "&clipboard_down=true&clipboard_seamless=true&show_control_bar=true"
    '<% if(path){ %><%- path -%><% } %>"></iframe>'
)


class KasmPatchTest(unittest.TestCase):
    def test_kasm_client_patch_is_idempotent_and_anchor_gated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / "kasm.html"
            page.write_text(f"<html><head>{PATCH.ANCHOR}</head><body>desktop</body></html>")
            PATCH.PAGE = str(page)

            PATCH._patch_kasm()
            PATCH._patch_kasm()

            patched = page.read_text()
            self.assertEqual(patched.count(PATCH.START), 1)
            self.assertIn(PATCH.END, patched)
            self.assertIn('view_only:"true"', patched)
            self.assertIn("#noVNC_control_bar_anchor{display:none", patched)

            changed_client = Path(directory) / "changed.html"
            original = "<html><head>different client</head></html>"
            changed_client.write_text(original)
            PATCH.PAGE = str(changed_client)
            PATCH._patch_kasm()
            self.assertEqual(changed_client.read_text(), original)

    def test_kclient_patch_preserves_the_iframe_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / "kclient.html"
            page.write_text(f"<body>\n{IFRAME}\n</body>")
            PATCH.KCLIENT = str(page)

            PATCH._patch_kclient()
            PATCH._patch_kclient()

            patched = page.read_text()
            self.assertEqual(patched.count(PATCH.VO_START), 1)
            self.assertIn(PATCH.VO_END, patched)
            self.assertIn(IFRAME, patched)
            self.assertGreater(patched.index(PATCH.VO_START), patched.index("</iframe>"))
            self.assertIn("URLSearchParams", patched)
            self.assertIn("(0|no|off|false)", patched)

    def test_missing_or_changed_targets_are_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            changed_client = Path(directory) / "changed.html"
            original = "<html><body>no vnc here</body></html>"
            changed_client.write_text(original)
            PATCH.KCLIENT = str(changed_client)
            PATCH._patch_kclient()
            self.assertEqual(changed_client.read_text(), original)

            PATCH.PAGE = str(Path(directory) / "missing-kasm.html")
            PATCH.KCLIENT = str(Path(directory) / "missing-kclient.html")
            PATCH._patch_kasm()
            PATCH._patch_kclient()


if __name__ == "__main__":
    unittest.main()
