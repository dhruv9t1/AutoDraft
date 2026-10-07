#!/usr/bin/env bash
# Call Oracle OCI Vision analyzeImage API directly and print the raw JSON response.
# Requires: OCI credentials (from .env, .oci/config, or env) and an image file path.
#
# Usage (from backend/):
#   ./scripts/oci-vision-analyze-image.sh path/to/image.png
#   ./scripts/oci-vision-analyze-image.sh "Screenshot 2026-01-30 at 7.37.29 PM.png"   # quote paths with spaces
#
# Credentials: script loads backend/.env if present, then backend/.oci/config for any missing OCI_* vars.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env from backend (optional)
if [ -f "$BACKEND_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  . "$BACKEND_DIR/.env"
  set +a
fi

# Load missing OCI_* from backend/.oci/config if present (legacy OCI helper; separate from the FastAPI runtime)
OCI_CONFIG="$BACKEND_DIR/.oci/config"
if [ -f "$OCI_CONFIG" ]; then
  [ -z "${OCI_REGION:-}" ]       && OCI_REGION=$(grep -E '^\s*region\s*=' "$OCI_CONFIG" | head -1 | sed -E 's/.*=\s*//; s/\s*$//')
  [ -z "${OCI_TENANCY_OCID:-}" ] && OCI_TENANCY_OCID=$(grep -E '^\s*tenancy\s*=' "$OCI_CONFIG" | head -1 | sed -E 's/.*=\s*//; s/\s*$//')
  [ -z "${OCI_USER_OCID:-}" ]     && OCI_USER_OCID=$(grep -E '^\s*user\s*=' "$OCI_CONFIG" | head -1 | sed -E 's/.*=\s*//; s/\s*$//')
  [ -z "${OCI_FINGERPRINT:-}" ]   && OCI_FINGERPRINT=$(grep -E '^\s*fingerprint\s*=' "$OCI_CONFIG" | head -1 | sed -E 's/.*=\s*//; s/\s*$//')
  [ -z "${OCI_KEY_FILE:-}" ]     && OCI_KEY_FILE=$(grep -E '^\s*key_file\s*=' "$OCI_CONFIG" | head -1 | sed -E 's/.*=\s*//; s/\s*$//')
  [ -z "${OCI_COMPARTMENT_ID:-}" ] && OCI_COMPARTMENT_ID=$(grep -E '^\s*compartment_id\s*=' "$OCI_CONFIG" 2>/dev/null | head -1 | sed -E 's/.*=\s*//; s/\s*$//') || true
fi

# Default compartment to tenancy if not set
[ -z "${OCI_COMPARTMENT_ID:-}" ] && OCI_COMPARTMENT_ID="${OCI_TENANCY_OCID:-}"

# Required env vars
: "${OCI_REGION?Set OCI_REGION or add region= to backend/.oci/config}"
: "${OCI_COMPARTMENT_ID?Set OCI_COMPARTMENT_ID or OCI_TENANCY_OCID (or compartment_id in config)}"
: "${OCI_TENANCY_OCID?Set OCI_TENANCY_OCID or add tenancy= to $OCI_CONFIG}"
: "${OCI_USER_OCID?Set OCI_USER_OCID or add user= to $OCI_CONFIG}"
: "${OCI_FINGERPRINT?Set OCI_FINGERPRINT or add fingerprint= to $OCI_CONFIG}"
: "${OCI_KEY_FILE?Set OCI_KEY_FILE or add key_file= to $OCI_CONFIG}"

# Resolve key file relative to backend or .oci
KEY_PATH="$OCI_KEY_FILE"
if [ ! -f "$KEY_PATH" ]; then
  KEY_PATH="$BACKEND_DIR/.oci/$OCI_KEY_FILE"
fi
if [ ! -f "$KEY_PATH" ]; then
  KEY_PATH="$BACKEND_DIR/$OCI_KEY_FILE"
fi
if [ ! -f "$KEY_PATH" ]; then
  echo "ERROR: OCI key file not found: $OCI_KEY_FILE (tried $KEY_PATH)" >&2
  exit 1
fi

# Image path: use all args so paths with spaces work (e.g. "Screenshot 2026-01-30 at 7.37.29 PM.png")
if [ $# -eq 0 ]; then
  echo "Usage: $0 /path/to/image.png" >&2
  echo "Example: $0 \"Screenshot 2026-01-30 at 7.37.29 PM.png\"" >&2
  exit 1
fi
IMAGE_PATH="$*"
if [ ! -f "$IMAGE_PATH" ]; then
  # macOS Screenshot filenames use Unicode narrow no-break space (U+202F) before "PM"/"AM", not a regular space
  if [[ "$IMAGE_PATH" == *" PM."* ]]; then
    IMAGE_PATH_ALT="${IMAGE_PATH% PM.*}"$'\u202f'"PM.${IMAGE_PATH##*PM.}"
    [ -f "$IMAGE_PATH_ALT" ] && IMAGE_PATH="$IMAGE_PATH_ALT"
  fi
  if [ ! -f "$IMAGE_PATH" ] && [[ "$IMAGE_PATH" == *" AM."* ]]; then
    IMAGE_PATH_ALT="${IMAGE_PATH% AM.*}"$'\u202f'"AM.${IMAGE_PATH##*AM.}"
    [ -f "$IMAGE_PATH_ALT" ] && IMAGE_PATH="$IMAGE_PATH_ALT"
  fi
  if [ ! -f "$IMAGE_PATH" ]; then
    echo "ERROR: Image file not found: $IMAGE_PATH" >&2
    echo "Tip: macOS Screenshot filenames use a special space before PM/AM. Run: ls and copy the exact filename." >&2
    exit 1
  fi
fi

# Base64 image (no newlines)
IMAGE_B64="$(base64 < "$IMAGE_PATH" | tr -d '\n')"

# Request body (same as backend)
BODY_JSON=$(jq -n \
  --arg comp "$OCI_COMPARTMENT_ID" \
  --arg data "$IMAGE_B64" \
  '{ "compartmentId": $comp, "features": [ { "featureType": "TEXT_DETECTION" } ], "image": { "source": "INLINE", "data": $data } }')

# Host and path (same as backend)
HOST="vision.aiservice.${OCI_REGION}.oci.oraclecloud.com"
PATH_SPEC="/20220125/actions/analyzeImage"
URL="https://${HOST}${PATH_SPEC}"

# Date in GMT (required by OCI)
DATE_HEADER=$(date -u '+%a, %d %b %Y %H:%M:%S GMT')

# Body bytes and SHA256 for signing
BODY_BYTES=$(printf '%s' "$BODY_JSON")
CONTENT_LEN=${#BODY_BYTES}
CONTENT_TYPE="application/json"
X_CONTENT_SHA256=$(printf '%s' "$BODY_BYTES" | openssl dgst -sha256 -binary | base64 | tr -d '\n')

# Signing string (order must match "headers" in Authorization)
SIGNING_STRING="(request-target): post ${PATH_SPEC}
host: ${HOST}
date: ${DATE_HEADER}
content-type: ${CONTENT_TYPE}
content-length: ${CONTENT_LEN}
x-content-sha256: ${X_CONTENT_SHA256}"

# Sign with private key (RSA-SHA256), base64 encode
SIGNATURE_B64=$(printf '%s' "$SIGNING_STRING" | openssl dgst -sha256 -sign "$KEY_PATH" | base64 | tr -d '\n')

KEY_ID="${OCI_TENANCY_OCID}/${OCI_USER_OCID}/${OCI_FINGERPRINT}"
AUTH_HEADER="Signature version=\"1\",keyId=\"${KEY_ID}\",algorithm=\"rsa-sha256\",headers=\"(request-target) host date content-type content-length x-content-sha256\",signature=\"${SIGNATURE_B64}\""

# Call Oracle Vision API
echo "POST $URL" >&2
echo "Host: $HOST" >&2
echo "" >&2
RESPONSE=$(curl -s -w '\n%{http_code}' -X POST "$URL" \
  -H "Host: $HOST" \
  -H "Date: $DATE_HEADER" \
  -H "Content-Type: $CONTENT_TYPE" \
  -H "Content-Length: $CONTENT_LEN" \
  -H "x-content-sha256: $X_CONTENT_SHA256" \
  -H "Authorization: $AUTH_HEADER" \
  -d "$BODY_JSON")
HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')
if command -v jq >/dev/null 2>&1; then
  echo "$BODY" | jq .
else
  echo "$BODY"
  echo "" >&2
  echo "(Install jq for pretty-printed JSON: brew install jq)" >&2
fi
if [ "$HTTP_CODE" -ge 400 ]; then
  echo "HTTP $HTTP_CODE" >&2
  exit 1
fi
