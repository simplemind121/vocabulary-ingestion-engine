# Production operations

This runbook covers the single-VPS production topology shipped in `docker-compose.yml`: API, migration job, Celery worker, PostgreSQL, Redis, and SeaweedFS S3-compatible object storage. PostgreSQL, Redis, and object storage are private to the Compose network. The API binds to `127.0.0.1` by default so a TLS reverse proxy can be the only public entry point.

## Clean install

Requirements:

- A current 64-bit Linux VPS with Docker Engine and Docker Compose v2.
- A TLS reverse proxy such as Caddy, nginx, or the provider load balancer.
- Enough persistent disk for the source pages, database, and at least two retained backups.

Create the configuration and replace every placeholder. The PostgreSQL password in `DATABASE_URL` must exactly match `POSTGRES_PASSWORD`.

```bash
cp .env.example .env
chmod 600 .env
openssl rand -hex 32  # use separately for POSTGRES_PASSWORD, S3 secret, and VIE_API_KEY
docker compose config --quiet
docker compose up --detach --build --wait --wait-timeout 180
curl --fail http://127.0.0.1:8000/health/ready
```

A ready deployment returns database, Redis, and storage as `ok`. Do not route public traffic until this endpoint succeeds. Keep port 8000 private or firewall-restricted; expose it through HTTPS only.

The production image includes Tesseract with English and Simplified Chinese
language data. Compose selects it through `VIE_OCR_ENGINE=tesseract` and
`VIE_OCR_LANGUAGES=eng+chi_sim`. Missing native text pages are rendered and sent
through OCR; low-confidence blocks remain blocking review work. Change the
engine or languages only after the production smoke test succeeds with the new
runtime.

For an automated destructive test using disposable volumes, run `scripts/compose-smoke.sh`. It builds all services, applies migrations, checks the worker and object storage, then proves backup and restore before deleting only its temporary project and volumes.

## Authentication and secrets

All `/api/` routes require `Authorization: Bearer <VIE_API_KEY>` when the key is configured. The production Compose file requires it. Liveness and readiness remain unauthenticated for the orchestrator.

- Never commit `.env` or reuse the example values.
- Give `.env` mode `0600` and restrict host login access.
- Terminate TLS before the API and rotate the API token if it is disclosed.
- Do not publish PostgreSQL, Redis, or object-storage ports.
- The API and worker run as a non-root user with a read-only container filesystem and `no-new-privileges`.
- Backups contain source-derived and possibly copyrighted data; encrypt them at rest and restrict access.

## Backup

Backups are consistent across PostgreSQL, the application data volume, and the S3 bucket. The script briefly stops API and worker writers, creates checksummed archives, and restarts services that were running.

```bash
scripts/backup.sh /srv/vie-backups/vie-$(date -u +%Y%m%dT%H%M%SZ)
```

Copy the completed directory to a different machine or storage provider. A backup is not considered valid until its `SHA256SUMS` verifies and a restore drill has succeeded. Keep at least one pre-upgrade backup and a retention policy appropriate to the source-data license.

## Restore

Restore is destructive and therefore requires the literal `--confirm` flag. It verifies all checksums, replaces the database schema, S3 bucket contents, and application volume, then waits for API and worker readiness.

```bash
scripts/restore.sh --confirm /srv/vie-backups/vie-20260930T120000Z
curl --fail http://127.0.0.1:8000/health/ready
```

Use a backup created by the same application version. The restore script deletes current production state inside the three scoped stores; it does not touch unrelated Docker projects or host paths.

## Upgrade

1. Create and externally copy a backup.
2. Record the current Git tag or `VIE_IMAGE` value.
3. Fetch and check out the target release, or set `VIE_IMAGE` to its immutable image tag.
4. Review release notes and configuration changes.
5. Run `docker compose config --quiet`.
6. Run `docker compose up --detach --build --wait --wait-timeout 180`.
7. Verify readiness, `alembic_version`, worker ping, and a representative authenticated API request.

The dedicated `migrate` service must finish successfully before API or worker start. Application startup never creates database tables implicitly.

## Rollback

1. Stop public traffic.
2. Check out the recorded previous Git tag or restore the previous immutable `VIE_IMAGE`.
3. Run `docker compose build` if the deployment builds locally.
4. Restore the pre-upgrade backup with `scripts/restore.sh --confirm ...`.
5. Verify readiness and a representative Gold download before reopening traffic.

Database downgrades are performed by restoring the matching snapshot, not by guessing at reverse migrations. This also restores matching source artifacts and object-store data.

## Routine checks

```bash
docker compose ps
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
docker compose exec -T worker celery -A app.worker.celery_app inspect ping --timeout 5
docker compose exec -T api alembic current
```

Investigate any restart loop, `not_ready` result, open required review, or failed Gate before publishing Gold. Never bypass a Gate to recover availability.
