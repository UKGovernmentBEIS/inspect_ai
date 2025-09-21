

# scans/
    {timestamp}-{scanname}-{scanid}/
        scan.metadata
        1.parquet
        2.parquet
        3.parquet
   
   


# table: transcripts (all metadata: model_name, task_args, scores)

# table: results (transcript_id, sample_id, message_id, value, metadata, references)


transcripts/
    1.parquet
    2.parquet

scans/
    scan-{scanid}/
        1.parquet
        2.parquet
        3.parquet

# scans/
#   timestamp-scanname-scan-id/
       <timestamp>-<scanname>-<scanid>.parquet
       
#      scan.json
#      reward_hacking.parquet
#      duplicate_messages.parquet


# scorer: Scorer | Scanner[Transcript]

# eval(scorer=reward_hacking())

# scan_resume(scan_id="foo")

scan_results(scan_id, "reward_hacking")


# inspect scan --transcripts="logs" scanner.py
