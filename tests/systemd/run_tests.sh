#!/bin/bash
set -euo pipefail

# Systemd installation integration tests for mercure.
# Tests fresh install and upgrade on Ubuntu 20.04, 22.04, 24.04.
#
# Usage: bash run_tests.sh [--ubuntu 24.04] [--skip-upgrade] [--keep-containers] [--verbose]
#        bash run_tests.sh --attach <container-name>   (re-attach to a kept container with port forwarding)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
UBUNTU_VERSIONS=("20.04" "22.04" "24.04")
SKIP_UPGRADE=false
KEEP_CONTAINERS=false
VERBOSE=false
ATTACH_CONTAINER=""
CONTAINERS_TO_CLEANUP=()

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ubuntu)
      UBUNTU_VERSIONS=("$2")
      shift 2
      ;;
    --skip-upgrade)
      SKIP_UPGRADE=true
      shift
      ;;
    --keep-containers)
      KEEP_CONTAINERS=true
      shift
      ;;
    --verbose|-v)
      VERBOSE=true
      shift
      ;;
    --attach)
      if [ -z "${2:-}" ]; then
        echo "Error: --attach requires a container name"
        echo "Available mercure test containers:"
        docker ps -a --filter "name=mercure-test-" --format "  {{.Names}}  ({{.Status}})"
        exit 1
      fi
      ATTACH_CONTAINER="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--ubuntu VERSION] [--skip-upgrade] [--keep-containers] [--verbose]"
      echo "       $0 --attach <container-name>"
      exit 1
      ;;
  esac
done

#
# Attach mode: forward ports from an existing kept container for manual inspection.
#
if [ -n "$ATTACH_CONTAINER" ]; then
  if ! docker inspect "$ATTACH_CONTAINER" &>/dev/null; then
    echo "Container '$ATTACH_CONTAINER' not found."
    echo "Available mercure test containers:"
    docker ps -a --filter "name=mercure-test-" --format "  {{.Names}}  ({{.Status}})"
    exit 1
  fi

  # Start the container if it's stopped
  if [ "$(docker inspect -f '{{.State.Running}}' "$ATTACH_CONTAINER")" != "true" ]; then
    echo "== Starting stopped container $ATTACH_CONTAINER..."
    docker start "$ATTACH_CONTAINER"
    sleep 3
  fi

  echo ""
  echo "  Web UI:  http://localhost:8000"
  echo "  DICOM:   localhost:11112"
  echo ""
  echo "  Logs:    docker exec $ATTACH_CONTAINER journalctl -f"
  echo ""

  docker exec -it "$ATTACH_CONTAINER" bash
fi

cleanup() {
  if [ "$KEEP_CONTAINERS" = true ]; then
    echo "== Keeping containers for inspection: ${CONTAINERS_TO_CLEANUP[*]}"
    return
  fi
  for cid in "${CONTAINERS_TO_CLEANUP[@]}"; do
    echo "== Cleaning up container $cid"
    docker rm -f "$cid" 2>/dev/null || true
  done
}
trap cleanup EXIT

#
# Determine the "old" tag for upgrade testing.
# If HEAD is tagged exactly, use the previous tag. Otherwise use the most recent tag.
#
resolve_upgrade_versions() {
  cd "$REPO_ROOT"
  local head_commit
  head_commit=$(git rev-parse HEAD)

  # Check if HEAD is exactly tagged
  local head_tag
  head_tag=$(git tag --points-at HEAD 2>/dev/null | grep -v '^latest' | head -1 || true)

  if [ -n "$head_tag" ]; then
    # HEAD is tagged — find the previous tag
    OLD_TAG=$(git tag --sort=-v:refname | grep -v '^latest' | grep -v "^${head_tag}$" | head -1)
    echo "HEAD is tagged as $head_tag; will upgrade from previous tag: $OLD_TAG"
  else
    # HEAD is untagged — use most recent tag
    OLD_TAG=$(git describe --tags --abbrev=0 HEAD 2>/dev/null)
    echo "HEAD is untagged ($(git describe --tags --always HEAD)); will upgrade from: $OLD_TAG"
  fi

  CURRENT_REF="$head_commit"
}

#
# Build the systemd base image for a given Ubuntu version.
#
build_image() {
  local ubuntu_version="$1"
  local image_tag="mercure-systemd-test:ubuntu-${ubuntu_version}"

  echo "== Building systemd test image for Ubuntu ${ubuntu_version}..." >&2
  docker build \
    --build-arg "UBUNTU_VERSION=${ubuntu_version}" \
    -t "$image_tag" \
    -f "$SCRIPT_DIR/Dockerfile.systemd" \
    "$SCRIPT_DIR" >&2

  echo "$image_tag"
}

#
# Start a privileged container running systemd as PID 1.
# Returns the container ID.
#
start_container() {
  local image_tag="$1"
  local container_name="$2"

  echo "== Starting container ${container_name}..." >&2
  docker run -d \
    --privileged \
    --cgroupns=host \
    --name "$container_name" \
    -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
    -p 8765:8000 \
    -p 33332:11112 \
    "$image_tag" >/dev/null

  CONTAINERS_TO_CLEANUP+=("$container_name")

  # Wait for systemd to be ready
  echo "== Waiting for systemd to initialize..." >&2
  local retries=30
  while [ $retries -gt 0 ]; do
    if docker exec "$container_name" systemctl is-system-running --wait 2>/dev/null | grep -qE "running|degraded"; then
      break
    fi
    sleep 1
    retries=$((retries - 1))
  done
  if [ $retries -eq 0 ]; then
    echo "WARN: systemd may not be fully ready, proceeding anyway" >&2
  fi
}

#
# Copy the repo into the container. Optionally check out a specific ref.
#
copy_repo() {
  local container_name="$1"
  local git_ref="${2:-}"

  echo "== Copying repo into container..."
  # Create a temporary archive of the repo (including untracked files)
  local tmparchive
  tmparchive=$(mktemp /tmp/mercure-repo-XXXXXX.tar)

  # Use git archive for the specific ref if given, otherwise tar the working tree
  if [ -n "$git_ref" ]; then
    echo "== Using git archive for ref: $git_ref"
    (cd "$REPO_ROOT" && git archive --format=tar "$git_ref") > "$tmparchive"
  else
    echo "== Using current working tree"
    (cd "$REPO_ROOT" && tar cf - \
      --exclude='.git' \
      --exclude='app/.venv' \
      --exclude='app/.mypy_cache' \
      --exclude='.mypy_cache' \
      --exclude='__pycache__' \
      .)  > "$tmparchive"
  fi

  docker exec "$container_name" mkdir -p /home/testuser/mercure
  docker cp "$tmparchive" "$container_name":/tmp/repo.tar
  docker exec "$container_name" bash -c "cd /home/testuser/mercure && tar xf /tmp/repo.tar && chown -R testuser:testuser /home/testuser/mercure"
  rm -f "$tmparchive"
}

#
# Run install.sh inside the container.
#
run_install() {
  local container_name="$1"
  local install_args="$2"

  echo "== Running: install.sh ${install_args}"
  local logfile="/tmp/mercure-install-${container_name}.log"
  # Run as root but with USER=testuser so install.sh skips the logname call.
  if [ "$VERBOSE" = true ]; then
    docker exec \
      -e USER=testuser \
      -w /home/testuser/mercure \
      "$container_name" \
      bash install.sh ${install_args} \
      2>&1 | tee "$logfile"
    local rc=${PIPESTATUS[0]}
  else
    docker exec \
      -e USER=testuser \
      -w /home/testuser/mercure \
      "$container_name" \
      bash install.sh ${install_args} \
      > "$logfile" 2>&1
    local rc=$?
    # Show last 30 lines for context
    echo "== Install output (last 30 lines):"
    tail -30 "$logfile"
  fi
  if [ $rc -ne 0 ]; then
    echo "== INSTALL FAILED (exit code $rc). Full log: $logfile"
    # Don't return 1 here — the LoadCredential fixup may repair the failure.
    # Service verification later will catch real failures.
  fi
}

#
# Fix credential drop-ins for Docker: LoadCredential doesn't work in containers,
# so replace any LoadCredential-based redis.conf with the EnvironmentFile variant.
#
fixup_credentials_for_docker() {
  local container_name="$1"

  local needs_fixup
  needs_fixup=$(docker exec "$container_name" bash -c '
    found=false
    for d in /etc/systemd/system/*.service.d; do
      [ -f "$d/redis.conf" ] && grep -q "LoadCredential" "$d/redis.conf" && found=true && break
    done
    echo $found
  ')

  if [ "$needs_fixup" != "true" ]; then
    echo "== No LoadCredential drop-ins found, skipping fixup"
    return
  fi

  echo "== Fixing credential drop-ins for Docker (LoadCredential unsupported)..."
  docker exec "$container_name" bash -c '
    envfile_conf="[Service]\nEnvironmentFile=/opt/mercure/config/redis.env\n"
    for d in /etc/systemd/system/*.service.d; do
      [ -f "$d/redis.conf" ] || continue
      if grep -q "LoadCredential" "$d/redis.conf"; then
        printf "$envfile_conf" > "$d/redis.conf"
      fi
    done
    # LoadCredential makes redis.env root:root 600; EnvironmentFile needs it
    # readable by the mercure user since services run as User=mercure
    chown mercure:mercure /opt/mercure/config/redis.env
    chmod 640 /opt/mercure/config/redis.env
    systemctl daemon-reload

    # install_services aborts before reaching workers because mercure_ui fails
    # with LoadCredential; enable and start everything now that drop-ins are fixed
    systemctl enable mercure_worker_fast@1 mercure_worker_fast@2 mercure_worker_slow@1 mercure_worker_slow@2 2>/dev/null || true
    systemctl restart mercure_bookkeeper mercure_cleaner mercure_dispatcher mercure_receiver mercure_router mercure_ui mercure_processor \
      mercure_worker_fast@1 mercure_worker_fast@2 mercure_worker_slow@1 mercure_worker_slow@2
  '
}

#
# Check that all mercure services are active.
#
verify_services() {
  local container_name="$1"
  local all_ok=true

  local services=(
    mercure_bookkeeper
    mercure_cleaner
    mercure_dispatcher
    mercure_receiver
    mercure_router
    mercure_ui
    mercure_processor
    "mercure_worker_fast@1"
    "mercure_worker_fast@2"
    "mercure_worker_slow@1"
    "mercure_worker_slow@2"
  )

  echo "== Verifying mercure services..."
  for svc in "${services[@]}"; do
    local status
    status=$(docker exec "$container_name" systemctl is-active "${svc}.service" 2>/dev/null || true)
    if [ "$status" = "active" ]; then
      echo "  [OK] ${svc}"
    else
      echo "  [FAIL] ${svc} — status: ${status}"
      # Show recent journal for debugging
      docker exec "$container_name" journalctl -u "${svc}.service" --no-pager -n 20 2>/dev/null || true
      all_ok=false
    fi
  done

  if [ "$all_ok" = false ]; then
    return 1
  fi
}

#
# Check that the web UI responds.
#
verify_webui() {
  local container_name="$1"

  echo "== Verifying web UI on port 8000..."
  local retries=10
  while [ $retries -gt 0 ]; do
    local http_code
    http_code=$(docker exec "$container_name" curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/login 2>/dev/null || echo "000")
    if [ "$http_code" = "200" ] || [ "$http_code" = "302" ]; then
      echo "  [OK] Web UI responded with HTTP ${http_code}"
      return 0
    fi
    echo "  Waiting for web UI (got HTTP ${http_code})..."
    sleep 3
    retries=$((retries - 1))
  done
  echo "  [FAIL] Web UI did not respond"
  return 1
}

#
# Stop all mercure services (needed before upgrade).
#
stop_services() {
  local container_name="$1"

  echo "== Stopping mercure services..."
  docker exec "$container_name" bash -c '
    sudo systemctl stop mercure_worker_fast@1 mercure_worker_fast@2 mercure_worker_slow@1 mercure_worker_slow@2 || true
    sudo systemctl stop mercure_ui mercure_processor mercure_router mercure_dispatcher mercure_cleaner mercure_receiver mercure_bookkeeper || true
  '
  sleep 2
}

## ============================================================
## Test phases
## ============================================================

test_fresh_install() {
  local ubuntu_version="$1"
  local container_name="mercure-test-fresh-${ubuntu_version//./-}"

  echo ""
  echo "============================================================"
  echo "  FRESH INSTALL TEST — Ubuntu ${ubuntu_version}"
  echo "============================================================"

  local image_tag
  image_tag=$(build_image "$ubuntu_version")

  start_container "$image_tag" "$container_name"
  copy_repo "$container_name"
  run_install "$container_name" "-y systemd"
  fixup_credentials_for_docker "$container_name"

  echo "== Waiting for services to stabilize..."
  sleep 15

  if ! verify_services "$container_name"; then
    echo "  FRESH INSTALL — Ubuntu ${ubuntu_version} — FAILED (services)"
    return 1
  fi
  if ! verify_webui "$container_name"; then
    echo "  FRESH INSTALL — Ubuntu ${ubuntu_version} — FAILED (webui)"
    return 1
  fi

  echo ""
  echo "  FRESH INSTALL — Ubuntu ${ubuntu_version} — PASSED"
  echo ""
}

test_upgrade() {
  local ubuntu_version="$1"
  local container_name="mercure-test-upgrade-${ubuntu_version//./-}"

  echo ""
  echo "============================================================"
  echo "  UPGRADE TEST — Ubuntu ${ubuntu_version}"
  echo "  Old: ${OLD_TAG} -> New: $(cd "$REPO_ROOT" && git describe --tags --always HEAD)"
  echo "============================================================"

  local image_tag
  image_tag=$(build_image "$ubuntu_version")

  start_container "$image_tag" "$container_name"

  # Phase 1: Install old version
  echo "== Phase 1: Installing old version (${OLD_TAG})..."
  copy_repo "$container_name" "$OLD_TAG"
  run_install "$container_name" "-y systemd"
  fixup_credentials_for_docker "$container_name"

  echo "== Waiting for services to stabilize..."
  sleep 15

  if ! verify_services "$container_name"; then
    echo "  UPGRADE TEST — Ubuntu ${ubuntu_version} — FAILED (old version services)"
    return 1
  fi
  if ! verify_webui "$container_name"; then
    echo "  UPGRADE TEST — Ubuntu ${ubuntu_version} — FAILED (old version webui)"
    return 1
  fi

  # Phase 2: Upgrade to current version
  echo "== Phase 2: Upgrading to current version..."
  stop_services "$container_name"
  copy_repo "$container_name"  # current working tree
  run_install "$container_name" "-y systemd -u"
  fixup_credentials_for_docker "$container_name"

  echo "== Waiting for services to stabilize..."
  sleep 15

  if ! verify_services "$container_name"; then
    echo "  UPGRADE TEST — Ubuntu ${ubuntu_version} — FAILED (upgraded services)"
    return 1
  fi
  if ! verify_webui "$container_name"; then
    echo "  UPGRADE TEST — Ubuntu ${ubuntu_version} — FAILED (upgraded webui)"
    return 1
  fi

  echo ""
  echo "  UPGRADE TEST — Ubuntu ${ubuntu_version} — PASSED"
  echo ""
}

## ============================================================
## Main
## ============================================================

main() {
  local failures=0

  if [ "$SKIP_UPGRADE" = false ]; then
    resolve_upgrade_versions
  fi

  for version in "${UBUNTU_VERSIONS[@]}"; do
    if ! test_fresh_install "$version"; then
      echo "  FRESH INSTALL — Ubuntu ${version} — FAILED"
      failures=$((failures + 1))
    fi

    if [ "$SKIP_UPGRADE" = false ]; then
      if ! test_upgrade "$version"; then
        echo "  UPGRADE TEST — Ubuntu ${version} — FAILED"
        failures=$((failures + 1))
      fi
    fi
  done

  echo ""
  echo "============================================================"
  if [ $failures -eq 0 ]; then
    echo "  ALL TESTS PASSED"
  else
    echo "  ${failures} TEST(S) FAILED"
  fi
  echo "============================================================"

  return $failures
}

main
