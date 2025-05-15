import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
from tqdm import tqdm

from inspect_ai._util.timer import execution_timer
from inspect_ai.analysis.beta import SampleSummary, samples_df
from inspect_ai.analysis.beta._dataframe.samples.columns import SampleMessages
from inspect_ai.log import list_eval_logs

if __name__ == "__main__":
    # with execution_timer("import"):
    #     df = samples_df(columns=SampleSummary + SampleMessages)
    #     df.info()

    with execution_timer("import parallel"):
        logs = [log.name for log in list_eval_logs()]

        # cap workers at 8 (as we eventually run into disk/memory contention)
        n_workers = max(min(mp.cpu_count(), 8), 1)

        dfs: list[pd.DataFrame | None] = [None] * len(logs)
        executor = ProcessPoolExecutor(max_workers=n_workers)
        try:
            futures = {
                executor.submit(
                    samples_df,
                    logs=log,
                    columns=SampleSummary + SampleMessages,
                    quiet=True,
                ): idx
                for idx, log in enumerate(logs)
            }
            for fut in tqdm(as_completed(futures), total=len(futures)):
                idx = futures[fut]
                dfs[idx] = fut.result()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        df = pd.concat(dfs, ignore_index=True)
        df.info()
