"""Local private catalog export, or guarded Render catalog preflight/transfer."""

import argparse
import base64
import gzip
import io
import json
import os
from pathlib import Path
import sys

from config.safe_logging import exception_summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "check", "dry-run", "commit", "verify"], nargs="?", default="check")
    parser.add_argument("--source")
    parser.add_argument("--bundle", help="Private export directory, or input catalog.json directory/file.")
    parser.add_argument("--review", help="Explicit local selection-review JSON; no automatic exclusions.")
    parser.add_argument("--sha256", help="Independently reviewed bundle digest (not a credential).")
    args = parser.parse_args(argv)
    try:
        if os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings") != "config.settings":
            raise ValueError("Unexpected settings module")
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
        import django
        django.setup()
        from django.conf import settings
        from django.core.management.base import CommandError
        from django.db import connection
        from core.catalog_transfer import MAX_BYTES, export_catalog, load_catalog, require, transfer
        if args.action == "export":
            require(bool(args.source and args.bundle and args.review), "EXPORT_ARGUMENTS_REQUIRED")
            require(not args.sha256, "EXPORT_DOES_NOT_ACCEPT_INPUT_HASH")
            review = json.loads(Path(args.review).read_text(encoding="utf-8-sig"))
            digest, counts = export_catalog(args.source, args.bundle, review)
            payload = (Path(args.bundle) / "catalog.json").read_bytes()
            packed = base64.b64encode(gzip.compress(payload, mtime=0)).decode("ascii")
            require(len(packed) <= 65536, "RENDER_ENV_BUNDLE_TOO_LARGE_USE_REVIEWED_PRIVATE_RUNNER")
            (Path(args.bundle) / "render-env-value.txt").write_text(packed, encoding="ascii")
            print(json.dumps({"result": "EXPORTED_NO_IMPORT", "sha256": digest, "counts": counts,
                              "selection_reviewed": review["reviewed"], "packed_characters": len(packed)}))
            return 0
        require(not args.source and not args.review, "SOURCE_AND_REVIEW_ARE_EXPORT_ONLY")
        digest = args.sha256 or os.environ.get("CATALOG_BUNDLE_SHA256", "").strip()
        if args.bundle:
            path = Path(args.bundle)
            if path.is_dir():
                path = path / "catalog.json"
            with path.open("rb") as stream:
                payload = stream.read(MAX_BYTES + 1)
        else:
            packed = os.environ.get("CATALOG_BUNDLE_GZIP_B64", "").strip()
            require(bool(packed) and len(packed) <= 65536, "PRIVATE_BUNDLE_ENV_REQUIRED_OR_TOO_LARGE")
            compressed = base64.b64decode(packed, validate=True)
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                payload = stream.read(MAX_BYTES + 1)
        document = load_catalog(payload, digest)
        # Explicit approval is bound to these exact bytes. Check/verify never import.
        if args.action in {"dry-run", "commit"}:
            require(os.environ.get("CATALOG_IMPORT_APPROVED_SHA256", "").strip() == digest,
                    "EXPLICIT_IMPORT_APPROVAL_REQUIRED")
        from render_postgres import validate_target, verify_server
        validate_target(connection, settings, os.environ)
        try:
            connection.ensure_connection()
            verify_server(connection)
            receipt = transfer(document, mode=args.action)
            print(json.dumps({"bundle_sha256": digest, "selection_reviewed": document["review"].get("reviewed"), **receipt}, sort_keys=True))
        finally:
            connection.close()
    except Exception as error:
        # Never print raw exceptions, payloads, settings, URLs or credentials.
        from django.core.management.base import CommandError
        from render_postgres import Refused
        if isinstance(error, (CommandError, Refused)):
            # Only uppercase constant codes from our guards are safe to print.
            code = error.args[0] if error.args else ""
            if isinstance(code, str) and code.replace("_", "").isalnum() and code.isupper():
                print("result=REFUSED reason=" + code)
                return 1
        print("result=FAILED " + exception_summary(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
