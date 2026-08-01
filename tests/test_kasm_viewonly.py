"""Execute the exact Kasm view-only forwarding JavaScript with Node.js 24."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_kasm_patch import PATCH

NODE_IMAGE = "node:24-slim@sha256:235600a8101ab264e117b1768e925532262668dc9b581ef1dd7d96ced463b8e7"
IFRAME = '<iframe class="vnc" src="vnc/index.html?autoconnect=1&resize=remote&show_control_bar=true"></iframe>'
BASE = "vnc/index.html?autoconnect=1&resize=remote&show_control_bar=true"


def _node_command() -> list[str]:
    node = shutil.which("node")
    if node is not None:
        version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10, check=False)
        if version.returncode == 0 and version.stdout.startswith("v24."):
            return [node]
    docker = ["docker", "run", "--rm", "--interactive", "--network", "none", "--read-only", NODE_IMAGE, "node"]
    socket = Path("/var/run/docker.sock")
    sg = shutil.which("sg")
    if socket.exists() and not os.access(socket, os.R_OK | os.W_OK) and sg is not None:
        return [sg, "docker", "-c", shlex.join(docker)]
    return docker


class KasmViewOnlyJavascriptTest(unittest.TestCase):
    def test_forwarding_preserves_default_and_normalizes_explicit_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory) / "kclient.html"
            page.write_text(f"<body>\n{IFRAME}\n</body>")
            PATCH.KCLIENT = str(page)
            PATCH._patch_kclient()
            patched = page.read_text()

        segment = patched[patched.index(PATCH.VO_START) + len(PATCH.VO_START) : patched.index(PATCH.VO_END)]
        javascript = segment[segment.index(">") + 1 : segment.rindex("</script>")]
        cases = [
            {"q": "", "base": BASE},
            {"q": "?view_only=true", "base": BASE},
            {"q": "?view_only=false", "base": BASE},
            {"q": "?view_only=0", "base": BASE},
            {"q": "?a=1&view_only=no", "base": BASE},
            {"q": "?view_only=false", "base": f"{BASE}&view_only=true"},
        ]
        harness = (
            "if (process.versions.node.split('.')[0] !== '24') throw new Error('Node 24 is required');\n"
            f"const CASES = {json.dumps(cases)};\n"
            f"const INNER = {json.dumps(javascript)};\n"
            "function makeFrame(base){ return { _s: base, getAttribute(k){ return k==='src' ? this._s : null; },"
            " get src(){ return this._s; }, set src(v){ this._s = v; } }; }\n"
            "const out = [];\n"
            "for (const c of CASES) { global.location = { search: c.q }; const frame = makeFrame(c.base);"
            " global.document = { querySelector: () => frame }; eval(INNER); out.push(frame.src); }\n"
            "console.log(JSON.stringify(out));\n"
        )

        result = subprocess.run(_node_command(), input=harness, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-1000:])
        output = json.loads(result.stdout.strip().splitlines()[-1])

        self.assertEqual(output[0], BASE)
        self.assertEqual(output[1], f"{BASE}&view_only=true")
        self.assertEqual(output[2], f"{BASE}&view_only=false")
        self.assertEqual(output[3], f"{BASE}&view_only=false")
        self.assertEqual(output[4], f"{BASE}&view_only=false")
        self.assertIn("view_only=false", output[5])
        self.assertNotIn("view_only=true", output[5])


if __name__ == "__main__":
    unittest.main()
