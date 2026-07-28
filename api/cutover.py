"""Lossless, checksummed application-data and media cutover bundles."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

from django.apps import apps
from django.core import serializers
from django.core.files import File
from django.core.files.storage import default_storage
from django.core.management.base import CommandError
from django.core.management.color import no_style
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BUNDLE_FORMAT_VERSION = 1
MANIFEST_MEMBER = "manifest.json"
DATA_MEMBER = "database/business-data.json"
MEDIA_PREFIX = "media/"
COPY_CHUNK_SIZE = 1024 * 1024

# Ordered by foreign-key dependency. These are the records that belong to the
# application and must survive a database-engine cutover.
BUSINESS_MODEL_LABELS = (
    "accounts.user",
    "auth.group",
    "services.service",
    "appointments.bookingdaylock",
    "appointments.appointment",
    "blog.blogpost",
    "gallery.galleryimage",
    "api.promotion",
    "api.contactmessage",
    "api.adminnote",
    "admin.logentry",
)

# These tables are intentionally rebuilt or discarded on the new environment.
EXCLUDED_DATA = (
    "django_migrations (recreated by migrate)",
    "django_content_type and auth_permission (recreated by migrate)",
    "django_session (ephemeral login sessions)",
    "token_blacklist_outstandingtoken and token_blacklist_blacklistedtoken "
    "(ephemeral JWT state; users sign in again after cutover)",
)


def business_models():
    return tuple(apps.get_model(label) for label in BUSINESS_MODEL_LABELS)


def business_counts():
    return {
        label: apps.get_model(label)._default_manager.count()
        for label in BUSINESS_MODEL_LABELS
    }


def serialize_business_data():
    def objects():
        for model in business_models():
            primary_key = model._meta.pk.name
            yield from model._default_manager.order_by(primary_key).iterator()

    payload = serializers.serialize(
        "json",
        objects(),
        indent=2,
        use_natural_foreign_keys=True,
    )
    return payload.encode("utf-8")


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _safe_media_name(name):
    normalized = str(name).replace("\\", "/").lstrip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise CommandError(f"Unsafe media path: {name!r}")
    return path.as_posix()


def iter_storage_files(storage=default_storage, directory=""):
    try:
        directories, files = storage.listdir(directory)
    except (NotImplementedError, OSError) as exc:
        raise CommandError(
            "The configured media storage cannot list all files. "
            "Use a storage backend with listdir support for cutover export."
        ) from exc

    for filename in sorted(files):
        name = f"{directory}/{filename}" if directory else filename
        yield _safe_media_name(name)
    for child in sorted(directories):
        name = f"{directory}/{child}" if directory else child
        yield from iter_storage_files(storage, _safe_media_name(name))


def _copy_and_hash(source, target):
    digest = hashlib.sha256()
    size = 0
    while True:
        chunk = source.read(COPY_CHUNK_SIZE)
        if not chunk:
            break
        target.write(chunk)
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def export_bundle(
    output_path,
    storage=default_storage,
    *,
    maintenance_confirmed=False,
):
    if not maintenance_confirmed:
        raise CommandError(
            "Export requires maintenance mode so database records and media cannot "
            "change during the snapshot. Stop application writes, then pass the "
            "explicit maintenance confirmation."
        )

    output_path = Path(output_path).expanduser().resolve()
    if output_path.exists():
        raise CommandError(f"Refusing to overwrite existing bundle: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with transaction.atomic():
        counts = business_counts()
        data = serialize_business_data()
    manifest = {
        "format": "beautiful-brows-cutover",
        "format_version": BUNDLE_FORMAT_VERSION,
        "created_at": timezone.now().isoformat(),
        "source_database_vendor": connection.vendor,
        "models": counts,
        "database": {
            "member": DATA_MEMBER,
            "size": len(data),
            "sha256": sha256_bytes(data),
        },
        "media": [],
        "excluded": list(EXCLUDED_DATA),
        "confidential": (
            "This archive contains personal data and password hashes. "
            "Store and transfer it as a secret."
        ),
    }

    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.name}.",
            suffix=".partial",
            dir=output_path.parent,
            delete=False,
        ) as temporary_file:
            temporary_name = temporary_file.name

        with zipfile.ZipFile(
            temporary_name,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            archive.writestr(DATA_MEMBER, data)
            for media_name in iter_storage_files(storage):
                member = f"{MEDIA_PREFIX}{media_name}"
                with storage.open(media_name, "rb") as source:
                    with archive.open(member, "w") as target:
                        size, checksum = _copy_and_hash(source, target)
                manifest["media"].append(
                    {
                        "path": media_name,
                        "member": member,
                        "size": size,
                        "sha256": checksum,
                    }
                )

            archive.writestr(
                MANIFEST_MEMBER,
                json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
            )

        os.replace(temporary_name, output_path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)

    return manifest


def _read_json_member(archive, member):
    try:
        with archive.open(member) as source:
            return json.load(source)
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CommandError(f"Invalid or missing {member} in cutover bundle.") from exc


def _hash_archive_member(archive, member):
    digest = hashlib.sha256()
    size = 0
    try:
        with archive.open(member) as source:
            while True:
                chunk = source.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except KeyError as exc:
        raise CommandError(f"Bundle member is missing: {member}") from exc
    return size, digest.hexdigest()


def validate_bundle(bundle_path):
    bundle_path = Path(bundle_path).expanduser().resolve()
    if not bundle_path.is_file():
        raise CommandError(f"Cutover bundle does not exist: {bundle_path}")

    try:
        archive = zipfile.ZipFile(bundle_path, mode="r")
    except zipfile.BadZipFile as exc:
        raise CommandError("Cutover bundle is not a valid ZIP archive.") from exc

    with archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise CommandError("Cutover bundle contains duplicate member names.")

        manifest = _read_json_member(archive, MANIFEST_MEMBER)
        if (
            manifest.get("format") != "beautiful-brows-cutover"
            or manifest.get("format_version") != BUNDLE_FORMAT_VERSION
        ):
            raise CommandError("Unsupported cutover bundle format or version.")

        if set(manifest.get("models", {})) != set(BUSINESS_MODEL_LABELS):
            raise CommandError("Bundle model inventory does not match this application.")

        database = manifest.get("database", {})
        if database.get("member") != DATA_MEMBER:
            raise CommandError("Bundle database member is invalid.")
        data_size, data_checksum = _hash_archive_member(archive, DATA_MEMBER)
        if (
            data_size != database.get("size")
            or data_checksum != database.get("sha256")
        ):
            raise CommandError("Business-data checksum verification failed.")

        with archive.open(DATA_MEMBER) as source:
            try:
                fixture = json.load(source)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise CommandError("Business-data fixture is not valid JSON.") from exc
        if not isinstance(fixture, list):
            raise CommandError("Business-data fixture must be a JSON list.")

        raw_fixture_counts = Counter(item.get("model") for item in fixture)
        if set(raw_fixture_counts) - set(BUSINESS_MODEL_LABELS):
            raise CommandError("Business-data fixture contains an unexpected model.")
        fixture_counts = {
            label: raw_fixture_counts.get(label, 0)
            for label in BUSINESS_MODEL_LABELS
        }
        if fixture_counts != manifest["models"]:
            raise CommandError("Business-data model counts do not match the manifest.")
        if any(item.get("pk") is None for item in fixture):
            raise CommandError("Every exported business record must retain its primary key.")

        expected_members = {MANIFEST_MEMBER, DATA_MEMBER}
        seen_media_paths = set()
        for media in manifest.get("media", []):
            path = _safe_media_name(media.get("path", ""))
            member = f"{MEDIA_PREFIX}{path}"
            if media.get("member") != member or path in seen_media_paths:
                raise CommandError("Bundle media inventory contains an invalid path.")
            seen_media_paths.add(path)
            expected_members.add(member)
            size, checksum = _hash_archive_member(archive, member)
            if size != media.get("size") or checksum != media.get("sha256"):
                raise CommandError(f"Media checksum verification failed: {path}")

        if set(names) != expected_members:
            raise CommandError("Cutover bundle contains unexpected or unlisted members.")

    return manifest


def ensure_all_migrations_applied():
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if plan:
        raise CommandError(
            "Target database has unapplied migrations. Run migrate before restore."
        )


def ensure_empty_target():
    populated = {
        label: count for label, count in business_counts().items() if count
    }
    if populated:
        summary = ", ".join(f"{label}={count}" for label, count in populated.items())
        raise CommandError(
            "Refusing to restore into a non-empty target database. "
            f"Existing records: {summary}"
        )


def _verify_current_media(manifest, storage=default_storage):
    expected_paths = {media["path"] for media in manifest["media"]}
    current_paths = set(iter_storage_files(storage))
    if current_paths != expected_paths:
        missing = sorted(expected_paths - current_paths)
        extra = sorted(current_paths - expected_paths)
        raise CommandError(
            "Current media inventory does not exactly match the bundle. "
            f"Missing: {missing}; extra: {extra}."
        )

    for media in manifest["media"]:
        path = media["path"]
        if not storage.exists(path):
            raise CommandError(f"Restored media file is missing: {path}")
        with storage.open(path, "rb") as source:
            size, checksum = _copy_and_hash(source, _DiscardWriter())
        if size != media["size"] or checksum != media["sha256"]:
            raise CommandError(f"Restored media checksum does not match: {path}")


class _DiscardWriter:
    def write(self, value):
        return len(value)


def verify_against_current(bundle_path, storage=default_storage):
    manifest = validate_bundle(bundle_path)
    with transaction.atomic():
        current_counts = business_counts()
        if current_counts != manifest["models"]:
            raise CommandError(
                "Current database counts do not match the cutover bundle. "
                f"Expected {manifest['models']}; found {current_counts}."
            )
        current_data = serialize_business_data()
        if sha256_bytes(current_data) != manifest["database"]["sha256"]:
            raise CommandError(
                "Current business-data checksum does not match the bundle."
            )
    _verify_current_media(manifest, storage)
    return manifest


def restore_bundle(bundle_path, storage=default_storage, allow_non_mysql=False):
    manifest = validate_bundle(bundle_path)
    if connection.vendor != "mysql" and not allow_non_mysql:
        raise CommandError(
            "Cutover restore requires a MySQL target. "
            "The non-MySQL override is reserved for isolated tests."
        )

    ensure_all_migrations_applied()
    ensure_empty_target()

    existing_media = list(iter_storage_files(storage))
    if existing_media:
        sample = ", ".join(existing_media[:5])
        raise CommandError(
            "Refusing to restore into non-empty target media storage. "
            f"Existing files include: {sample}"
        )

    bundle_path = Path(bundle_path).expanduser().resolve()
    created_media = []
    try:
        with zipfile.ZipFile(bundle_path, mode="r") as archive:
            with archive.open(DATA_MEMBER) as source:
                data = source.read().decode("utf-8")
            # Keep deserialization lazy so dependency-ordered records (notably
            # users) are saved before later natural foreign keys are resolved.
            deserialized = serializers.deserialize("json", data)

            with transaction.atomic():
                for item in deserialized:
                    item.save()

                for media in manifest["media"]:
                    with archive.open(media["member"]) as source:
                        saved_name = storage.save(media["path"], File(source))
                    if saved_name != media["path"]:
                        storage.delete(saved_name)
                        raise CommandError(
                            "Media storage changed a restored filename: "
                            f"{media['path']} -> {saved_name}"
                        )
                    created_media.append(saved_name)

                sequence_sql = connection.ops.sequence_reset_sql(
                    no_style(), business_models()
                )
                with connection.cursor() as cursor:
                    for statement in sequence_sql:
                        cursor.execute(statement)

                if business_counts() != manifest["models"]:
                    raise CommandError(
                        "Post-restore database counts do not match the bundle."
                    )
                if (
                    sha256_bytes(serialize_business_data())
                    != manifest["database"]["sha256"]
                ):
                    raise CommandError(
                        "Post-restore business-data checksum does not match the bundle."
                    )
                _verify_current_media(manifest, storage)
    except Exception:
        for media_name in reversed(created_media):
            try:
                storage.delete(media_name)
            except Exception:
                # The original restore error is more useful; verification will
                # identify any leftover file before a retry.
                pass
        raise

    return manifest
