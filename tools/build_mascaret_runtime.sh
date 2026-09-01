#!/usr/bin/env bash
# Build the reviewed official MASCARET target into an isolated output directory.
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <cache-directory> <output-directory>" >&2
  exit 2
fi

cache_dir="$(realpath -m "$1")"
output_dir="$(realpath -m "$2")"
repository_root="$(pwd -P)"
case "$cache_dir/" in
  "$repository_root/"*) ;;
  *) echo "cache directory must be inside the repository workspace" >&2; exit 2 ;;
esac
case "$output_dir/" in
  "$repository_root/"*) ;;
  *) echo "output directory must be inside the repository workspace" >&2; exit 2 ;;
esac
source_archive="$cache_dir/telemac-mascaret-v9.1.1-1fe3b514.tar.gz"
source_dir="$output_dir/source"
build_dir="$output_dir/build"
source_url='https://gitlab.pam-retd.fr/api/v4/projects/otm%2Ftelemac-mascaret/repository/archive.tar.gz?sha=1fe3b5141f7d9c9fa8fe6d6d0316c994a39c2d95'
source_sha256='54b52798435baeb294ad3418c2fe146b5c10ef0d6e8e3e9d72d606e0f9fdb5e3'

mkdir -p "$cache_dir" "$output_dir"
if [[ ! -f "$source_archive" ]]; then
  curl --fail --location --retry 3 --output "$source_archive" "$source_url"
fi
echo "$source_sha256  $source_archive" | sha256sum --check --strict
rm -rf "$source_dir" "$build_dir"
mkdir -p "$source_dir"
tar --extract --gzip --file "$source_archive" --directory "$source_dir" --strip-components=1
cmake -S "$source_dir" -B "$build_dir" \
  -DCMAKE_BUILD_TYPE=Release \
  -DUSE_MPI=OFF \
  -DUSE_MED=OFF \
  -DUSE_MUMPS=OFF \
  -DBUILD_TELAPY=OFF \
  -DBUILD_HERMES_WRAPPER=OFF
cmake --build "$build_dir" --target homere_mascaret --parallel 2
test -x "$build_dir/bin/mascaret"
test -f "$build_dir/lib/libmascaret.so"
