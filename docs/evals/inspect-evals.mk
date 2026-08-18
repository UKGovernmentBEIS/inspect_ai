INSPECT_EVALS_PATH ?= ../inspect_evals

.PHONY: sync
sync:
	python docs/evals/sync_all.py --inspect-evals $(INSPECT_EVALS_PATH)
