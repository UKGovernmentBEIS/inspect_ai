INSPECT_EVALS_PATH ?= ../inspect_evals

.PHONY: sync
sync:
	python docs/evals/sync.py $(INSPECT_EVALS_PATH)

.PHONY: sync-harbor
sync-harbor:
	python docs/evals/sync_harbor.py

.PHONY: sync-all
sync-all: sync sync-harbor
