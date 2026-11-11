"""Ed25519 through the CPython TLS runtime's already loaded OpenSSL 3 provider."""

from __future__ import annotations

import ctypes
import os
import ssl
from contextlib import contextmanager
from functools import lru_cache

from .mirror_contract import MirrorError, require


@lru_cache(maxsize=1)
def library():
    # Never search/load an ambient alternate crypto implementation or execute a
    # utility. This is the library already selected by the qualified Python TLS
    # runtime, including the frozen installer's inventoried native DLLs.
    require(ssl.OPENSSL_VERSION_INFO[0] == 3, "ssh_crypto_unavailable")
    try:
        if os.name == "nt":
            from ctypes import wintypes as w

            loaded = ctypes.WinDLL("kernel32", use_last_error=True).GetModuleHandleW
            loaded.argtypes, loaded.restype = [w.LPCWSTR], w.HMODULE
            name = "libcrypto-3.dll"
            handle = loaded(name)
            if not handle:
                name = "libcrypto-3-x64.dll"
                handle = loaded(name)
            require(handle, "ssh_crypto_unavailable")
            # Windows ctypes inspects the name even when an existing handle is
            # supplied. This names that same loaded module; it never loads one.
            result = ctypes.CDLL(name, handle=handle)
        else:
            result = ctypes.CDLL("libcrypto.so.3", mode=os.RTLD_NOLOAD | os.RTLD_NOW)
        pointer, size = ctypes.c_void_p, ctypes.c_size_t
        for name in ("EVP_PKEY_new_raw_private_key_ex", "EVP_PKEY_new_raw_public_key_ex"):
            function = getattr(result, name)
            function.argtypes = [pointer, ctypes.c_char_p, ctypes.c_char_p, pointer, size]
            function.restype = pointer
        result.EVP_PKEY_free.argtypes, result.EVP_PKEY_free.restype = [pointer], None
        result.EVP_PKEY_get_raw_public_key.argtypes = [pointer, pointer, ctypes.POINTER(size)]
        result.EVP_PKEY_get_raw_public_key.restype = ctypes.c_int
        result.EVP_MD_CTX_new.argtypes, result.EVP_MD_CTX_new.restype = [], pointer
        result.EVP_MD_CTX_free.argtypes, result.EVP_MD_CTX_free.restype = [pointer], None
        for name in ("EVP_DigestSignInit", "EVP_DigestVerifyInit"):
            function = getattr(result, name)
            function.argtypes, function.restype = [pointer] * 5, ctypes.c_int
        result.EVP_DigestSign.argtypes = [pointer, pointer, ctypes.POINTER(size), pointer, size]
        result.EVP_DigestSign.restype = ctypes.c_int
        result.EVP_DigestVerify.argtypes = [pointer, pointer, size, pointer, size]
        result.EVP_DigestVerify.restype = ctypes.c_int
        return result
    except (OSError, AttributeError):
        raise MirrorError("ssh_crypto_unavailable") from None


def buffer(value):
    return (ctypes.c_ubyte * max(1, len(value))).from_buffer_copy(value or b"\0")


@contextmanager
def key(value, *, private):
    require(type(value) is bytes and len(value) == 32, "ssh_key")
    api, data = library(), buffer(value)
    create = api.EVP_PKEY_new_raw_private_key_ex if private else api.EVP_PKEY_new_raw_public_key_ex
    native = create(None, b"ED25519", None, data, len(value))
    require(native, "ssh_crypto_unavailable")
    try:
        yield api, native
    finally:
        api.EVP_PKEY_free(native)
        ctypes.memset(data, 0, len(value))


def public_key(seed):
    with key(seed, private=True) as (api, native):
        output, size = buffer(b"\0" * 32), ctypes.c_size_t(32)
        require(
            api.EVP_PKEY_get_raw_public_key(native, output, ctypes.byref(size)) == 1
            and size.value == 32,
            "ssh_crypto_unavailable",
        )
        return bytes(output)


def sign(seed, message):
    require(type(message) is bytes and len(message) <= 32768, "ssh_agent_request")
    with key(seed, private=True) as (api, native):
        context = api.EVP_MD_CTX_new()
        require(context, "ssh_crypto_unavailable")
        try:
            require(
                api.EVP_DigestSignInit(context, None, None, None, native) == 1,
                "ssh_crypto_unavailable",
            )
            output, size, data = buffer(b"\0" * 64), ctypes.c_size_t(64), buffer(message)
            require(
                api.EVP_DigestSign(context, output, ctypes.byref(size), data, len(message)) == 1
                and size.value == 64,
                "ssh_crypto_unavailable",
            )
            return bytes(output)
        finally:
            api.EVP_MD_CTX_free(context)


def verify(public, message, signature):
    require(
        type(message) is bytes
        and len(message) <= 32768
        and type(signature) is bytes
        and len(signature) == 64,
        "ssh_agent_request",
    )
    with key(public, private=False) as (api, native):
        context = api.EVP_MD_CTX_new()
        require(context, "ssh_crypto_unavailable")
        try:
            require(
                api.EVP_DigestVerifyInit(context, None, None, None, native) == 1,
                "ssh_crypto_unavailable",
            )
            result = api.EVP_DigestVerify(
                context, buffer(signature), len(signature), buffer(message), len(message)
            )
            require(result in {0, 1}, "ssh_crypto_unavailable")
            return result == 1
        finally:
            api.EVP_MD_CTX_free(context)
