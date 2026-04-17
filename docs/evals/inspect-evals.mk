INSPECT_EVALS_PATH ?= ../inspect_evals

.PHONY: sync
sync:
	python docs/evals/sync.py $(INSPECT_EVALS_PATH)
