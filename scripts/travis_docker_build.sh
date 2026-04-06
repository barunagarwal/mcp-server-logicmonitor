#!/bin/bash
set -euo pipefail

# Travis CI Docker Build Script
# Builds and pushes the LogicMonitor MCP image to AWS ECR and/or GCR.
#
# Push targets:
#  - AWS ECR: 560269851512.dkr.ecr.us-west-2.amazonaws.com/mcp-server-logicmonitor
#  - GCR Non-Prod: eu.gcr.io/dexda-non-production/mcp-server-logicmonitor
#  - GCR Prod: eu.gcr.io/dexda-production/mcp-server-logicmonitor (tag builds only)

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="mcp-server-logicmonitor"
DOCKERFILE="$PROJECT_ROOT/deploy/Dockerfile"
CONTEXT="$PROJECT_ROOT"

AWS_REGION="${AWS_REGION:-us-west-2}"
ECR_HOST="560269851512.dkr.ecr.us-west-2.amazonaws.com"
ECR_IMAGE="${ECR_HOST}/${IMAGE_NAME}"
GCR_HOST="eu.gcr.io"
GCR_NP_IMAGE="${GCR_HOST}/dexda-non-production/${IMAGE_NAME}"
GCR_PRD_IMAGE="${GCR_HOST}/dexda-production/${IMAGE_NAME}"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERR ]${NC} $1"
}

get_branch() {
    local branch

    branch=$(git rev-parse --abbrev-ref HEAD)
    if [ -n "${TRAVIS_BRANCH:-}" ]; then
        branch="${TRAVIS_PULL_REQUEST_BRANCH:-$TRAVIS_BRANCH}"
    fi

    echo "$branch"
}

get_autobuild_line() {
    local branch=$1
    local autobuild_file="${PROJECT_ROOT}/AUTOBUILD"

    if [ ! -f "$autobuild_file" ]; then
        return 0
    fi

    awk -F: -v branch="$branch" '
        $0 !~ /^#/ && $1 == branch {
            print
            exit
        }
    ' "$autobuild_file"
}

should_build_image() {
    local image_name=$1
    local line=$2

    if [ -z "$line" ]; then
        return 1
    fi

    if [[ "$line" != *:* ]]; then
        return 0
    fi

    local selected_images=${line#*:}

    if echo "$selected_images" | tr ',' '\n' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | grep -Fxq "$image_name"; then
        return 0
    fi

    return 1
}

sanitize_branch_label() {
    local branch=$1
    local branch_label=${branch//\//_}
    branch_label=${branch_label//+/_}
    echo "$branch_label"
}

authenticate_google() {
    local name=$1
    local encoded_json=$2

    echo "$encoded_json" | base64 --decode | docker login -u _json_key --password-stdin "https://${GCR_HOST}"
    log_info "Authenticated with ${name} for ${GCR_HOST}"
}

authenticate_ecr() {
    aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_HOST"
    log_info "Authenticated with AWS ECR ${ECR_HOST}"
}

branch=$(get_branch)

if [ -n "${TRAVIS_PULL_REQUEST:-}" ] && [ "${TRAVIS_PULL_REQUEST}" != "false" ]; then
    log_info "Skipping Docker build on pull request for ${branch}"
    exit 0
fi

autobuild_line=""
if [ -z "${TRAVIS_TAG:-}" ] && [ -f "${PROJECT_ROOT}/AUTOBUILD" ]; then
    autobuild_line=$(get_autobuild_line "$branch")
    if [ -z "$autobuild_line" ]; then
        log_info "Skipping Docker build for branch '${branch}' (not listed in AUTOBUILD)"
        exit 0
    fi
fi

if [ -z "${TRAVIS_TAG:-}" ] && [ -f "${PROJECT_ROOT}/AUTOBUILD" ] && ! should_build_image "$IMAGE_NAME" "$autobuild_line"; then
    log_info "Skipping ${IMAGE_NAME} for branch '${branch}' (not selected in AUTOBUILD)"
    exit 0
fi

branch_label=$(sanitize_branch_label "$branch")
sha=$(git rev-parse --short HEAD)
ts=$(date +%Y%m%d_%H%M%S)
release_build=""

if [ -n "${TRAVIS_TAG:-}" ]; then
    release_build="true"
    tags=("${TRAVIS_TAG}" "${branch_label}-${sha}-${ts}" "${branch_label}-${sha}" "${branch_label}" "release")
    log_info "Building tagged release ${TRAVIS_TAG}"
elif [[ "$branch" =~ ^(main|master)(-.*)?$ ]]; then
    tags=("${branch_label}-${sha}-${ts}" "${branch_label}-${sha}" "${branch_label}" "latest")
else
    tags=("${branch_label}-${sha}-${ts}-SNAPSHOT" "${branch_label}-${sha}-SNAPSHOT" "${branch_label}")
fi

log_info "Preparing image build"
log_info "Branch: ${branch}"
log_info "Primary tag: ${tags[0]}"
log_info "All tags: ${tags[*]}"
echo ""

if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
    log_step "Authenticating with AWS ECR"
    authenticate_ecr
else
    log_warn "AWS credentials not present; skipping ECR push"
fi

if [ -n "${GCLOUD_SA_NON_PROD_JSON:-}" ]; then
    log_step "Authenticating with GCR non-prod"
    authenticate_google "GCLOUD_SA_NON_PROD_JSON" "$GCLOUD_SA_NON_PROD_JSON"
else
    log_warn "GCLOUD_SA_NON_PROD_JSON not present; skipping GCR non-prod push"
fi

if [ -n "$release_build" ] && [ -n "${GCLOUD_SA_PROD_JSON:-}" ]; then
    log_step "Authenticating with GCR prod"
    authenticate_google "GCLOUD_SA_PROD_JSON" "$GCLOUD_SA_PROD_JSON"
elif [ -n "$release_build" ]; then
    log_warn "GCLOUD_SA_PROD_JSON not present; skipping GCR prod push"
fi

log_step "Building ${IMAGE_NAME}"
docker build \
    -f "$DOCKERFILE" \
    -t "${IMAGE_NAME}:${tags[0]}" \
    "$CONTEXT"

for tag in "${tags[@]}"; do
    docker tag "${IMAGE_NAME}:${tags[0]}" "${IMAGE_NAME}:${tag}"

    if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
        docker tag "${IMAGE_NAME}:${tags[0]}" "${ECR_IMAGE}:${tag}"
    fi

    if [ -n "${GCLOUD_SA_NON_PROD_JSON:-}" ]; then
        docker tag "${IMAGE_NAME}:${tags[0]}" "${GCR_NP_IMAGE}:${tag}"
    fi

    if [ -n "$release_build" ] && [ -n "${GCLOUD_SA_PROD_JSON:-}" ]; then
        docker tag "${IMAGE_NAME}:${tags[0]}" "${GCR_PRD_IMAGE}:${tag}"
    fi
done

if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
    log_step "Pushing ${IMAGE_NAME} to AWS ECR"
    for tag in "${tags[@]}"; do
        docker push "${ECR_IMAGE}:${tag}"
    done
fi

if [ -n "${GCLOUD_SA_NON_PROD_JSON:-}" ]; then
    log_step "Pushing ${IMAGE_NAME} to GCR non-prod"
    for tag in "${tags[@]}"; do
        docker push "${GCR_NP_IMAGE}:${tag}"
    done
fi

if [ -n "$release_build" ] && [ -n "${GCLOUD_SA_PROD_JSON:-}" ]; then
    log_step "Pushing ${IMAGE_NAME} to GCR prod"
    for tag in "${tags[@]}"; do
        docker push "${GCR_PRD_IMAGE}:${tag}"
    done
fi

echo ""
echo "=========================================="
log_info "Build and push complete"
echo "=========================================="
echo ""
log_info "Published image targets:"
if [ -n "${AWS_ACCESS_KEY_ID:-}" ]; then
    echo "  - ${ECR_IMAGE}:${tags[0]}"
fi
if [ -n "${GCLOUD_SA_NON_PROD_JSON:-}" ]; then
    echo "  - ${GCR_NP_IMAGE}:${tags[0]}"
fi
if [ -n "$release_build" ] && [ -n "${GCLOUD_SA_PROD_JSON:-}" ]; then
    echo "  - ${GCR_PRD_IMAGE}:${tags[0]}"
fi
