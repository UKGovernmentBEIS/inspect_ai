from gaia import GAIA_DATASET_LOCATION
from huggingface_hub import snapshot_download

# Run this file to download the GAIA dataset.

GAIA_DATASET_LOCATION.mkdir(parents=True, exist_ok=True)
snapshot_download(
    repo_id="gaia-benchmark/GAIA",
    repo_type="dataset",
    local_dir=GAIA_DATASET_LOCATION,
)
