"""Parity oracle harness for skeleton-fed outline rows (epatey#23).

`oracle` is a frozen Python port of the legacy viewer outline pipeline;
`candidate` derives outline rows from a `SampleSkeleton` alone; `compare`
diffs the two row streams modulo the signed-off divergence allowances.
"""
