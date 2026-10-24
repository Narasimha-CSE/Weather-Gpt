# -*- coding: utf-8 -*-
"""Tests for the email-once + captcha login, trusted devices and Google sign-in.   Run:  python test_auth_flow.py"""
import os
import tempfile
import unittest

from flask import Flask

import auth

CAPTCHA = "ABCDE"
SENT = {}


def make_app():
    tmp = tempfile.mkdtemp()
    auth.DATA_DIR = tmp
    auth.DB_PATH = os.path.join(tmp, "test.db")
    auth._pending.clear()
    auth._hits.clear()
    SENT.clear()
    auth.make_captcha_text = lambda: CAPTCHA
    auth.send_otp_email = lambda to, name, otp: SENT.__setitem__(to, otp)
    auth._fetch_profile = lambda provider, cfg, code: ("Gina Google", "gina@example.com", True)
    os.environ.update(SECRET_KEY="test-secret", GOOGLE_CLIENT_ID="id", GOOGLE_CLIENT_SECRET="secret")
    app = Flask(__name__)
    app.config["TESTING"] = True
    auth.init_auth(app)
    app.add_url_rule("/", "home", lambda: "home")
    return app


def new_captcha(c):
    r = c.get("/auth/captcha")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"
    return r


def cap_login(c, email, answer=CAPTCHA, fresh=True):
    if fresh:
        new_captcha(c)
    return c.post("/auth/login", json={"email": email, "captcha": answer})


def register(c, email, name="Ravi Kumar"):
    assert c.post("/auth/register", json={"name": name, "email": email}).status_code == 200
    return c.post("/auth/verify", json={"email": email, "otp": SENT[email]})


class AuthFlow(unittest.TestCase):
    def setUp(self):
        os.environ.pop("STRICT_NEW_DEVICE_OTP", None)
        self.app = make_app()
        self.c = self.app.test_client()

    def test_login_page_never_asks_for_otp_by_default(self):
        register(self.c, "ravi@example.com")
        other = self.app.test_client()                                       # different browser, no cookie
        r = cap_login(other, "ravi@example.com")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("otp_required", r.get_json())
        self.assertEqual(other.get("/auth/me").get_json()["user"]["email"], "ravi@example.com")
        self.assertEqual(cap_login(self.app.test_client(), "ravi@example.com", answer="WRONG").status_code, 400)
        self.assertEqual(cap_login(self.app.test_client(), "nobody@example.com").status_code, 404)

    def test_register_verifies_email_once_and_trusts_device(self):
        r = register(self.c, "ravi@example.com")
        self.assertEqual(r.status_code, 201)
        self.assertIn("wg_device=", r.headers.get("Set-Cookie", "") + "".join(r.headers.getlist("Set-Cookie")))
        self.assertEqual(self.c.get("/auth/me").status_code, 401)          # not logged in yet

    def test_captcha_login_after_registration(self):
        register(self.c, "ravi@example.com")
        r = cap_login(self.c, "ravi@example.com")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["verified"], "device")
        self.assertEqual(self.c.get("/auth/me").status_code, 200)

    def test_captcha_is_checked_and_single_use(self):
        register(self.c, "ravi@example.com")
        r = cap_login(self.c, "ravi@example.com", answer="WRONG")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.get_json()["captcha_failed"])
        self.assertEqual(self.c.get("/auth/me").status_code, 401)
        self.assertEqual(cap_login(self.c, "ravi@example.com").status_code, 200)
        self.c.post("/auth/logout")
        # same answer again without loading a new captcha must fail
        self.assertEqual(cap_login(self.c, "ravi@example.com", fresh=False).status_code, 400)
        # no captcha at all
        self.assertEqual(self.c.post("/auth/login", json={"email": "ravi@example.com"}).status_code, 400)

    def test_relogin_with_captcha_after_logout(self):
        register(self.c, "ravi@example.com")
        cap_login(self.c, "ravi@example.com")
        self.c.post("/auth/logout")
        self.assertEqual(self.c.get("/auth/me").status_code, 401)
        self.assertEqual(cap_login(self.c, "ravi@example.com").status_code, 200)

    def test_strict_mode_new_device_needs_the_email_code_once(self):
        os.environ["STRICT_NEW_DEVICE_OTP"] = "1"
        register(self.c, "ravi@example.com")
        other = self.app.test_client()                                       # a different browser
        r = cap_login(other, "ravi@example.com")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["otp_required"])
        self.assertEqual(other.get("/auth/me").status_code, 401)             # captcha alone is NOT enough here
        self.assertEqual(other.post("/auth/verify", json={"email": "ravi@example.com", "otp": "000000"}).status_code, 400)
        ok = other.post("/auth/verify", json={"email": "ravi@example.com", "otp": SENT["ravi@example.com"]})
        self.assertEqual(ok.status_code, 200)
        other.post("/auth/logout")
        self.assertEqual(cap_login(other, "ravi@example.com").status_code, 200)   # now captcha is enough

    def test_strict_mode_forged_or_foreign_device_cookie_is_not_trusted(self):
        os.environ["STRICT_NEW_DEVICE_OTP"] = "1"
        register(self.c, "ravi@example.com")
        self.c.set_cookie("wg_device", "garbage")                            # forged cookie
        r = cap_login(self.c, "ravi@example.com")
        self.assertTrue(r.get_json().get("otp_required"))
        self.assertEqual(self.c.get("/auth/me").status_code, 401)
        auth._pending.clear()                                                # (skip the 30 s resend gap)
        mira = self.app.test_client()                                        # trusted for Mira only
        register(mira, "mira@example.com", "Mira Rao")
        r = cap_login(mira, "ravi@example.com")
        self.assertTrue(r.get_json().get("otp_required"))
        self.assertEqual(mira.get("/auth/me").status_code, 401)

    def test_unknown_email(self):
        self.assertEqual(cap_login(self.c, "nobody@example.com").status_code, 404)

    def test_rate_limit(self):
        codes = [cap_login(self.c, "ravi@example.com", answer="XXXXX").status_code for _ in range(12)]
        self.assertIn(429, codes)

    def test_google_login_then_captcha_login(self):
        r = self.c.get("/auth/social/google")
        self.assertEqual(r.status_code, 302)
        self.assertIn("accounts.google.com", r.headers["Location"])
        with self.c.session_transaction() as s:
            state = s["oauth_state"]
        r = self.c.get("/auth/social/google/callback?code=abc&state=" + state)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/?welcome=1"))
        self.assertEqual(self.c.get("/auth/me").get_json()["user"]["email"], "gina@example.com")
        self.assertNotIn("log in", (r.get_data(as_text=True) or "").lower())
        self.c.post("/auth/logout")
        r = cap_login(self.c, "gina@example.com")                            # valid with the captcha
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["verified"], "device")
        # any browser can log in to the Google account with email + captcha
        self.assertEqual(cap_login(self.app.test_client(), "gina@example.com").status_code, 200)

    def test_google_state_is_checked(self):
        self.c.get("/auth/social/google")
        r = self.c.get("/auth/social/google/callback?code=abc&state=wrong")
        self.assertIn("social_error=failed", r.headers["Location"])
        self.assertEqual(self.c.get("/auth/me").status_code, 401)

    def test_public_and_private_routes(self):
        self.assertEqual(self.c.get("/auth/captcha").status_code, 200)
        self.assertEqual(self.c.get("/").status_code, 302)                   # home needs login
        self.assertEqual(self.c.get("/api/anything").status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
