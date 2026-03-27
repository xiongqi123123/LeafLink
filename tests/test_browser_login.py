from __future__ import annotations

import unittest

import bootstrap
from leaflink.auth.browser_login import (
    detect_base_url,
    has_supported_cookies,
    is_project_dashboard,
    is_supported_cookie_domain,
    select_relevant_cookies,
)


class BrowserLoginTests(unittest.TestCase):
    def test_select_relevant_cookies_filters_supported_hosts(self) -> None:
        cookies = select_relevant_cookies(
            [
                {
                    "name": "sharelatex.sid",
                    "value": "abc",
                    "domain": ".www.overleaf.com",
                },
                {
                    "name": "XSRF-TOKEN",
                    "value": "token",
                    "domain": "cn.overleaf.com",
                },
                {
                    "name": "ga",
                    "value": "ignored",
                    "domain": ".www.overleaf.com",
                },
                {
                    "name": "sharelatex.sid",
                    "value": "ignored-host",
                    "domain": ".example.com",
                },
            ]
        )
        self.assertEqual(
            [(cookie.name, cookie.domain) for cookie in cookies],
            [("sharelatex.sid", ".www.overleaf.com"), ("XSRF-TOKEN", "cn.overleaf.com")],
        )

    def test_detect_base_url_uses_final_supported_host(self) -> None:
        base_url = detect_base_url(
            ["https://www.overleaf.com/login", "https://cn.overleaf.com/project"],
            fallback="https://www.overleaf.com",
        )
        self.assertEqual(base_url, "https://cn.overleaf.com")

    def test_project_dashboard_detection_and_supported_cookie_detection(self) -> None:
        self.assertTrue(
            is_project_dashboard(["https://cn.overleaf.com/project", "https://cn.overleaf.com/project/abc"])
        )
        self.assertTrue(is_supported_cookie_domain("overleaf.com"))
        self.assertTrue(
            has_supported_cookies(
                [
                    {"name": "custom_session", "domain": ".overleaf.com"},
                ]
            )
        )
