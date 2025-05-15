import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm

from inspect_ai.analysis.beta import SampleSummary, samples_df
from inspect_ai.log import list_eval_logs

if __name__ == "__main__":
    logs = [log.name for log in list_eval_logs()]
    n_workers = max(mp.cpu_count() - 1, 1)

    dfs: list[pd.DataFrame] = []
    executor = ProcessPoolExecutor(max_workers=n_workers)
    try:
        futures = [executor.submit(samples_df, log, SampleSummary) for log in logs]
        for fut in tqdm(as_completed(futures), total=len(futures), smoothing=0.1):
            dfs.append(fut.result())
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    df = pd.concat(dfs, ignore_index=True)
    df.info()
