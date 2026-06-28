# Image "B" for the sandbox-fingerprint drift regression test: an Alpine-based image.
# Has a different image id AND a different OS than Dockerfile.a, yet is published
# behind the SAME mutable tag (inspect-fingerprint-drift:latest) — the recipe path
# cannot distinguish the two, but the recorded fingerprint can.
FROM alpine:3.19
