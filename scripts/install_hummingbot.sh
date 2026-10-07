#!/usr/bin/env bash
# Run inside the selected Hummingbot environment, not the host's Python.
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hb_dir="${1:-/home/hummingbot}"
compatibility="${2:-}"
if [[ -n "$compatibility" && "$compatibility" != "--with-compatibility" ]]; then
  echo "Second argument must be --with-compatibility or omitted" >&2
  exit 1
fi
if [[ ! -d "$hb_dir/hummingbot/strategy_v2" ]]; then
  echo "Expected a Hummingbot source environment at the supplied path" >&2
  exit 1
fi
# Abort before installing or copying anything if the connector/network differs.
python "$repo_dir/scripts/check_mainnet.py"
if [[ "$compatibility" == "--with-compatibility" ]]; then
  python "$repo_dir/scripts/hummingbot_compat.py" --hb-dir "$hb_dir"
fi
# Build from a temporary code copy so a read-only repository remains clean.
package_dir="$(mktemp -d)"
cp "$repo_dir/pyproject.toml" "$package_dir/pyproject.toml"
cp -R "$repo_dir/agents" "$repo_dir/src" "$package_dir/"
python -m pip install --no-build-isolation --no-deps "$package_dir"
if [[ "$compatibility" == "--with-compatibility" ]]; then
  python "$repo_dir/scripts/hummingbot_compat.py" --hb-dir "$hb_dir" --apply
fi
install -d "$hb_dir/controllers/directional_trading" "$hb_dir/conf/controllers" "$hb_dir/conf/scripts"
# Same single file Condor syncs from the agent folder.
install -m 644 "$repo_dir/condor/flyby/controllers/derive_cesf_long_vol/derive_cesf_long_vol.py" \
  "$hb_dir/controllers/directional_trading/derive_cesf_long_vol.py"
for profile in eth btc sol hype; do
  install -m 644 "$repo_dir/conf/controllers/conf_flyby_$profile.yml" "$hb_dir/conf/controllers/conf_flyby_$profile.yml"
done
for profile in eth sol; do
  install -m 644 "$repo_dir/conf/controllers/conf_flyby_${profile}_active.yml" "$hb_dir/conf/controllers/conf_flyby_${profile}_active.yml"
done
for profile in eth btc; do
  install -m 644 "$repo_dir/conf/controllers/conf_flyby_options_$profile.yml" "$hb_dir/conf/controllers/conf_flyby_options_$profile.yml"
done
install -m 644 "$repo_dir/conf/controllers/conf_flyby_eth_exposure_test.yml" "$hb_dir/conf/controllers/conf_flyby_eth_exposure_test.yml"
install -m 644 "$repo_dir/conf/scripts/conf_v2_flyby.yml" "$hb_dir/conf/scripts/conf_v2_flyby.yml"
install -m 644 "$repo_dir/conf/scripts/conf_v2_flyby_eth_sol_active.yml" "$hb_dir/conf/scripts/conf_v2_flyby_eth_sol_active.yml"
echo "Installed mainnet-only paused profiles (derive_perpetual, legacy v2 API)."
echo "No account verified or bot started; the team supplies credentials and clears launch gates."
echo "Connector compatibility is opt-in; Flyby refuses entry without it and a fresh full margin snapshot."
echo "Optional atomic RFQ profiles are installed paused and NOT selected by the default launcher."
echo "The separate ETH 40%/75% exposure test is paused; it does not replace the fixed submission identity."
echo "ETH+SOL operator activation profiles are installed separately; select their launcher only after account preflight."
