"""Static serving of the built React app from the Python dashboard server (one URL for the demo)."""
import http.client
import importlib.util
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("dashboard_static_server", Path(__file__).resolve().parents[1] / "server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class StaticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        dist = Path(self.tmp.name) / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>BUILT</html>")
        (dist / "assets" / "app-1.js").write_text("console.log(1)")
        (dist / "assets" / "app-1.css").write_text("body{}")
        (dist / "assets" / "notes.txt").write_text("nope")
        (Path(self.tmp.name) / "secret.js").write_text("SECRET")
        self.patch = patch.object(server, "DIST", str(dist))
        self.patch.start()
        self.http = HTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.patch.stop()
        self.tmp.cleanup()

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.http.server_port)
        c.request("GET", path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, r.getheader("Content-Type"), body

    def test_root_serves_built_index(self):
        status, kind, body = self.get("/")
        self.assertEqual((status, b"BUILT" in body), (200, True))

    def test_assets_served_with_types(self):
        self.assertEqual(self.get("/assets/app-1.js")[:2], (200, "text/javascript; charset=utf-8"))
        self.assertEqual(self.get("/assets/app-1.css")[:2], (200, "text/css; charset=utf-8"))

    def test_traversal_and_odd_names_refused(self):
        for bad in ("/assets/../secret.js", "/assets/%2e%2e/secret.js", "/assets/..%2fsecret.js", "/assets/notes.txt",
                    "/assets//etc/passwd", "/assets/.hidden.js", "/assets/missing.js", "/assets/a%00.js"):
            self.assertEqual(self.get(bad)[0], 404, bad)

    def test_without_build_root_falls_back_and_assets_404(self):
        with patch.object(server, "DIST", self.tmp.name + "/nodist"):
            self.assertEqual(self.get("/assets/app-1.js")[0], 404)
            self.assertIn(self.get("/")[0], (200, 404))


if __name__ == "__main__":
    unittest.main()
